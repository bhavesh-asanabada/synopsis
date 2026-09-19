import io
import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from docx import Document
from jinja2 import FileSystemLoader

from synopsis import create_app
from synopsis.metadata import infer_metadata

HEADERS = {'X-Synopsis-Request': '1'}


@pytest.fixture
def app(tmp_path):
    app = create_app({'TESTING': True, 'DATA_DIR': str(tmp_path), 'PROCESS_JOBS': False})
    app.extensions['store'].set_setting('metadataLookup', False)
    yield app
    app.extensions['processor'].pool.shutdown(wait=True)


@pytest.fixture
def client(app):
    return app.test_client()


def create(client, **fields):
    result = client.post('/api/items', json={'title': 'A thoughtful reference', **fields}, headers=HEADERS)
    assert result.status_code == 201, result.json
    return result.json


def upload(client, content, filename):
    result = client.post('/api/upload', data={'files': (io.BytesIO(content), filename)}, headers=HEADERS)
    assert result.status_code == 202, result.json
    return result.json['items'][0]


def test_homepage_reloads_updated_template_without_server_restart(app, client, tmp_path):
    template_dir = tmp_path / 'templates'
    template_dir.mkdir()
    template = template_dir / 'index.html'
    template.write_text('<main>Original library</main>')
    app.jinja_loader = FileSystemLoader(template_dir)
    response = client.get('/')
    assert response.status_code == 200
    assert b'Original library' in response.data
    assert response.headers['Cache-Control'] == 'no-store'
    previous_mtime = template.stat().st_mtime_ns
    template.write_text('<main>Library with table controls</main>')
    os.utime(template, ns=(previous_mtime + 1_000_000_000,) * 2)
    updated = client.get('/')
    assert updated.status_code == 200
    assert b'Library with table controls' in updated.data
    assert b'Original library' not in updated.data


def test_persistence_search_notes_and_collections(app, client):
    collection = client.post('/api/collections', json={'name': 'Climate research'}, headers=HEADERS).json
    item = create(client, authors=['Curie, Marie'], year='2024', tags=['energy'], collections=[collection['id']])
    result = client.post(f"/api/items/{item['id']}/notes", json={'text': 'An unexpected connection to quantum materials.'}, headers=HEADERS)
    assert result.status_code == 201
    assert client.get('/api/library?q=quantum').json['items'][0]['id'] == item['id']
    assert client.get('/api/library?q=missing').json['items'] == []
    recreated = create_app({'TESTING': True, 'DATA_DIR': app.config['DATA_DIR'], 'PROCESS_JOBS': False})
    assert recreated.test_client().get(f"/api/items/{item['id']}").json['notes'][0]['text'].startswith('An unexpected')
    recreated.extensions['processor'].pool.shutdown()
    assert client.delete('/api/collections/'+collection['id'], headers=HEADERS).status_code == 200
    assert client.get(f"/api/items/{item['id']}").json['collections'] == []


def test_text_processing_metadata_and_duplicate_file(app, client):
    content = b'Rethinking Research Libraries\nAuthor: Lovelace, Ada\nYear: 2024\n\nAbstract\nA searchable library connects ideas.\n\nKeywords\nresearch'
    item = upload(client, content, 'paper.txt')
    app.extensions['processor'].process(item['id'])
    result = client.get('/api/items/'+item['id']).json
    assert result['status'] == 'ready'
    assert result['title'] == 'Rethinking Research Libraries'
    assert result['authors'] == ['Lovelace, Ada']
    assert result['year'] == '2024'
    assert 'connects ideas' in result['abstract']
    assert result['reviewed'] is False
    assert len(client.get('/api/library?q=searchable').json['items']) == 1
    duplicate = upload(client, content, 'renamed.txt')
    assert duplicate['duplicate'] is True and duplicate['id'] == item['id']
    assert client.get('/api/items/'+item['id']+'/file?download=1').data == content


def test_user_edits_survive_processing(app, client):
    item = upload(client, b'A long automatically extracted title\nAuthor: Someone\n', 'paper.txt')
    client.patch('/api/items/'+item['id'], json={'title': 'My corrected title', 'authors': ['Curie, Marie']}, headers=HEADERS)
    app.extensions['processor'].process(item['id'])
    result = client.get('/api/items/'+item['id']).json
    assert result['title'] == 'My corrected title'
    assert result['authors'] == ['Curie, Marie']


def test_invalid_files_do_not_lose_original(app, client):
    item = upload(client, b'not a PDF', 'broken.pdf')
    app.extensions['processor'].process(item['id'])
    assert client.get('/api/items/'+item['id']).json['status'] == 'error'
    assert client.get('/api/items/'+item['id']+'/file?download=1').data == b'not a PDF'
    result = client.post('/api/upload', data={'files': (io.BytesIO(b'<script/>'), 'bad.html')}, headers=HEADERS)
    assert result.status_code == 400
    assert client.post('/api/upload', data={'files': (io.BytesIO(b''), 'empty.txt')}, headers=HEADERS).json['items'][0]['error']


def test_docx_embedded_metadata(app, client):
    doc = Document()
    doc.core_properties.title = 'A Durable Research Library'
    doc.core_properties.author = 'Ada Lovelace'
    doc.add_paragraph('Important searchable scientific observations.')
    buffer = io.BytesIO()
    doc.save(buffer)
    item = upload(client, buffer.getvalue(), 'research.docx')
    app.extensions['processor'].process(item['id'])
    result = client.get('/api/items/'+item['id']).json
    assert result['title'] == 'A Durable Research Library'
    assert result['authors'] == ['Ada Lovelace']
    assert 'scientific observations' in result['text']


def make_scan():
    image = Image.new('RGB', (1800, 900), 'white')
    draw = ImageDraw.Draw(image)
    fonts = ['/System/Library/Fonts/Supplemental/Arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    font_path = next((p for p in fonts if Path(p).exists()), None)
    font = ImageFont.truetype(font_path, 52) if font_path else ImageFont.load_default(size=52)
    draw.multiline_text((100, 100), 'Research Libraries Connect Ideas\nAuthor: Ada Lovelace\nYear: 2024\n\nAbstract\nScientific documents become searchable.', font=font, fill='black', spacing=30)
    return image


@pytest.mark.skipif(not shutil.which('tesseract'), reason='Tesseract is required for OCR integration')
@pytest.mark.parametrize('suffix', ['png', 'pdf'])
def test_real_image_and_scanned_pdf_ocr(app, client, suffix):
    image = make_scan()
    buffer = io.BytesIO()
    image.save(buffer, format=suffix.upper())
    item = upload(client, buffer.getvalue(), 'scanned.'+suffix)
    app.extensions['processor'].process(item['id'])
    result = client.get('/api/items/'+item['id']).json
    assert result['status'] == 'ready', result['progress']
    assert 'Research Libraries Connect Ideas' in result['text']
    assert 'Scientific documents become searchable' in result['text']
    assert result['ocrUsed'] is True
    assert result['pageCount'] == 1
    assert result['year'] == '2024'


def test_password_pdf_reports_error(app, client):
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.encrypt('secret')
    buffer = io.BytesIO()
    writer.write(buffer)
    item = upload(client, buffer.getvalue(), 'locked.pdf')
    app.extensions['processor'].process(item['id'])
    result = client.get('/api/items/'+item['id']).json
    assert result['status'] == 'error'
    assert 'password-protected' in result['progress']


@pytest.mark.parametrize('format_name,suffix', [('bibtex', '.bib'), ('ris', '.ris'), ('csl', '.json')])
def test_bibliography_roundtrip(client, format_name, suffix):
    item = create(client, title='The Research Library', authors=['Lovelace, Ada'], year='2024',
                  journal='Journal of Discovery', doi='10.1234/discovery', volume='7', issue='2', pages='12-19', url='https://example.org/paper')
    result = client.post('/api/export', json={'ids': [item['id']], 'format': format_name}, headers=HEADERS)
    assert result.status_code == 200
    imported = client.post('/api/import', data={'file': (io.BytesIO(result.data), 'references'+suffix)}, headers=HEADERS)
    assert imported.status_code == 201, imported.json
    copy = imported.json['items'][0]
    for field in ['title', 'year', 'authors', 'doi', 'volume', 'issue', 'pages', 'url']:
        assert copy[field] == item[field], field


@pytest.mark.parametrize('style', ['apa', 'modern-language-association', 'chicago-author-date', 'vancouver'])
def test_real_csl_bibliography(client, style):
    item = create(client, title='The Research Library', authors=['Lovelace, Ada'], year='2024')
    result = client.post('/api/bibliography', json={'ids': [item['id']], 'style': style}, headers=HEADERS)
    assert result.status_code == 200, result.json
    assert 'Lovelace' in result.json['text']
    assert '2024' in result.json['text']
    assert 'Research Library' in result.json['text']


def test_bibliography_html_preserves_italics_and_escapes_titles(client):
    item = create(client, title='A <script>alert(1)</script> & Study', authors=['Lovelace, Ada'], year='2024',
                  journal='Journal & Examples')
    result = client.post('/api/bibliography', json={'ids': [item['id']], 'style': 'apa'}, headers=HEADERS)
    assert result.status_code == 200, result.json
    assert '<i>Journal &amp; Examples</i>' in result.json['html']
    assert '<script>' not in result.json['html'] and '&lt;script&gt;' in result.json['html']
    assert 'A <script>alert(1)</script> & Study' in result.json['text']
    assert 'Journal & Examples' in result.json['text']


def test_bibliography_html_applies_hanging_indent_and_line_spacing(client):
    one = create(client, title='First reference', authors=['Ada, Lovelace'], year='2020', journal='A Journal')
    two = create(client, title='Second reference', authors=['Grace, Hopper'], year='2021', journal='A Journal')
    result = client.post('/api/bibliography', json={'ids': [one['id'], two['id']], 'style': 'apa'}, headers=HEADERS)
    assert result.status_code == 200, result.json
    # APA is double-spaced with a hanging indent; each entry must be its own block so the styles
    # actually take effect (plain '\n\n' between entries collapses to nothing in rendered HTML).
    assert result.json['html'].count('text-indent:-2em') == 2
    assert 'line-height:2' in result.json['html']
    assert result.json['html'].count('<div') >= 3


def test_bibliography_omits_blank_fields_and_spaces_vancouver_numbering(client):
    book = create(client, title='The Structure of Scientific Revolutions', authors=['Kuhn, Thomas S.'],
                  year='1962', type='book', publisher='University of Chicago Press')
    article = create(client, title='Deep learning in medical imaging', authors=['Smith, John'],
                     year='2021', journal='Journal of Medical AI', volume='15', issue='2', pages='101-120')

    apa = client.post('/api/bibliography', json={'ids': [book['id']], 'style': 'apa'}, headers=HEADERS)
    # A plain book has no container-title, so citeproc must not emit a dangling "In" before the publisher.
    assert 'In ' not in apa.json['text']
    assert 'In.' not in apa.json['text']

    vancouver = client.post('/api/bibliography', json={'ids': [book['id'], article['id']], 'style': 'vancouver'},
                            headers=HEADERS)
    # citeproc-py doesn't render second-field-align hanging indents, so numbers must get an explicit space.
    assert '1.Kuhn' not in vancouver.json['text'] and '2.Smith' not in vancouver.json['text']
    assert '1. Kuhn' in vancouver.json['text']
    assert '2. Smith' in vancouver.json['text']


def test_trash_restore_permanent_delete_and_backup(app, client):
    item = upload(client, b'Research documents are valuable', 'paper.txt')
    app.extensions['processor'].process(item['id'])
    assert client.delete('/api/items/'+item['id'], headers=HEADERS).status_code == 400
    backup = client.get('/api/backup')
    with zipfile.ZipFile(io.BytesIO(backup.data)) as archive:
        data = json.loads(archive.read('library.json'))
        assert data['items'][0]['id'] == item['id']
        assert any(p.startswith('uploads/') for p in archive.namelist())
    assert client.patch('/api/items/'+item['id'], json={'trashed': True}, headers=HEADERS).status_code == 200
    assert client.get('/api/library').json['counts']['trash'] == 1
    client.patch('/api/items/'+item['id'], json={'trashed': False}, headers=HEADERS)
    assert client.get('/api/library').json['counts']['all'] == 1
    client.patch('/api/items/'+item['id'], json={'trashed': True}, headers=HEADERS)
    assert client.delete('/api/items/'+item['id'], headers=HEADERS).status_code == 200
    assert client.get('/api/items/'+item['id']).status_code == 404
    assert list(app.extensions['store'].uploads.iterdir()) == []


def test_request_safety_and_validation(client):
    assert client.post('/api/items', json={'title': 'Forbidden'}).status_code == 403
    assert client.post('/api/items', json={'title': 'Forbidden'}, headers={**HEADERS, 'Origin': 'https://evil.example'}).status_code == 403
    for fields in [{'title':''}, {'authors':'Ada'}, {'url':'javascript:alert(1)'}, {'year':'yesterday'}, {'collections':['missing']}]:
        assert client.post('/api/items', json=fields, headers=HEADERS).status_code == 400
    assert client.get('/api/items/../../etc/passwd/file').status_code == 404
    item = create(client)
    assert client.patch('/api/items/'+item['id'], json={'filePath':'/etc/passwd'}, headers=HEADERS).status_code == 200
    assert not app_has_path(client.get('/api/items/'+item['id']).json)


def app_has_path(item):
    return 'filePath' in item


def test_upload_folder_preserves_documents_and_portable_backup(app, client, tmp_path):
    from manage import restore_backup
    from synopsis.storage import Store
    store = app.extensions['store']
    original = upload(client, b'Original research document in the default folder', 'original.txt')
    # Emulate a document created before folder preferences were introduced.
    store.update(original['id'], {'uploadDirectory': ''})
    destination = tmp_path / 'My papers' / 'Uploaded documents'
    result = client.patch('/api/settings', json={'uploadDirectory': str(destination)}, headers=HEADERS)
    assert result.status_code == 200, result.json
    assert destination.is_dir()
    second = upload(client, b'New research document saved in the custom folder', 'new.txt')
    assert store.document_path(store.get(second['id'])).parent == destination
    assert Store(store.root).uploads == destination
    # Jobs queued before and after the switch must read their own original paths.
    for reference in (original, second):
        app.extensions['processor'].process(reference['id'])
        assert store.get(reference['id'])['status'] == 'ready'
        assert client.get(f"/api/items/{reference['id']}/file").status_code == 200
        assert 'uploadDirectory' not in client.get(f"/api/items/{reference['id']}").json
    assert client.patch('/api/settings', json={'uploadDirectory': ''}, headers=HEADERS).status_code == 200
    assert store.uploads == store.default_uploads
    duplicate = upload(client, b'New research document saved in the custom folder', 'duplicate.txt')
    assert duplicate['duplicate'] and duplicate['id'] == second['id']
    unrelated = destination / 'unrelated.txt'
    unrelated.write_text('This is not a library document.')
    backup = client.get('/api/backup')
    assert backup.status_code == 200
    with zipfile.ZipFile(io.BytesIO(backup.data)) as archive:
        payload = json.loads(archive.read('library.json'))
        assert all('uploadDirectory' not in item for item in payload['items'])
        assert len([name for name in archive.namelist() if name.startswith('uploads/')]) == 2
        assert 'uploads/unrelated.txt' not in archive.namelist()
    archive_path = tmp_path / 'multiple-folders.zip'
    archive_path.write_bytes(backup.data)
    restored_root = tmp_path / 'restored-multiple-folders'
    assert restore_backup(archive_path, restored_root) == 2
    restored = Store(restored_root)
    for item in restored.items():
        assert restored.document_path(item).parent == restored_root / 'uploads'
        assert restored.document_path(item).read_bytes() == store.document_path(store.get(item['id'])).read_bytes()
    custom_file = store.document_path(store.get(second['id']))
    client.patch(f"/api/items/{second['id']}", json={'trashed': True}, headers=HEADERS)
    assert client.delete(f"/api/items/{second['id']}", headers=HEADERS).status_code == 200
    assert not custom_file.exists() and unrelated.exists()
    assert store.document_path(store.get(original['id'])).exists()


def test_invalid_upload_folder_does_not_change_settings(app, client, tmp_path, monkeypatch):
    store = app.extensions['store']
    occupied = tmp_path / 'existing-file'
    occupied.write_text('Keep this file')
    for path in [None, 123, 'relative/folder', 'bad\0path', str(occupied), str(occupied / 'child')]:
        response = client.patch('/api/settings', json={'uploadDirectory': path, 'metadataLookup': True}, headers=HEADERS)
        assert response.status_code == 400, response.json
        assert store.uploads == store.default_uploads
        assert store.setting('metadataLookup') is False
    assert occupied.read_text() == 'Keep this file'
    def deny_write(*args, **kwargs):
        raise PermissionError('Folder is read-only')
    monkeypatch.setattr('synopsis.storage.tempfile.TemporaryFile', deny_write)
    assert client.patch('/api/settings', json={'uploadDirectory': str(tmp_path / 'read-only')}, headers=HEADERS).status_code == 400
    assert store.uploads == store.default_uploads


def test_browse_folder_returns_selected_path(client, tmp_path, monkeypatch):
    import subprocess
    chosen = tmp_path / 'Chosen documents'
    monkeypatch.setattr('synopsis.subprocess.run', lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=str(chosen), stderr=''))
    response = client.post('/api/settings/browse-folder', headers=HEADERS)
    assert response.status_code == 200
    assert response.json['path'] == str(chosen)


def test_browse_folder_handles_cancel_and_failure(client, monkeypatch):
    import subprocess
    monkeypatch.setattr('synopsis.subprocess.run', lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout='', stderr=''))
    response = client.post('/api/settings/browse-folder', headers=HEADERS)
    assert response.status_code == 200
    assert response.json['path'] == ''

    def missing_tkinter(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout='', stderr='ModuleNotFoundError')
    monkeypatch.setattr('synopsis.subprocess.run', missing_tkinter)
    response = client.post('/api/settings/browse-folder', headers=HEADERS)
    assert response.status_code == 400
    assert 'unavailable' in response.json['error']

    def hangs(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=300)
    monkeypatch.setattr('synopsis.subprocess.run', hangs)
    response = client.post('/api/settings/browse-folder', headers=HEADERS)
    assert response.status_code == 400
    assert 'timed out' in response.json['error']


def test_upload_folder_expands_home_and_rejects_watcher_overlap(app, client, tmp_path, monkeypatch):
    # expanduser uses the operating system's home resolver; provide an isolated expansion.
    expanduser = Path.expanduser
    monkeypatch.setattr(Path, 'expanduser', lambda path: tmp_path / str(path)[2:] if str(path).startswith('~/') else expanduser(path))
    response = client.patch('/api/settings', json={'uploadDirectory': '~/Research documents'}, headers=HEADERS)
    assert response.status_code == 200
    assert client.get('/api/settings').json['uploadDirectory'] == str(tmp_path / 'Research documents')
    intake = tmp_path / 'intake'
    intake.mkdir()
    app.extensions['store'].put_entity('watchers', {'path': str(intake), 'enabled': False})
    assert client.patch('/api/settings', json={'uploadDirectory': str(intake)}, headers=HEADERS).status_code == 400


def test_annotations_and_duplicates(client):
    first = create(client, doi='10.1234/test')
    second = create(client, title='Alternate title', doi='10.1234/test')
    assert client.get('/api/library').json['counts']['duplicates'] == 2
    result = client.post('/api/items/'+first['id']+'/annotations', json={'text':'A meaningful passage', 'page':1}, headers=HEADERS)
    assert result.status_code == 201
    assert client.get('/api/library?q=meaningful').json['items'][0]['id'] == first['id']
    client.delete(f"/api/items/{first['id']}/annotations/{result.json['id']}", headers=HEADERS)
    assert client.get('/api/items/'+first['id']).json['annotations'] == []


def test_doi_enrichment_with_service_response(app, client, monkeypatch):
    monkeypatch.setattr('synopsis.processing.lookup_doi', lambda doi: dict(title='Verified bibliographic title', authors=['Curie, Marie'], year='2023', doi=doi))
    app.extensions['store'].set_setting('metadataLookup', True)
    item = upload(client, b'Some extracted research document title\nDOI: 10.1234/test.\n', 'paper.txt')
    app.extensions['processor'].process(item['id'])
    result = client.get('/api/items/'+item['id']).json
    assert result['source'] == 'crossref'
    assert result['title'] == 'Verified bibliographic title'
    assert result['doi'] == '10.1234/test'


def test_backup_restore_is_lossless_and_never_overwrites(app, client, tmp_path):
    from manage import restore_backup
    collection = client.post('/api/collections', json={'name': 'Recovered research'}, headers=HEADERS).json
    item = upload(client, b'Restore this scientific reference\nAuthor: Ada Lovelace', 'original.txt')
    app.extensions['processor'].process(item['id'])
    client.patch('/api/items/'+item['id'], json={'collections':[collection['id']], 'tags':['important']}, headers=HEADERS)
    client.post('/api/items/'+item['id']+'/notes', json={'text':'A persistent observation'}, headers=HEADERS)
    backup = tmp_path / 'backup.zip'
    backup.write_bytes(client.get('/api/backup').data)
    destination = tmp_path / 'recovered'
    assert restore_backup(backup, destination) == 1
    recovered = create_app({'DATA_DIR': str(destination), 'PROCESS_JOBS': False, 'TESTING': True})
    result = recovered.test_client().get('/api/items/'+item['id']).json
    assert result['notes'][0]['text'] == 'A persistent observation'
    assert result['tags'] == ['important']
    assert result['collections'] == [collection['id']]
    assert recovered.test_client().get('/api/items/'+item['id']+'/file?download=1').data.startswith(b'Restore this')
    assert recovered.extensions['store'].setting('metadataLookup') is False
    with pytest.raises(ValueError, match='never overwritten'):
        restore_backup(backup, destination)
    recovered.extensions['processor'].pool.shutdown()


def test_metadata_lookup_normalizes_crossref_types(monkeypatch):
    from synopsis.metadata import lookup_doi
    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {'message': {'title':['Deep learning'], 'type':'journal-article', 'author':[{'family':'LeCun','given':'Yann'}],
                                'published':{'date-parts':[[2015,5,28]]}, 'container-title':['Nature'], 'DOI':'10.1038/nature14539'}}
    monkeypatch.setattr('synopsis.metadata.requests.get', lambda *args, **kwargs: Response())
    result = lookup_doi('https://doi.org/10.1038/nature14539')
    assert result['type'] == 'article-journal'
    assert result['authors'] == ['LeCun, Yann']
    assert result['year'] == '2015'


def test_mixed_pdf_preserves_text_and_ocrs_scanned_pages(app, client):
    if not shutil.which('tesseract'):
        pytest.skip('Tesseract is required')
    from pypdf import PdfReader
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 16 Tf 50 700 Td (Digital research page with enough readable text for extraction.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    scanned = io.BytesIO()
    make_scan().save(scanned, format='PDF')
    scanned.seek(0)
    writer.add_page(PdfReader(scanned).pages[0])
    buffer = io.BytesIO()
    writer.write(buffer)
    item = upload(client, buffer.getvalue(), 'mixed.pdf')
    app.extensions['processor'].process(item['id'])
    result = client.get('/api/items/'+item['id']).json
    assert result['status'] == 'ready', result['progress']
    assert result['pageCount'] == 2
    assert 'Digital research page' in result['text']
    assert 'Research Libraries Connect Ideas' in result['text']
    assert result['ocrUsed'] is True
