import hashlib
import io
import json
import threading
import time
import zipfile
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from synopsis import create_app
from synopsis.cloud import GOOGLE, GRAPH, CloudStorage
from synopsis.services import import_local_file
from manage import restore_backup

HEADERS = {'X-Synopsis-Request': '1'}


class Reply:
    def __init__(self, value=None, status=200, headers=None):
        self.value=value or {};self.status_code=status;self.headers=headers or {}
    def json(self): return self.value


@pytest.fixture
def cloud_app(tmp_path, monkeypatch):
    app=create_app({'TESTING':True,'DATA_DIR':str(tmp_path/'library'),'PROCESS_JOBS':False})
    store=app.extensions['store'];store.set_setting('metadataLookup',False)
    calls=[];remote={};sessions={};counter=[0]
    def provider(method,url,**kwargs):
        calls.append((method,url,kwargs))
        assert kwargs['allow_redirects'] is False
        if url.endswith('/token'):
            return Reply({'access_token':'private-access','refresh_token':'private-refresh-rotated' if kwargs['data']['grant_type']=='refresh_token' else 'private-refresh','expires_in':3600})
        if url==GOOGLE+'/about': return Reply({'user':{'emailAddress':'reader@example.com','permissionId':'account-1'}})
        if url==GRAPH+'/me/drive': return Reply({'id':'drive-1','owner':{'user':{'displayName':'A Reader'}}})
        if method=='POST' and url==GOOGLE+'/files': return Reply({'id':'google-folder','webViewLink':'https://drive.google.com/drive/folders/google-folder'})
        if method=='GET' and '/me/drive/root:/' in url: return Reply(status=404)
        if method=='POST' and url==GRAPH+'/me/drive/root/children': return Reply({'id':'ms-folder','folder':{},'webUrl':'https://onedrive.live.com/folder'})
        if url==GOOGLE+'/files/generateIds':
            counter[0]+=1;return Reply({'ids':['generated-'+str(counter[0])]})
        if url.startswith(GOOGLE+'/files/') and method=='GET':
            return Reply(remote[url.rsplit('/',1)[-1]]) if url.rsplit('/',1)[-1] in remote else Reply(status=404)
        if url=='https://www.googleapis.com/upload/drive/v3/files':
            meta=kwargs['json'];session='https://www.googleapis.com/upload/drive/v3/files?session='+meta['id']
            sessions[session]=meta;return Reply(headers={'Location':session})
        if method=='PUT':
            raw=kwargs['data'].read();assert int(kwargs['headers']['Content-Length'])==len(raw)
            key=sessions[url]['id'] if url in sessions else url
            value={'id':key,'size':len(raw),'md5Checksum':hashlib.md5(raw).hexdigest(),'webUrl':'https://onedrive.live.com/file','webViewLink':'https://drive.google.com/file/d/'+key+'/view'}
            remote[key]=value;return Reply(value,201)
        raise AssertionError((method,url))
    monkeypatch.setattr('synopsis.cloud.requests.request',provider)
    yield app,calls,remote,provider
    app.extensions['cloud'].close();app.extensions['watcher'].close();app.extensions['processor'].pool.shutdown(wait=True)


def configure(client,provider):
    response=client.post(f'/api/connectors/{provider}/configure',json={'clientId':'client-123','clientSecret':'private-secret','tenant':'common','folderName':'Synopsis research'},headers=HEADERS)
    assert response.status_code==200,response.json


def connect(client,provider):
    configure(client,provider)
    response=client.post(f'/api/connectors/{provider}/connect',headers=HEADERS)
    assert response.status_code==200,response.json
    query=parse_qs(urlsplit(response.json['url']).query)
    result=client.get(f'/api/connectors/{provider}/callback',query_string={'code':'valid-code','state':query['state'][0]})
    assert result.location=='/?connector=connected'
    return query


def upload(client,content=b'A private research document',name='study.txt'):
    response=client.post('/api/upload',data={'files':(io.BytesIO(content),name)},headers=HEADERS)
    assert response.status_code==202,response.json
    return response.json['items'][0]


@pytest.mark.parametrize('provider',['google','onedrive'])
def test_oauth_upload_refresh_and_backup(cloud_app,provider,tmp_path):
    app,calls,remote,_=cloud_app;client=app.test_client();cloud=app.extensions['cloud'];store=app.extensions['store']
    query=connect(client,provider)
    assert query['code_challenge_method']==['S256'] and len(query['code_challenge'][0])==43
    token_request=next(k['data'] for m,u,k in calls if u.endswith('/token'))
    assert len(token_request['code_verifier'])>=43
    assert token_request['redirect_uri']==f'http://localhost/api/connectors/{provider}/callback'
    result=client.post('/api/connectors/destination',json={'destination':provider},headers=HEADERS)
    assert result.status_code==200
    item=upload(client);assert item['cloudStorage']['status']=='queued'
    c=cloud.config(provider);c['expiresAt']=0;cloud.save(provider,c)
    cloud.transfer(item['id']);saved=store.get(item['id'])
    assert saved['cloudStorage']['status']=='saved',saved['cloudStorage']
    assert store.document_path(saved).read_bytes()==b'A private research document'
    assert any(k.get('data',{}).get('grant_type')=='refresh_token' for m,u,k in calls if u.endswith('/token'))
    assert cloud.config(provider)['refreshToken']=='private-refresh-rotated'
    before=len(remote);cloud.transfer(item['id']);assert len(remote)==before
    duplicate=upload(client);assert duplicate['duplicate'] and duplicate['id']==item['id']
    assert client.get('/api/items/'+item['id']+'/file').status_code==200
    public=client.get('/api/connectors').json
    assert public['providers'][provider]['connected'] is True
    assert 'private-' not in json.dumps(public)
    assert 'private-' not in client.get('/api/settings').text
    raw=client.get('/api/backup').data
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        payload=archive.read('library.json');assert b'private-' not in payload
    backup=tmp_path/'backup.zip';backup.write_bytes(raw)
    restore_backup(backup,tmp_path/'restored')
    from synopsis.storage import Store
    restored=Store(tmp_path/'restored');assert restored.setting('cloudDestination','local')=='local'
    assert restored.setting('cloud:'+provider) is None
    assert restored.document_path(restored.get(item['id'])).exists()


def test_oauth_state_browser_binding_replay_and_denial(cloud_app):
    app,calls,_,_=cloud_app;client=app.test_client();cloud=app.extensions['cloud']
    configure(client,'google')
    url=client.post('/api/connectors/google/connect',headers=HEADERS).json['url']
    state=parse_qs(urlsplit(url).query)['state'][0]
    count=len(calls)
    assert app.test_client().get('/api/connectors/google/callback',query_string={'state':state,'code':'stolen'}).location=='/?connector=failed'
    assert len(calls)==count
    result=client.get('/api/connectors/google/callback',query_string={'state':state,'code':'code'})
    assert result.location=='/?connector=connected'
    count=len(calls)
    assert client.get('/api/connectors/google/callback',query_string={'state':state,'code':'code'}).location=='/?connector=failed'
    assert len(calls)==count
    client.post('/api/connectors/google/disconnect',headers=HEADERS)
    url=client.post('/api/connectors/google/connect',headers=HEADERS).json['url'];state=parse_qs(urlsplit(url).query)['state'][0]
    assert client.get('/api/connectors/google/callback',query_string={'state':state,'error':'access_denied'}).location=='/?connector=failed'
    assert not cloud.config('google').get('accessToken')
    url=client.post('/api/connectors/google/connect',headers=HEADERS).json['url'];state=parse_qs(urlsplit(url).query)['state'][0]
    cloud.pending['google']['expires']=0
    assert client.get('/api/connectors/google/callback',query_string={'state':state,'code':'code'}).location=='/?connector=failed'


@pytest.mark.parametrize('provider',['google','onedrive'])
def test_ambiguous_upload_retry_does_not_duplicate(cloud_app,monkeypatch,provider):
    app,calls,remote,handler=cloud_app;client=app.test_client();cloud=app.extensions['cloud'];store=app.extensions['store']
    connect(client,provider);client.post('/api/connectors/destination',json={'destination':provider},headers=HEADERS)
    item=upload(client)
    def flaky(method,url,**kwargs):
        response=handler(method,url,**kwargs)
        if method=='PUT': raise requests.Timeout('response lost after upload')
        return response
    monkeypatch.setattr('synopsis.cloud.requests.request',flaky)
    cloud.transfer(item['id']);assert store.get(item['id'])['cloudStorage']['status']=='error'
    assert len(remote)==1
    monkeypatch.setattr('synopsis.cloud.requests.request',handler)
    assert client.post('/api/connectors/items/'+item['id']+'/retry',headers=HEADERS).status_code==202
    CloudStorage(store).transfer(item['id'])
    assert store.get(item['id'])['cloudStorage']['status']=='saved'
    assert len(remote)==1
    assert len([u for m,u,k in calls if u.endswith('generateIds')])==(1 if provider=='google' else 0)


def test_cloud_failure_independent_of_ocr_disconnect_and_account_switch(cloud_app,monkeypatch):
    app,calls,remote,handler=cloud_app;client=app.test_client();cloud=app.extensions['cloud'];store=app.extensions['store']
    connect(client,'google');client.post('/api/connectors/destination',json={'destination':'google'},headers=HEADERS)
    item=upload(client)
    monkeypatch.setattr('synopsis.cloud.requests.request',lambda *a,**k:Reply(status=403))
    cloud.transfer(item['id']);assert store.get(item['id'])['cloudStorage']['status']=='error'
    app.extensions['processor'].process(item['id'])
    assert store.get(item['id'])['status']=='ready'
    assert store.get(item['id'])['text']=='A private research document'
    client.post('/api/connectors/google/disconnect',headers=HEADERS)
    assert client.get('/api/connectors').json['destination']=='local'
    assert not cloud.config('google').get('refreshToken')
    assert client.post('/api/connectors/items/'+item['id']+'/retry',headers=HEADERS).status_code==400
    monkeypatch.setattr('synopsis.cloud.requests.request',handler)
    connect(client,'google');client.post('/api/connectors/destination',json={'destination':'google'},headers=HEADERS)
    assert client.post('/api/connectors/items/'+item['id']+'/retry',headers=HEADERS).status_code==400
    assert client.post('/api/connectors/items/'+item['id']+'/save',headers=HEADERS).status_code==202
    cloud.transfer(item['id']);assert store.get(item['id'])['cloudStorage']['status']=='saved'
    client.patch('/api/items/'+item['id'],json={'trashed':True},headers=HEADERS)
    assert client.delete('/api/items/'+item['id'],headers=HEADERS).status_code==200
    assert len(remote)==1  # Local deletion never deletes someone else's cloud file.


def test_interrupted_jobs_and_watchers_and_restore_pauses(cloud_app,tmp_path):
    app,_,_,_=cloud_app;client=app.test_client();cloud=app.extensions['cloud'];store=app.extensions['store']
    connect(client,'onedrive');cloud.destination('onedrive')
    path=tmp_path/'watched.txt';path.write_text('Watched research')
    item_id=import_local_file(store,app.extensions['processor'],path)['id']
    assert store.get(item_id)['cloudStorage']['status']=='queued'
    job=store.get(item_id)['cloudStorage'];store.update(item_id,{'cloudStorage':{**job,'status':'uploading'}})
    # Restarted worker resumes a persisted in-flight upload using the same target.
    restarted=CloudStorage(store);restarted.start()
    deadline=time.time()+5
    while store.get(item_id)['cloudStorage']['status']!='saved' and time.time()<deadline: time.sleep(.02)
    restarted.close();restarted.thread.join(2)
    assert store.get(item_id)['cloudStorage']['status']=='saved'
    store.update(item_id,{'cloudStorage':{**job,'status':'queued'}})
    backup=tmp_path/'backup.zip';backup.write_bytes(client.get('/api/backup').data)
    restore_backup(backup,tmp_path/'restored')
    from synopsis.storage import Store
    assert Store(tmp_path/'restored').get(item_id)['cloudStorage']['status']=='paused'


def test_validation_origin_and_upload_url_guard(cloud_app,monkeypatch):
    app,_,_,handler=cloud_app;client=app.test_client();cloud=app.extensions['cloud'];store=app.extensions['store']
    assert client.post('/api/connectors/destination',json={'destination':'google'}).status_code==403
    assert client.post('/api/connectors/destination',json={'destination':'google'},headers={**HEADERS,'Origin':'https://evil.test'}).status_code==403
    assert client.post('/api/connectors/destination',json={'destination':'google'},headers=HEADERS).status_code==400
    assert client.post('/api/connectors/unknown/connect',headers=HEADERS).status_code==404
    assert client.post('/api/connectors/google/configure',json={'clientId':'id','clientSecret':'secret','folderName':'../escape'},headers=HEADERS).status_code==400
    assert client.post('/api/connectors/onedrive/configure',json={'clientId':'id','clientSecret':'secret','tenant':'evil/a'},headers=HEADERS).status_code==400
    connect(client,'google');cloud.destination('google');item=upload(client)
    def malicious(method,url,**kwargs):
        if url=='https://www.googleapis.com/upload/drive/v3/files': return Reply(headers={'Location':'https://evil.test/steal-token'})
        assert 'evil.test' not in url
        return handler(method,url,**kwargs)
    monkeypatch.setattr('synopsis.cloud.requests.request',malicious)
    cloud.transfer(item['id']);assert store.get(item['id'])['cloudStorage']['status']=='error'
    assert 'Invalid Google' in store.get(item['id'])['cloudStorage']['error']


def test_transfer_locks_prevent_delete_or_disconnect_but_not_local_upload(cloud_app,monkeypatch):
    app,_,_,handler=cloud_app;client=app.test_client();cloud=app.extensions['cloud'];store=app.extensions['store']
    connect(client,'onedrive');cloud.destination('onedrive');item=upload(client)
    started=threading.Event();release=threading.Event()
    def blocked(method,url,**kwargs):
        if method=='PUT': started.set();assert release.wait(5)
        return handler(method,url,**kwargs)
    monkeypatch.setattr('synopsis.cloud.requests.request',blocked)
    worker=threading.Thread(target=cloud.transfer,args=(item['id'],));worker.start();assert started.wait(5)
    try:
        assert client.post('/api/connectors/onedrive/disconnect',headers=HEADERS).status_code==409
        assert client.delete('/api/items/'+item['id'],headers=HEADERS).status_code==409
        other=upload(client,b'Another local file');assert other['cloudStorage']['status']=='queued'
    finally: release.set();worker.join(5)
    assert store.get(item['id'])['cloudStorage']['status']=='saved'


@pytest.mark.parametrize('provider',['google','onedrive'])
def test_unverified_remote_copy_is_not_marked_saved(cloud_app,monkeypatch,provider):
    app,_,_,handler=cloud_app;client=app.test_client();cloud=app.extensions['cloud'];store=app.extensions['store']
    connect(client,provider);cloud.destination(provider);item=upload(client)
    def corrupt(method,url,**kwargs):
        reply=handler(method,url,**kwargs)
        if method=='PUT':
            if provider=='google': reply.value['md5Checksum']='wrong-checksum'
            else: reply.value['size']=0
        return reply
    monkeypatch.setattr('synopsis.cloud.requests.request',corrupt)
    cloud.transfer(item['id'])
    saved=store.get(item['id'])
    assert saved['cloudStorage']['status']=='error'
    assert store.document_path(saved).read_bytes()==b'A private research document'
