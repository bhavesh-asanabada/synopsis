"""OAuth-connected cloud copies of originals; local files remain the OCR source."""
import base64
import hashlib
import hmac
import mimetypes
import re
import secrets
import time
from functools import wraps
from threading import Event, RLock, Thread
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

import requests
from flask import Blueprint, abort, jsonify, redirect, request
from werkzeug.utils import secure_filename

from .storage import now

PROVIDERS = {'google': 'Google Drive', 'onedrive': 'OneDrive'}
GOOGLE = 'https://www.googleapis.com/drive/v3'
GRAPH = 'https://graph.microsoft.com/v1.0'
SCOPES = {'google': 'https://www.googleapis.com/auth/drive.file',
          'onedrive': 'offline_access https://graph.microsoft.com/Files.ReadWrite'}


class CloudError(ValueError):
    pass


def http(method, url, **kwargs):
    try:
        response = requests.request(method, url, timeout=(10, 120), allow_redirects=False, **kwargs)
    except requests.RequestException:
        raise CloudError('Cloud service unavailable. Your local document is safe; retry the transfer.') from None
    if response.status_code not in (200, 201, 204, 404, 409):
        if response.status_code in (401, 403):
            raise CloudError('Cloud access was denied. Check account permissions or reconnect in Settings.')
        if response.status_code == 429:
            raise CloudError('The cloud service is busy. Wait a moment, then retry.')
        raise CloudError('Cloud request failed. Check account storage and connectivity, then retry.')
    return response


def data(response):
    if response.status_code not in (200, 201):
        raise CloudError('Cloud folder or file is unavailable. Check the connection in Settings.')
    try:
        result = response.json()
        if not isinstance(result, dict): raise ValueError()
        return result
    except (ValueError, TypeError):
        raise CloudError('The cloud provider returned an invalid response.') from None


class CloudStorage:
    def __init__(self, store):
        self.store = store
        self.lock = RLock()
        self.pending = {}
        self.stop_event = Event()
        self.thread = None

    def config(self, provider):
        return self.store.setting('cloud:' + provider, {})

    def synchronized(self, fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not self.lock.acquire(blocking=False):
                abort(409, description='A cloud transfer is in progress. Try this action after it finishes.')
            try:
                return fn(*args, **kwargs)
            finally:
                self.lock.release()
        return wrapped

    def save(self, provider, config):
        self.store.set_setting('cloud:' + provider, config)

    def public(self, origin):
        result = {}
        for provider, name in PROVIDERS.items():
            c = self.config(provider)
            result[provider] = {key: c.get(key, '') for key in ('clientId', 'tenant', 'folderName', 'account', 'folderUrl')}
            result[provider].update(name=name, connected=bool(c.get('refreshToken')), hasClientSecret=bool(c.get('clientSecret')),
                                    redirectUri=origin + '/api/connectors/' + provider + '/callback')
        return {'destination': self.store.setting('cloudDestination', 'local'), 'providers': result}

    def configure(self, provider, values):
        c = self.config(provider)
        if c.get('refreshToken'):
            raise ValueError('Disconnect this account before changing its application settings.')
        fields = {}
        for key, default, limit in (('clientId', '', 500), ('clientSecret', '', 4096), ('tenant', 'common', 100), ('folderName', 'Synopsis', 100)):
            value = values.get(key, default)
            if not isinstance(value, str) or len(value) > limit or any(ord(v) < 32 for v in value):
                raise ValueError('Enter valid connector settings.')
            fields[key] = value.strip()
        if not fields['clientId']: raise ValueError('An OAuth application client ID is required.')
        if not re.fullmatch(r'[A-Za-z0-9.-]+', fields['tenant']): raise ValueError('Enter a valid Microsoft tenant ID or common.')
        if not fields['folderName'] or re.search(r'["*:<>?/\\|#%]', fields['folderName']) or fields['folderName'].endswith('.'):
            raise ValueError('Use a simple folder name without path separators or reserved characters.')
        if not fields['clientSecret'] and fields['clientId'] == c.get('clientId') and fields['tenant'] == c.get('tenant'):
            fields['clientSecret'] = c.get('clientSecret', '')
        if not fields['clientSecret']: raise ValueError('An OAuth web application client secret is required.')
        self.save(provider, fields)
        self.pending.pop(provider, None)

    def token_url(self, provider, c):
        return 'https://oauth2.googleapis.com/token' if provider == 'google' else f'https://login.microsoftonline.com/{c["tenant"]}/oauth2/v2.0/token'

    def begin(self, provider, origin):
        c = self.config(provider)
        if not c.get('clientId') or not c.get('clientSecret'): raise ValueError('Save OAuth application settings before connecting.')
        state, verifier, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        callback = origin + '/api/connectors/' + provider + '/callback'
        self.pending[provider] = {'state': state, 'verifier': verifier, 'binding': binding, 'expires': time.time()+600, 'callback': callback}
        params = {'client_id': c['clientId'], 'redirect_uri': callback, 'response_type': 'code', 'scope': SCOPES[provider],
                  'state': state, 'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),
                  'code_challenge_method': 'S256'}
        if provider == 'google':
            url = 'https://accounts.google.com/o/oauth2/v2/auth'
            params.update(access_type='offline', prompt='consent')
        else:
            url = f'https://login.microsoftonline.com/{c["tenant"]}/oauth2/v2.0/authorize'
            params.update(response_mode='query', prompt='select_account')
        return url + '?' + urlencode(params), binding

    def token(self, provider, c, fields):
        payload = {'client_id': c['clientId'], 'client_secret': c['clientSecret'], **fields}
        if provider == 'onedrive': payload['scope'] = SCOPES[provider]
        value = data(http('POST', self.token_url(provider, c), data=payload))
        if not isinstance(value.get('access_token'), str) or not value['access_token']:
            raise CloudError('No cloud access token received. Reconnect the account.')
        refresh = value.get('refresh_token') or c.get('refreshToken')
        if not isinstance(refresh, str) or not refresh:
            raise CloudError('Offline access was not granted. Reconnect and allow offline file access.')
        return {**c, 'accessToken': value['access_token'], 'refreshToken': refresh,
                'expiresAt': time.time() + max(0, int(value.get('expires_in', 3600)))}

    def finish(self, provider, args, binding):
        pending = self.pending.get(provider)
        if not pending or pending['expires'] < time.time() or not hmac.compare_digest(args.get('state', ''), pending['state']) or not hmac.compare_digest(binding, pending['binding']):
            raise ValueError('This connection request expired or belongs to another browser. Start again in Settings.')
        self.pending.pop(provider)
        if args.get('error'): raise ValueError('Sign-in was canceled or access was denied. Try connecting again.')
        code = args.get('code', '')
        if not code or len(code) > 8192: raise ValueError('No valid authorization code was received.')
        c = self.config(provider)
        if c.get('refreshToken'): raise ValueError('Disconnect the current account before connecting another.')
        c = self.token(provider, c, {'grant_type': 'authorization_code', 'code': code,
                                    'redirect_uri': pending['callback'], 'code_verifier': pending['verifier']})
        headers = {'Authorization': 'Bearer ' + c['accessToken']}
        if provider == 'google':
            user = data(http('GET', GOOGLE+'/about', headers=headers, params={'fields': 'user'})).get('user', {})
            c.update(account=user.get('emailAddress') or user.get('displayName') or 'Google Drive', accountId=user.get('permissionId', ''))
            folder = data(http('POST', GOOGLE+'/files', headers=headers,
                               json={'name': c['folderName'], 'mimeType': 'application/vnd.google-apps.folder'},
                               params={'fields': 'id,webViewLink'}))
            c['folderUrl'] = folder.get('webViewLink', '')
        else:
            drive = data(http('GET', GRAPH+'/me/drive', headers=headers, params={'$select': 'id,owner'}))
            user = drive.get('owner', {}).get('user', {})
            c.update(account=user.get('email') or user.get('displayName') or 'OneDrive', accountId=drive['id'])
            folder_url = GRAPH+'/me/drive/root:/'+quote(c['folderName'], safe='')
            response = http('GET', folder_url, headers=headers)
            if response.status_code == 404:
                response = http('POST', GRAPH+'/me/drive/root/children', headers=headers,
                                json={'name': c['folderName'], 'folder': {}, '@microsoft.graph.conflictBehavior': 'fail'})
                if response.status_code == 409: response = http('GET', folder_url, headers=headers)
            folder = data(response)
            if 'folder' not in folder: raise ValueError('The chosen OneDrive folder name belongs to a file. Choose another name.')
            c['folderUrl'] = folder.get('webUrl', '')
        if not isinstance(folder.get('id'), str) or not folder['id']: raise CloudError('No cloud folder was returned.')
        c.update(folderId=folder['id'], connectionId=str(uuid4()))
        self.save(provider, c)

    def access(self, provider, c):
        if not c.get('refreshToken'): raise CloudError('This cloud account is disconnected. Connect it in Settings.')
        if c.get('expiresAt', 0) < time.time()+60:
            c = self.token(provider, c, {'grant_type': 'refresh_token', 'refresh_token': c['refreshToken']})
            self.save(provider, c)
        return c

    def disconnect(self, provider):
        c = self.config(provider)
        self.save(provider, {k: c.get(k, '') for k in ('clientId', 'clientSecret', 'tenant', 'folderName')})
        self.pending.pop(provider, None)
        if self.store.setting('cloudDestination') == provider: self.store.set_setting('cloudDestination', 'local')
        for item in self.store.items():
            job = item.get('cloudStorage', {})
            if job.get('provider') == provider and job.get('status') in ('queued', 'uploading'):
                self.store.update(item['id'], {'cloudStorage': {**job, 'status': 'error', 'error': 'Account disconnected. Connect and save this document to cloud again.'}})

    def destination(self, value):
        if value not in ('local', *PROVIDERS): raise ValueError('Choose local storage, Google Drive, or OneDrive.')
        if value != 'local' and not self.config(value).get('refreshToken'): raise ValueError('Connect the cloud account before selecting it.')
        self.store.set_setting('cloudDestination', value)

    def enqueue(self, item_id, explicit=False):
        # Snapshot credentials/destination without waiting for a network transfer.
        # A disconnected/replaced connection is rejected again by the worker.
        item = self.store.get(item_id)
        if not item or not item.get('filePath') or item.get('trashed'): return
        old = item.get('cloudStorage', {})
        if old and not explicit: return
        if old.get('status') == 'uploading': raise ValueError('This cloud transfer is already in progress.')
        provider = self.store.setting('cloudDestination', 'local')
        if provider == 'local':
            if explicit: raise ValueError('Choose a cloud destination in Settings first.')
            return
        c = self.config(provider)
        if not c.get('refreshToken'):
            if explicit: raise ValueError('Connect the cloud account in Settings first.')
            self.store.update(item_id, {'cloudStorage': {'provider': provider, 'connectionId': '', 'status': 'error', 'error': 'Account disconnected during intake. Connect and use Save to cloud.'}})
            return
        if old.get('provider') == provider and old.get('connectionId') == c['connectionId']:
            if old.get('status') == 'saved': return
            job = {**old, 'status': 'queued', 'error': ''}
        else:
            job = {'provider': provider, 'connectionId': c['connectionId'], 'folderId': c['folderId'], 'status': 'queued', 'error': ''}
        self.store.update(item_id, {'cloudStorage': job})

    def retry(self, item_id):
        item = self.store.get(item_id)
        job = item.get('cloudStorage', {}) if item else {}
        if not job or job.get('status') != 'error': raise ValueError('There is no failed cloud transfer to retry.')
        if job['connectionId'] != self.config(job['provider']).get('connectionId'):
            raise ValueError('The account connection changed. Use Save to cloud to choose the current destination.')
        self.store.update(item_id, {'cloudStorage': {**job, 'status': 'queued', 'error': ''}})

    def transfer(self, item_id):
        with self.lock:
            item = self.store.get(item_id)
            job = item.get('cloudStorage', {}) if item else {}
            if not job or job.get('status') not in ('queued', 'uploading'): return
            if item.get('trashed'):
                self.store.update(item_id, {'cloudStorage': {**job, 'status': 'error', 'error': 'Document is in Trash. Restore it before retrying.'}})
                return
            job = {**job, 'status': 'uploading', 'error': ''}
            self.store.update(item_id, {'cloudStorage': job})
            try:
                provider = job['provider']
                c = self.config(provider)
                if job['connectionId'] != c.get('connectionId'): raise CloudError('Account connection changed. Use Save to cloud to choose the current destination.')
                c = self.access(provider, c)
                path = self.store.document_path(item)
                size = path.stat().st_size
                if not 0 < size <= 100*1024*1024: raise CloudError('Cloud documents must be between 1 byte and 100 MB.')
                headers = {'Authorization': 'Bearer ' + c['accessToken']}
                mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                if provider == 'google':
                    if not job.get('remoteId'):
                        job['remoteId'] = data(http('GET', GOOGLE+'/files/generateIds', headers=headers, params={'count': 1, 'space': 'drive'}))['ids'][0]
                        self.store.update(item_id, {'cloudStorage': job})
                    remote = GOOGLE+'/files/'+quote(job['remoteId'], safe='')
                    fields = {'fields': 'id,size,md5Checksum,webViewLink,trashed'}
                    response = http('GET', remote, headers=headers, params=fields)
                    if response.status_code == 404:
                        response = http('POST', 'https://www.googleapis.com/upload/drive/v3/files', headers={**headers, 'X-Upload-Content-Type': mime, 'X-Upload-Content-Length': str(size)},
                                        params={'uploadType': 'resumable', **fields}, json={'id': job['remoteId'], 'name': item['fileName'], 'parents': [job['folderId']]})
                        if response.status_code == 409:
                            response = http('GET', remote, headers=headers, params=fields)
                        else:
                            location = response.headers.get('Location', '')
                            parsed = urlsplit(location)
                            if parsed.scheme != 'https' or parsed.netloc != 'www.googleapis.com' or not parsed.path.startswith('/upload/'):
                                raise CloudError('Invalid Google Drive upload session. Retry the transfer.')
                            with path.open('rb') as stream:
                                response = http('PUT', location, headers={**headers, 'Content-Type': mime, 'Content-Length': str(size)}, data=stream)
                    result = data(response)
                    with path.open('rb') as stream: checksum = hashlib.file_digest(stream, 'md5').hexdigest()
                    if result.get('md5Checksum') != checksum or result.get('trashed'):
                        raise CloudError('The remote document does not match the local original. Check the cloud copy.')
                    url = result.get('webViewLink', '') or 'https://drive.google.com/file/d/'+quote(job['remoteId'], safe='')+'/view'
                else:
                    # Stable unique path makes retries replace the same Synopsis copy.
                    name = item['id']+'-'+(secure_filename(item['fileName']) or path.name)[-140:]
                    remote = GRAPH+'/me/drive/items/'+quote(job['folderId'], safe='')+':/'+quote(name, safe='')+':/content'
                    with path.open('rb') as stream:
                        result = data(http('PUT', remote, headers={**headers, 'Content-Type': mime, 'Content-Length': str(size)}, data=stream))
                    url = result.get('webUrl', '')
                if int(result.get('size', -1)) != size or not result.get('id'): raise CloudError('The cloud upload size could not be verified. Retry the transfer.')
                job.update(status='saved', remoteId=result['id'], url=url, savedAt=now(), error='')
            except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
                job.update(status='error', error=str(exc) if isinstance(exc, CloudError) else 'Cloud transfer failed. Your local document is safe; retry or reconnect in Settings.')
            self.store.update(item_id, {'cloudStorage': job})

    def start(self):
        def run():
            while not self.stop_event.is_set():
                for item in self.store.items():
                    if self.stop_event.is_set(): break
                    if item.get('cloudStorage', {}).get('status') in ('queued', 'uploading'):
                        self.transfer(item['id'])
                self.stop_event.wait(3)
        self.thread = Thread(target=run, name='synopsis-cloud', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()


def register_cloud(app, store):
    cloud = CloudStorage(store)
    app.extensions['cloud'] = cloud
    bp = Blueprint('connectors', __name__, url_prefix='/api/connectors')

    @bp.before_request
    def provider_check():
        if request.view_args and request.view_args.get('provider') not in (None, *PROVIDERS): abort(404)

    @bp.get('')
    def settings():
        return jsonify(cloud.public(request.host_url.rstrip('/')))

    @bp.post('/destination')
    @cloud.synchronized
    def destination():
        with cloud.lock: cloud.destination(request.get_json().get('destination'))
        return jsonify(ok=True)

    @bp.post('/<provider>/configure')
    @cloud.synchronized
    def configure(provider):
        with cloud.lock: cloud.configure(provider, request.get_json())
        return jsonify(ok=True)

    @bp.post('/<provider>/connect')
    @cloud.synchronized
    def connect(provider):
        with cloud.lock:
            if cloud.config(provider).get('refreshToken'): raise ValueError('Disconnect this account before connecting again.')
            url, binding = cloud.begin(provider, request.host_url.rstrip('/'))
        response = jsonify(url=url)
        response.set_cookie('synopsis-oauth-'+provider, binding, max_age=600, httponly=True, samesite='Lax', secure=request.is_secure, path='/api/connectors/'+provider)
        return response

    @bp.get('/<provider>/callback')
    def callback(provider):
        try:
            with cloud.lock: cloud.finish(provider, request.args, request.cookies.get('synopsis-oauth-'+provider, ''))
            result = 'connected'
        except (ValueError, KeyError, TypeError):
            result = 'failed'
        response = redirect('/?connector='+result)
        response.delete_cookie('synopsis-oauth-'+provider, path='/api/connectors/'+provider)
        return response

    @bp.post('/<provider>/disconnect')
    @cloud.synchronized
    def disconnect(provider):
        with cloud.lock: cloud.disconnect(provider)
        return jsonify(ok=True)

    @bp.post('/items/<item_id>/save')
    @cloud.synchronized
    def save(item_id):
        item = store.get(item_id)
        if not item or not item.get('filePath') or item.get('trashed'): raise ValueError('Choose an active document to save to cloud.')
        cloud.enqueue(item_id, explicit=True)
        return jsonify(ok=True), 202

    @bp.post('/items/<item_id>/retry')
    @cloud.synchronized
    def retry(item_id):
        with cloud.lock: cloud.retry(item_id)
        return jsonify(ok=True), 202

    app.register_blueprint(bp)
    if app.config.get('CLOUD_JOBS', app.config['PROCESS_JOBS'] and not app.config.get('TESTING')):
        cloud.start()
    return cloud
