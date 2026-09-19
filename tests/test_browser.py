"""Real-browser checks against an isolated Flask library, never the user's data."""
import threading

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from synopsis import create_app


@pytest.fixture
def browser_app(tmp_path):
    app = create_app({'DATA_DIR': str(tmp_path), 'TESTING': True})
    app.extensions['store'].set_setting('metadataLookup', False)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield app, f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    app.extensions['processor'].pool.shutdown(wait=True)


def test_browser_library_workflow(browser_app, tmp_path):
    app, url = browser_app
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors=[]
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(url)
        expect(page.get_by_role('heading', name='Your next discovery starts here.')).to_be_visible()
        page.screenshot(path='artifacts/library-empty.png', full_page=True)
        page.get_by_role('button', name='Add your first document').click()
        page.get_by_role('button', name='Manual entry', exact=True).click()
        page.locator('[name=title]').fill('The architecture of a thoughtful research library')
        page.locator('[name=authors]').fill('Lovelace, Ada\nCurie, Marie')
        page.locator('[name=year]').fill('2024')
        page.locator('[name=journal]').fill('Journal of Knowledge')
        page.get_by_role('button', name='Add reference', exact=True).click()
        expect(page.locator('.reference')).to_have_count(1)
        expect(page.locator('.detail-heading h2')).to_have_text('The architecture of a thoughtful research library')
        page.get_by_role('button', name='Star reference', exact=True).click()
        expect(page.locator('.star-button')).to_have_class('icon-button star-button starred')
        page.get_by_role('button', name='New collection', exact=True).click()
        page.locator('[name=name]').fill('Literature review')
        page.get_by_role('button', name='Create collection', exact=True).click()
        expect(page.locator('#page-title')).to_have_text('Literature review.')
        page.locator('[data-action=organize]').click()
        page.locator('[name=tags]').fill('research, knowledge')
        page.get_by_label('Literature review', exact=True).check()
        page.get_by_role('button', name='Save organization').click()
        expect(page.locator('.reference')).to_have_count(1)
        page.locator('[data-tab=notes]').click()
        page.locator('#note-text').fill('Connect this idea to semantic search and archival memory.')
        page.get_by_role('button', name='Save note', exact=True).click()
        expect(page.locator('.note p')).to_have_text('Connect this idea to semantic search and archival memory.')
        page.locator('#search').fill('archival memory')
        expect(page.locator('.reference')).to_have_count(1)
        page.locator('#search').fill('impossible term')
        expect(page.locator('.reference')).to_have_count(0)
        page.get_by_role('button', name='Clear filters').click()
        expect(page.locator('.reference')).to_have_count(1)
        page.get_by_role('button', name='Cite', exact=True).click()
        expect(page.locator('#citation-preview')).to_contain_text('Lovelace')
        page.locator('#citation-style').select_option('vancouver')
        expect(page.locator('#citation-preview')).to_contain_text('2024')
        with page.expect_download() as download:
            page.locator('[data-export=bibtex]').click()
        assert download.value.suggested_filename == 'synopsis-library.bib'
        page.get_by_role('button', name='Close dialog').click()
        page.locator('[data-tab=info]').click()
        page.screenshot(path='artifacts/library-reference.png', full_page=True)
        page.reload()
        expect(page.locator('.reference')).to_have_count(1)
        page.locator('.reference').click()
        page.locator('[data-tab=notes]').click()
        expect(page.locator('.note p')).to_contain_text('archival memory')
        document = tmp_path / 'research.txt'
        document.write_text('New Directions in Research Libraries\nAuthor: Hopper, Grace\nYear: 2025\n\nAbstract\nAn unexpected connection between ideas and discovery.')
        page.locator('#file-input').set_input_files(str(document))
        expect(page.locator('#upload-results')).to_contain_text('ready for review', timeout=30000)
        page.locator('[data-open-upload]').click()
        expect(page.locator('.detail-heading h2')).to_have_text('New Directions in Research Libraries')
        expect(page.locator('.detail-heading>p')).to_have_text('Hopper, Grace')
        page.get_by_role('button', name='Read document', exact=True).click()
        expect(page.locator('#extracted-text')).to_contain_text('unexpected connection')
        page.get_by_role('button', name='Save a highlight', exact=True).click()
        page.get_by_role('textbox', name='Passage', exact=True).fill('An unexpected connection between ideas and discovery.')
        page.get_by_role('button', name='Save highlight', exact=True).click()
        expect(page.locator('.highlight p')).to_contain_text('unexpected connection')
        page.locator('[data-tab=info]').click()
        page.get_by_role('button', name='Looks good', exact=True).click()
        expect(page.get_by_text('Metadata ready for review', exact=True)).to_have_count(0)
        page.get_by_role('button', name='Move to trash', exact=True).click()
        page.get_by_role('button', name='Restore to library', exact=True).click()
        expect(page.get_by_role('button', name='Move to trash', exact=True)).to_be_visible()
        page.get_by_role('button', name='Close details', exact=True).click()
        page.set_viewport_size({'width':390, 'height':844})
        page.screenshot(path='artifacts/library-mobile.png', full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.get_by_role('button', name='Toggle navigation', exact=True).click()
        expect(page.locator('#sidebar')).to_have_class('sidebar mobile-open')
        page.locator('[data-scope=all]').click()
        page.get_by_role('button', name='Workspace settings', exact=True).click()
        expect(page.get_by_text('Tesseract is installed and ready.', exact=False)).to_be_visible()
        page.get_by_role('button', name='Save preferences', exact=True).click()
        assert errors == []
        browser.close()


def test_table_columns_and_library_workflow(browser_app):
    app, url = browser_app
    store = app.extensions['store']
    first = store.create({'title': 'Alpha research', 'authors': ['Lovelace, Ada'],
                          'year': '2024', 'doi': '10.1234/example', 'journal': 'Knowledge'})
    for number in range(24):
        store.create({'title': f'Beta research {number:02}', 'year': '2023'})
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        page.get_by_role('button', name='Table view', exact=True).click()
        expect(page.locator('.table-reference')).to_have_count(25)
        page.get_by_label('Sort references').select_option('title')
        expect(page.locator('.table-reference').first).to_have_attribute('data-id', first['id'])
        page.get_by_role('button', name='Columns', exact=True).click()
        page.get_by_label('Publication', exact=True).uncheck()
        page.get_by_label('DOI', exact=True).check()
        page.get_by_role('button', name='Done', exact=True).click()
        expect(page.locator('th[data-column="journal"]')).to_have_count(0)
        expect(page.locator('.table-reference').first.locator('.column-doi')).to_have_text('10.1234/example')
        page.locator('th[data-column="authors"]').drag_to(page.locator('th[data-column="title"]'))
        assert page.locator('th[data-column]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.column)') == ['authors', 'title', 'year', 'type', 'doi']
        expect(page.locator('#drop-overlay')).to_be_hidden()
        page.locator('[data-column-header="title"]').focus()
        page.keyboard.press('Alt+ArrowLeft')
        assert page.locator('th[data-column]').first.get_attribute('data-column') == 'title'
        page.reload()
        expect(page.get_by_role('button', name='Table view', exact=True)).to_have_attribute('aria-pressed', 'true')
        assert page.locator('th[data-column]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.column)') == ['title', 'authors', 'year', 'type', 'doi']
        page.get_by_label('Search your library').fill('Alpha research')
        expect(page.locator('.table-reference')).to_have_count(1)
        row = page.locator('.table-reference')
        row.get_by_role('checkbox').check()
        page.get_by_role('button', name='Mark read', exact=True).click()
        expect(page.locator('#toast-region')).to_contain_text('References marked as read')
        assert store.get(first['id'])['read'] is True
        row.get_by_role('button', name='Star reference', exact=True).click()
        expect(row.get_by_role('button', name='Unstar reference', exact=True)).to_be_visible()
        row.locator('.column-title').click()
        expect(page.locator('.detail-heading h2')).to_have_text('Alpha research')
        page.get_by_role('button', name='Close details', exact=True).click()
        page.get_by_label('Search your library').fill('')
        expect(page.locator('.table-reference')).to_have_count(25)
        for width, height in [(1440, 900), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            dimensions = page.evaluate('({height:document.scrollingElement.scrollHeight,width:document.scrollingElement.scrollWidth,viewportHeight:innerHeight,viewportWidth:innerWidth})')
            assert dimensions['height'] == height and dimensions['width'] == width, dimensions
            assert page.locator('.library-main').evaluate('(e)=>{e.scrollTop=200;return e.scrollTop>0}')
            assert page.locator('.library-table-scroll').evaluate('(e)=>{e.scrollLeft=200;return e.scrollLeft>0}')
        page.locator('.library-main').evaluate('(e)=>e.scrollTop=0')
        page.get_by_role('button', name='Columns', exact=True).click()
        page.get_by_role('button', name='Move Title later', exact=True).click()
        expect(page.locator('.column-option').first.locator('label')).to_have_text('Authors')
        page.get_by_role('button', name='Reset columns', exact=True).click()
        for key in ['authors', 'year', 'journal', 'type']:
            page.locator(f'[data-column-toggle="{key}"]').uncheck()
        page.locator('[data-column-toggle="title"]').click()
        expect(page.locator('[data-column-toggle="title"]')).to_be_checked()
        expect(page.locator('#toast-region')).to_contain_text('Keep at least one column visible')
        page.get_by_role('button', name='Reset columns', exact=True).click()
        page.get_by_role('button', name='Done', exact=True).click()
        expect(page.locator('th[data-column]')).to_have_count(5)
        page.get_by_role('button', name='Grid view', exact=True).click()
        expect(page.locator('.item-grid .reference')).to_have_count(25)
        page.get_by_role('button', name='List view', exact=True).click()
        expect(page.locator('.item-list .reference')).to_have_count(25)
        assert errors == []
        browser.close()


def test_empty_table_and_invalid_preferences(browser_app):
    _, url = browser_app
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        page.goto(url)
        page.evaluate("localStorage.setItem('synopsis.library-view', JSON.stringify({view:'table', order:['unknown','title','title'], columns:['unknown']}))")
        page.reload()
        expect(page.get_by_role('button', name='Add your first document')).to_be_visible()
        expect(page.get_by_role('button', name='Table view', exact=True)).to_have_attribute('aria-pressed', 'true')
        assert page.locator('.library-main').evaluate('(e)=>{e.scrollTop=200;return e.scrollTop===0}')
        page.get_by_role('button', name='Columns', exact=True).click()
        expect(page.locator('[data-column-toggle]:checked')).to_have_count(5)
        page.get_by_role('button', name='Done', exact=True).click()
        page.evaluate("localStorage.setItem('synopsis.library-view', '{broken')")
        page.reload()
        expect(page.get_by_role('button', name='List view', exact=True)).to_have_attribute('aria-pressed', 'true')
        expect(page.get_by_role('button', name='Add your first document')).to_be_visible()
        browser.close()


def test_upload_folder_settings_workflow(browser_app, tmp_path):
    app, url = browser_app
    destination = tmp_path / 'Chosen documents' / 'Research'
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.goto(url)
        page.get_by_role('button', name='Workspace settings', exact=True).click()
        page.get_by_label('Upload folder', exact=True).fill(str(destination))
        page.get_by_role('button', name='Save preferences', exact=True).click()
        expect(page.locator('#modal')).not_to_be_visible()
        assert destination.is_dir()
        page.locator('#file-input').set_input_files({'name':'custom-location.txt', 'mimeType':'text/plain', 'buffer':b'A research document in a chosen folder\nAuthor: Lovelace, Ada\n'})
        expect(page.locator('#upload-results')).to_contain_text('ready for review', timeout=30000)
        item = app.extensions['store'].items()[0]
        assert app.extensions['store'].document_path(item).parent == destination
        assert app.extensions['store'].document_path(item).exists()
        page.get_by_role('button', name='Close dialog', exact=True).click()
        page.reload()
        page.get_by_role('button', name='Workspace settings', exact=True).click()
        expect(page.get_by_label('Upload folder', exact=True)).to_have_value(str(destination))
        page.get_by_label('Upload folder', exact=True).fill('relative/path')
        page.get_by_role('button', name='Save preferences', exact=True).click()
        expect(page.locator('#toast-region')).to_contain_text('absolute folder path')
        expect(page.locator('#modal')).to_be_visible()
        page.get_by_role('button', name='Use default folder', exact=True).click()
        page.get_by_role('button', name='Save preferences', exact=True).click()
        expect(page.locator('#modal')).not_to_be_visible()
        assert app.extensions['store'].uploads == app.extensions['store'].default_uploads
        assert page.request.get(url + f"/api/items/{item['id']}/file").status == 200
        browser.close()
