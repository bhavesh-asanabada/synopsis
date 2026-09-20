import threading
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from test_cloud import cloud_app, Reply


def test_cloud_connection_destination_upload_retry_and_mobile(cloud_app,monkeypatch):
    app,calls,remote,provider=cloud_app
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            def consent(route):
                params=parse_qs(urlsplit(route.request.url).query)
                assert params['redirect_uri'][0]==origin+'/api/connectors/google/callback'
                route.fulfill(status=302,headers={'Location':params['redirect_uri'][0]+'?'+urlencode({'state':params['state'][0],'code':'mock-consent'})})
            page.route('https://accounts.google.com/**',consent)
            page.goto(origin);page.get_by_role('button',name='Workspace settings',exact=True).click()
            page.get_by_role('tab',name='Cloud storage',exact=True).click()
            expect(page.get_by_label('Save new documents to',exact=True)).to_have_value('local')
            page.get_by_label('Google Drive client ID',exact=True).fill('client-123')
            page.get_by_label('Google Drive client secret',exact=True).fill('private-secret')
            page.get_by_role('button',name='Connect Google Drive',exact=True).click()
            expect(page.locator('#cloud-settings-status')).to_contain_text('Account connected')
            page.get_by_label('Save new documents to',exact=True).select_option('google')
            page.get_by_role('button',name='Apply storage destination',exact=True).click()
            expect(page.locator('#cloud-settings-status')).to_have_text('Storage destination saved.')
            page.locator('#cloud-connectors').scroll_into_view_if_needed()
            page.screenshot(path='artifacts/cloud-connectors.png')
            page.get_by_role('button',name='Close dialog',exact=True).click()
            page.locator('#file-input').set_input_files({'name':'cloud-study.txt','mimeType':'text/plain','buffer':b'Reliable cloud research\nMethods\nWe test persistent storage.'})
            expect(page.locator('[data-open-upload]')).to_have_count(1)
            item=app.extensions['store'].items()[0];cloud=app.extensions['cloud']
            app.extensions['processor'].process(item['id'])
            monkeypatch.setattr('synopsis.cloud.requests.request',lambda *a,**k:Reply(status=403))
            cloud.transfer(item['id'])
            page.locator('[data-open-upload]').click()
            expect(page.locator('.cloud-document')).to_contain_text('Needs attention')
            expect(page.locator('.cloud-transfer-error')).to_contain_text('access was denied')
            monkeypatch.setattr('synopsis.cloud.requests.request',provider)
            page.get_by_role('button',name='Retry cloud upload',exact=True).click()
            expect(page.locator('.cloud-document')).to_contain_text('Waiting to upload')
            cloud.transfer(item['id'])
            expect(page.locator('.cloud-document')).to_contain_text('Google Drive · Saved',timeout=10000)
            expect(page.get_by_role('link',name='Open cloud copy',exact=True)).to_have_attribute('href','https://drive.google.com/file/d/generated-1/view')
            page.reload();page.locator('.reference').click()
            expect(page.locator('.cloud-document')).to_contain_text('Google Drive · Saved')
            page.set_viewport_size({'width':390,'height':844})
            page.get_by_role('button',name='Workspace settings',exact=True).click()
            page.get_by_role('tab',name='Cloud storage',exact=True).click()
            page.locator('#cloud-connectors').scroll_into_view_if_needed()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('[data-connector=google] summary').click()
            page.on('dialog',lambda dialog:dialog.accept())
            page.get_by_role('button',name='Disconnect Google Drive',exact=True).click()
            expect(page.get_by_label('Save new documents to',exact=True)).to_have_value('local')
            expect(page.locator('#cloud-settings-status')).to_contain_text('Cloud copies were kept')
            assert len(remote)==1 and not errors
            browser.close()
    finally:
        server.shutdown()
