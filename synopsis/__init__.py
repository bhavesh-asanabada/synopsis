"""Synopsis Flask application and JSON API."""
import hashlib
import io
import json
import mimetypes
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

import pytesseract
from flask import Flask, jsonify, render_template, request, send_file, abort
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from ._paths import PACKAGE_DIR, default_data_dir
from .storage import Store, summary
from .processing import Processor, ALLOWED
from .metadata import lookup_doi
from .citations import bibliography, export_references, import_references, STYLES

UNAVAILABLE_FOLDER_PICKER = 'The folder picker is unavailable on this computer. Enter the path manually.'


def pick_folder_natively(prompt='Choose an upload folder'):
    """Open the OS-native folder dialog in a separate process and return the chosen path, or '' if canceled."""
    system = platform.system()
    if system == 'Darwin':
        result = subprocess.run(['osascript', '-e', f'POSIX path of (choose folder with prompt "{prompt}")'],
                                capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return result.stdout.strip()
        if 'User canceled' in result.stderr:
            return ''
        raise ValueError(UNAVAILABLE_FOLDER_PICKER)
    if system == 'Windows':
        script = ("Add-Type -AssemblyName System.Windows.Forms;"
                 "$f=New-Object System.Windows.Forms.FolderBrowserDialog;"
                 "if($f.ShowDialog() -eq 'OK'){Write-Output $f.SelectedPath}")
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                                capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise ValueError(UNAVAILABLE_FOLDER_PICKER)
        return result.stdout.strip()
    # Linux and other platforms: fall back to Tk, if it is installed.
    script = ("import tkinter, tkinter.filedialog as fd\n"
             "root = tkinter.Tk(); root.withdraw(); root.attributes('-topmost', True)\n"
             f"print(fd.askdirectory(title={prompt!r}) or '', end='')")
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise ValueError(UNAVAILABLE_FOLDER_PICKER)
    return result.stdout.strip()

TEXT_FIELDS = {'title', 'year', 'journal', 'doi', 'url', 'abstract', 'type', 'volume', 'issue', 'pages', 'publisher'}
BOOL_FIELDS = {'starred', 'read', 'trashed', 'reviewed'}
LIST_FIELDS = {'authors', 'tags', 'collections'}
TYPES = {'article-journal', 'book', 'chapter', 'paper-conference', 'thesis', 'report', 'webpage', 'document'}


def validate_fields(payload, store):
    if not isinstance(payload, dict):
        raise ValueError('Expected a JSON object.')
    result = {}
    for key, value in payload.items():
        if key in TEXT_FIELDS:
            if not isinstance(value, str) or len(value) > (30000 if key == 'abstract' else 2000):
                raise ValueError(f'{key} must be text of a reasonable length.')
            result[key] = value.strip()
        elif key in BOOL_FIELDS:
            if not isinstance(value, bool):
                raise ValueError(f'{key} must be true or false.')
            result[key] = value
        elif key in LIST_FIELDS:
            if not isinstance(value, list) or len(value) > 200 or any(not isinstance(v, str) or len(v) > 500 for v in value):
                raise ValueError(f'{key} must be a list of text values.')
            result[key] = list(dict.fromkeys(v.strip() for v in value if v.strip()))
    if 'title' in result and not result['title']:
        raise ValueError('A title is required.')
    if 'type' in result and result['type'] not in TYPES:
        raise ValueError('Unsupported reference type.')
    if result.get('url') and urlsplit(result['url']).scheme not in ('http', 'https'):
        raise ValueError('URLs must begin with https:// or http://.')
    if result.get('year') and not re.fullmatch(r'\d{4}', result['year']):
        raise ValueError('Year must have four digits.')
    if 'collections' in result:
        valid = {c['id'] for c in store.collections()}
        if any(c not in valid for c in result['collections']):
            raise ValueError('Collection does not exist.')
    return result


def create_app(config=None):
    app = Flask(__name__, template_folder=str(PACKAGE_DIR / 'templates'), static_folder=str(PACKAGE_DIR / 'static'))
    app.json.sort_keys = False
    app.config.update(DATA_DIR=os.environ.get('SYNOPSIS_DATA_DIR', str(default_data_dir())),
                      MAX_CONTENT_LENGTH=100 * 1024 * 1024, PROCESS_JOBS=True,
                      TEMPLATES_AUTO_RELOAD=True,
                      TRUSTED_HOSTS=['localhost', '127.0.0.1', '[::1]'])
    if config:
        app.config.update(config)
    store = Store(app.config['DATA_DIR'])
    processor = Processor(store)
    app.extensions['store'] = store
    app.extensions['processor'] = processor
    from .research import register_research
    register_research(app, store, processor)

    def queue(item_id):
        if app.config['PROCESS_JOBS']:
            processor.submit(item_id)

    def get_item(item_id):
        item = store.get(item_id)
        if not item:
            abort(404, description='Reference not found.')
        return item

    @app.before_request
    def same_origin():
        if request.path.startswith('/api/') and request.method in ('POST', 'PATCH', 'DELETE', 'PUT'):
            if request.headers.get('X-Synopsis-Request') != '1':
                abort(403, description='Missing application request header.')
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                abort(403, description='Cross-origin writes are not allowed.')
            if request.is_json and not isinstance(request.get_json(), dict):
                raise ValueError('Expected a JSON object.')

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; frame-src 'self'; object-src 'self'; base-uri 'none'; form-action 'self'"
        if request.path == '/' or request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        if isinstance(error, ValueError):
            return jsonify(error=str(error)), 400
        app.logger.exception('Request failed')
        return jsonify(error='This request could not be completed. Please try again.'), 500

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/health')
    def health():
        return jsonify(ok=True, ocrAvailable=bool(shutil.which('tesseract')))

    @app.get('/api/library')
    def library():
        all_items = [i for i in store.items() if not i.get('mergedInto')]
        matches = [i for i in store.items(request.args.get('q', '')) if not i.get('mergedInto')] if request.args.get('q') else all_items
        active = [i for i in all_items if not i['trashed']]
        duplicate_keys = {}
        for item in active:
            key = item['doi'].lower().strip() or re.sub(r'\W+', '', item['title'].casefold())
            duplicate_keys.setdefault(key, []).append(item['id'])
        duplicate_ids = [i for ids in duplicate_keys.values() if len(ids) > 1 for i in ids]
        publication_statuses={s['id']:s for s in store.entities('status')}
        return jsonify(items=[{**summary(i),'publicationStatus':publication_statuses.get(i['id'])} for i in matches], collections=store.collections(),
                       counts=dict(all=len(active), starred=sum(i['starred'] for i in active),
                                   unread=sum(not i['read'] for i in active),
                                   review=sum(not i['reviewed'] for i in active),
                                   trash=sum(i['trashed'] for i in all_items), duplicates=len(duplicate_ids)),
                       duplicateIds=duplicate_ids)

    @app.post('/api/items')
    def create_item():
        fields = validate_fields(request.get_json(), store)
        return jsonify(summary(store.create(fields))), 201

    @app.get('/api/items/<item_id>')
    def detail(item_id):
        return jsonify({**{k: v for k, v in get_item(item_id).items() if k not in ('filePath', 'uploadDirectory')},
                        'publicationStatus':store.entity('status',item_id)})

    @app.patch('/api/items/<item_id>')
    def update_item(item_id):
        get_item(item_id)
        fields = validate_fields(request.get_json(), store)
        def changes(current):
            fields['editedFields'] = list(set(current.get('editedFields', [])) | (set(fields) & TEXT_FIELDS) | (set(fields) & {'authors'}))
            fields['provenance'] = {**current.get('provenance', {}), **{k:{'source':'user-correction','reviewRequired':False,'value':v} for k,v in fields.items() if k in TEXT_FIELDS or k=='authors'}}
            return fields
        return jsonify(summary(store.update(item_id, changes)))

    @app.delete('/api/items/<item_id>')
    def delete_item(item_id):
        item = get_item(item_id)
        if not item['trashed']:
            raise ValueError('Move this reference to Trash before permanently deleting it.')
        if item['status'] in ('queued', 'processing'):
            raise ValueError('Wait for document processing to finish before deleting it.')
        if any(item_id in i.get('attachments',[]) for i in store.items() if i['id'] != item_id):
            raise ValueError('This document is attached to another reference. Keep it to preserve its source links.')
        for kind in ('notebooks','matrices','reviews','versions'):
            if any(item_id in json.dumps(entity) for entity in store.entities(kind)):
                raise ValueError('Research records cite this document. Remove those records before permanently deleting the source.')
        if item['filePath']:
            (store.document_path(item)).unlink(missing_ok=True)
        store.delete(item_id)
        return jsonify(ok=True)

    @app.post('/api/upload')
    def upload():
        files = request.files.getlist('files')
        if not files or len(files) > 20:
            raise ValueError('Choose between 1 and 20 documents.')
        collection = request.form.get('collection', '')
        if collection and collection not in {c['id'] for c in store.collections()}:
            raise ValueError('Collection does not exist.')
        for file in files:
            if Path(file.filename or '').suffix.lower() not in ALLOWED:
                raise ValueError('Supported documents: PDF, PNG, JPG, TIFF, WebP, DOCX, TXT, and Markdown.')
        results = []
        for file in files:
            original = secure_filename(file.filename) or 'document'
            path = store.uploads / (str(uuid4()) + Path(original).suffix.lower())
            file.save(path)
            if path.stat().st_size == 0:
                path.unlink()
                results.append({'fileName': original, 'error': 'This file is empty.'})
                continue
            hasher = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            duplicate = next((i for i in store.items() if i.get('sha256') == digest and not i['trashed']), None)
            if duplicate:
                path.unlink()
                if collection and collection not in duplicate['collections']:
                    duplicate = store.update(duplicate['id'], {'collections': duplicate['collections'] + [collection]})
                results.append({**summary(duplicate), 'duplicate': True})
                continue
            item = store.create(dict(title=Path(file.filename).stem, fileName=file.filename,
                                     filePath=path.name, uploadDirectory=str(path.parent), fileSize=path.stat().st_size, sha256=digest,
                                     collections=[collection] if collection else [], status='queued',
                                     reviewed=False, source='document', progress='Waiting to process…'))
            queue(item['id'])
            results.append(summary(item))
        return jsonify(items=results), 202

    @app.post('/api/items/<item_id>/retry')
    def retry(item_id):
        item = get_item(item_id)
        if not item['filePath']:
            raise ValueError('This reference has no document attachment.')
        if item['status'] in ('queued', 'processing'):
            raise ValueError('This document is already being processed.')
        store.update(item_id, {'status': 'queued', 'progress': 'Waiting to process…'})
        queue(item_id)
        return jsonify(ok=True)

    @app.get('/api/items/<item_id>/file')
    def document_file(item_id):
        item = get_item(item_id)
        if not item['filePath']:
            abort(404, description='No document is attached.')
        suffix = Path(item['filePath']).suffix
        # Only passive, known formats may be viewed inline.
        inline = suffix in {'.pdf', '.png', '.jpg', '.jpeg', '.webp'} and request.args.get('download') != '1'
        mime = mimetypes.guess_type(item['filePath'])[0] or 'application/octet-stream'
        return send_file(store.document_path(item), mimetype=mime,
                         as_attachment=not inline, download_name=item['fileName'], conditional=True)

    @app.post('/api/lookup')
    def lookup():
        payload = request.get_json()
        try:
            return jsonify(lookup_doi(payload.get('doi', '')))
        except ValueError:
            raise
        except Exception:
            return jsonify(error='Metadata lookup is unavailable. Check your connection or add the reference manually.'), 502

    @app.post('/api/items/<item_id>/notes')
    def add_note(item_id):
        item = get_item(item_id)
        text = request.get_json().get('text', '')
        if not isinstance(text, str) or not text.strip() or len(text) > 50000:
            raise ValueError('Enter a note between 1 and 50,000 characters.')
        from .storage import now
        note = dict(id=str(uuid4()), text=text.strip(), createdAt=now())
        store.update(item_id, lambda current: {'notes': current['notes'] + [note]})
        return jsonify(note), 201

    @app.delete('/api/items/<item_id>/notes/<note_id>')
    def delete_note(item_id, note_id):
        item = get_item(item_id)
        store.update(item_id, lambda current: {'notes': [n for n in current['notes'] if n['id'] != note_id]})
        return jsonify(ok=True)

    @app.post('/api/items/<item_id>/annotations')
    def add_annotation(item_id):
        item = get_item(item_id)
        payload = request.get_json()
        text = payload.get('text', '')
        page = payload.get('page', 1)
        if not isinstance(text, str) or not text.strip() or len(text) > 10000:
            raise ValueError('Select or enter a passage to highlight (up to 10,000 characters).')
        if not isinstance(page, int) or page < 1 or page > max(1, item['pageCount']):
            raise ValueError('Enter a valid page number.')
        annotation = dict(id=str(uuid4()), text=text.strip(), page=page)
        store.update(item_id, lambda current: {'annotations': current['annotations'] + [annotation]})
        return jsonify(annotation), 201

    @app.delete('/api/items/<item_id>/annotations/<annotation_id>')
    def delete_annotation(item_id, annotation_id):
        item = get_item(item_id)
        store.update(item_id, lambda current: {'annotations': [a for a in current['annotations'] if a['id'] != annotation_id]})
        return jsonify(ok=True)

    @app.post('/api/collections')
    def add_collection():
        payload = request.get_json()
        name, parent = payload.get('name', ''), payload.get('parent') or None
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError('Collection names must be between 1 and 100 characters.')
        if parent and parent not in {c['id'] for c in store.collections()}:
            raise ValueError('Parent collection does not exist.')
        collection = dict(id=str(uuid4()), name=name.strip(), parent=parent)
        with store.connect() as db:
            db.execute('INSERT INTO collections VALUES (:id, :name, :parent)', collection)
        return jsonify(collection), 201

    @app.patch('/api/collections/<collection_id>')
    def rename_collection(collection_id):
        name = request.get_json().get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError('Enter a collection name (up to 100 characters).')
        with store.connect() as db:
            db.execute('UPDATE collections SET name=? WHERE id=?', (name.strip(), collection_id))
        return jsonify(ok=True)

    @app.delete('/api/collections/<collection_id>')
    def delete_collection(collection_id):
        with store.connect() as db:
            db.execute('UPDATE collections SET parent=NULL WHERE parent=?', (collection_id,))
            db.execute('DELETE FROM collections WHERE id=?', (collection_id,))
        for item in store.items():
            if collection_id in item['collections']:
                store.update(item['id'], {'collections': [c for c in item['collections'] if c != collection_id]})
        return jsonify(ok=True)

    @app.post('/api/import')
    def import_library():
        file = request.files.get('file')
        if not file:
            raise ValueError('Choose a bibliography file.')
        try:
            entries = import_references(file.read().decode('utf-8-sig'), Path(file.filename).suffix.lower())
            validated = [validate_fields(e, store) for e in entries]
        except Exception as exc:
            raise ValueError('Could not import references: ' + str(exc)[:200]) from exc
        created = [summary(store.create({**entry, 'source': 'import'})) for entry in validated]
        return jsonify(items=created), 201

    def selected_items():
        payload = request.get_json()
        ids = payload.get('ids', [])
        if not isinstance(ids, list) or not ids or len(ids) > 5000 or any(not isinstance(i, str) for i in ids):
            raise ValueError('Select between 1 and 5,000 references.')
        return [get_item(i) for i in dict.fromkeys(ids)], payload

    @app.post('/api/bibliography')
    def cite():
        items, payload = selected_items()
        formatted, plain = bibliography(items, payload.get('style', 'apa'))
        return jsonify(text=plain, html=formatted)

    @app.post('/api/export')
    def export():
        items, payload = selected_items()
        text, ext = export_references(items, payload.get('format', 'bibtex'))
        return send_file(io.BytesIO(text.encode('utf-8')), mimetype='text/plain; charset=utf-8',
                         as_attachment=True, download_name=f'synopsis-library.{ext}')

    @app.get('/api/settings')
    def settings():
        try:
            languages = pytesseract.get_languages()
        except Exception:
            languages = []
        return jsonify(metadataLookup=store.setting('metadataLookup', True), ocrLanguage=store.setting('ocrLanguage', 'eng'),
                       languages=languages, ocrAvailable=bool(shutil.which('tesseract')), styles=STYLES,
                       uploadDirectory=str(store.uploads), defaultUploadDirectory=str(store.default_uploads))

    @app.patch('/api/settings')
    def update_settings():
        payload = request.get_json()
        changes = {}
        if 'metadataLookup' in payload:
            if not isinstance(payload['metadataLookup'], bool):
                raise ValueError('Metadata lookup must be true or false.')
            changes['metadataLookup'] = payload['metadataLookup']
        if 'ocrLanguage' in payload:
            try:
                valid = pytesseract.get_languages()
            except Exception:
                valid = []
            if payload['ocrLanguage'] not in valid:
                raise ValueError('This OCR language is not installed.')
            changes['ocrLanguage'] = payload['ocrLanguage']
        if 'uploadDirectory' in payload:
            changes['uploadDirectory'] = store.validate_upload_directory(payload['uploadDirectory'])
        with store.connect() as db:
            for key, value in changes.items():
                db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, json.dumps(value)))
        return jsonify(ok=True)

    @app.post('/api/settings/browse-folder')
    def browse_folder():
        try:
            path = pick_folder_natively()
        except subprocess.TimeoutExpired:
            raise ValueError('The folder picker timed out. Please try again.')
        return jsonify(path=path)

    @app.get('/api/backup')
    def backup():
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            with store.connect() as db:
                entities=[{'kind':r['kind'],'data':json.loads(r['data'])} for r in db.execute('SELECT kind,data FROM entities')]
            items = store.items()
            portable_items = [{k:v for k,v in item.items() if k != 'uploadDirectory'} for item in items]
            archive.writestr('library.json', json.dumps(dict(version=2, items=portable_items, collections=store.collections(), entities=entities,
                              settings={'metadataLookup': store.setting('metadataLookup', True),
                                        'ocrLanguage': store.setting('ocrLanguage', 'eng'), 'ai':store.setting('ai',{}),
                                        'automaticStatusChecks':store.setting('automaticStatusChecks',False)}), indent=2))
            for item in items:
                if item.get('filePath'):
                    archive.write(store.document_path(item), 'uploads/' + item['filePath'])
        buffer.seek(0)
        return send_file(buffer, mimetype='application/zip', as_attachment=True, download_name='synopsis-backup.zip')

    # Jobs persist in SQLite and resume after a clean restart.
    if app.config['PROCESS_JOBS']:
        for item in store.items():
            if item['status'] in ('queued', 'processing'):
                queue(item['id'])
    return app
