"""Advanced workflows exercised through the actual desktop and mobile interface."""
import threading
from pathlib import Path
import pytest
import pymupdf
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from synopsis import create_app
from synopsis.documents import fingerprint
from tests_helpers import semantic_fixture


@pytest.fixture
def workspace(tmp_path):
    app=create_app({'DATA_DIR':str(tmp_path/'data'),'TESTING':True,'EMBEDDER':semantic_fixture})
    store=app.extensions['store'];store.set_setting('metadataLookup',False)
    for title,text in [
        ('Small dataset reliability','Question\nHow does dataset size affect reliability?\n\nMethods\nThirty participants provided a small dataset.\n\nResults\nSmall samples reduced reliable generalization.\n\nLimitations\nThe sample was small.'),
        ('Replication study','Question\nDoes more data improve reliability?\n\nMethods\nSixty participants provided a larger dataset.\n\nResults\nPerformance improved with more observations.')]:
        store.create({'title':title,'authors':['Lovelace, Ada'],'year':'2024','text':text,'pageTexts':[{'page':1,'text':text,'hash':fingerprint(text),'method':'document-text','pagination':'logical','words':[]}],'pageCount':1})
    server=make_server('127.0.0.1',0,app,threaded=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield app,f'http://127.0.0.1:{server.server_port}',tmp_path
    server.shutdown();app.extensions['watcher'].close();app.extensions['processor'].pool.shutdown(wait=True)


def test_research_browser_complete_workflows(workspace):
    app,url,tmp_path=workspace
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(url);expect(page.locator('.reference')).to_have_count(2)
        page.get_by_role('button',name='Research workspace',exact=True).click()
        research=page.locator('#research-dialog')
        expect(research).to_be_visible()
        research.get_by_role('button',name='Evidence',exact=True).click()
        research.locator('#notebook-create [name=title]').fill('Dataset reliability')
        research.get_by_role('button',name='Create notebook',exact=True).click()
        expect(research.locator('.research-card h3')).to_contain_text(['Dataset reliability'])
        research.get_by_role('button',name='Search & ask',exact=True).click()
        research.get_by_role('textbox',name='Research question',exact=True).fill('small datasets reliability')
        research.get_by_role('button',name='Find evidence',exact=True).click()
        expect(research.locator('#research-results .source-card').first).to_be_visible()
        research.get_by_role('button',name='Use as evidence',exact=True).first.click()
        research.locator('[name=claim]').fill('Small samples can reduce reliability.')
        research.locator('[name=stance]').select_option('qualifies')
        research.locator('[name=interpretation]').fill('A small dataset is described; review the outcome separately.')
        research.get_by_role('button',name='Save evidence',exact=True).click()
        expect(research.locator('.evidence-claim h4')).to_have_text('Small samples can reduce reliability.')
        research.get_by_role('button',name='Compare',exact=True).click()
        research.locator('#matrix-create [name=title]').fill('Two studies compared')
        ids=[i['id'] for i in app.extensions['store'].items()]
        research.locator('#matrix-create [name=ids]').select_option(ids)
        research.locator('#matrix-create [name=columns]').fill('methods, findings, Custom judgment')
        research.get_by_role('button',name='Build comparison',exact=True).click()
        expect(research.locator('.matrix-table tbody tr')).to_have_count(2)
        research.locator('[data-edit-cell="Custom judgment"]').first.click()
        research.locator('#matrix-cell [name=text]').fill('User reviewed, with a cited passage.')
        research.locator('#matrix-cell [name=sources]').select_option(index=0)
        research.get_by_role('button',name='Save reviewed cell',exact=True).click()
        expect(research.get_by_text('User reviewed, with a cited passage.',exact=True)).to_be_visible()
        with page.expect_download() as downloaded:
            research.get_by_role('link',name='Export CSV',exact=True).click()
        assert downloaded.value.suggested_filename=='synopsis-comparison.csv'
        research.get_by_role('button',name='Paper insights',exact=True).click()
        expect(research.get_by_role('heading',name='Methods',exact=True)).to_be_visible()
        page.screenshot(path='artifacts/research-insights.png',full_page=True)
        research.get_by_role('button',name='Versions',exact=True).click()
        research.locator('#versions-create [name=title]').fill('Preprint and published version')
        research.locator('#versions-create [name=ids]').select_option(ids)
        research.get_by_role('button',name='Link selected versions',exact=True).click()
        expect(research.get_by_role('heading',name='Preprint and published version',exact=True)).to_be_visible()
        research.locator('#diff-form [name=left]').select_option(ids[0]);research.locator('#diff-form [name=right]').select_option(ids[1])
        research.get_by_role('button',name='Show changes',exact=True).click()
        expect(research.locator('#diff-results .diff-block').first).to_be_visible()
        research.get_by_role('button',name='Graph',exact=True).click()
        expect(research.locator('.research-graph')).to_be_visible()
        research.get_by_text('Add an explicit relationship',exact=True).click()
        research.locator('#relation-create [name=source]').select_option(ids[0]);research.locator('#relation-create [name=target]').select_option(ids[1])
        research.locator('#relation-create [name=kind]').select_option('related')
        research.locator('#relation-create [name=note]').fill('These studies address the same question.')
        research.get_by_role('button',name='Save relationship',exact=True).click()
        research.locator('#graph-filter').select_option('related')
        expect(research.locator('.research-graph line')).to_have_count(1)
        research.get_by_role('button',name='Reviews',exact=True).click()
        research.locator('#review-create [name=title]').fill('Reliability review')
        research.locator('#review-create [name=criteria]').fill('Include studies with empirical data.')
        research.locator('#review-create [name=reviewers]').fill('Ada')
        research.locator('#review-create [name=ids]').select_option(ids)
        research.get_by_role('button',name='Create review',exact=True).click()
        research.get_by_role('button',name='Record decision',exact=True).first.click()
        research.locator('#review-decision [name=reason]').fill('Meets the inclusion criteria.')
        research.get_by_role('button',name='Record decision',exact=True).click()
        expect(research.locator('.review-flow')).to_contain_text('abstract Included')
        research.get_by_role('button',name='Automation',exact=True).click()
        research.locator('#rule-create [name=contains]').fill('study')
        research.locator('#rule-create [name=tags]').fill('reading-list')
        research.get_by_role('button',name='Save rule',exact=True).click()
        research.get_by_role('button',name='Apply to existing library',exact=True).click()
        expect(page.locator('#toast-region')).to_contain_text('Rules matched')
        research.get_by_role('button',name='AI & alerts',exact=True).click()
        research.locator('#research-settings [name=endpoint]').fill('http://127.0.0.1:11434/v1')
        research.locator('#research-settings [name=model]').fill('configured-local-model')
        # Deliberately leave provider disabled; no external service is called in this browser test.
        research.get_by_role('button',name='Save research preferences',exact=True).click()
        expect(research.locator('[name=endpoint]')).to_have_value('http://127.0.0.1:11434/v1')
        page.set_viewport_size({'width':390,'height':844})
        research.get_by_role('button',name='Evidence',exact=True).click()
        expect(research.locator('.evidence-claim')).to_be_visible()
        page.screenshot(path='artifacts/research-mobile.png',full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        research.get_by_role('button',name='Close research workspace',exact=True).click()
        page.reload();page.get_by_role('button',name='Research workspace',exact=True).click()
        research.get_by_role('button',name='Evidence',exact=True).click()
        expect(research.locator('.evidence-claim h4')).to_have_text('Small samples can reduce reliability.')
        assert errors==[]
        browser.close()


def test_reader_region_capture_annotation_and_source_navigation(workspace):
    app,url,tmp_path=workspace
    with pymupdf.open() as pdf:
        page=pdf.new_page(width=500,height=700)
        page.insert_text((40,90),'Research results are linked to their sources.',fontsize=16)
        page.insert_text((40,130),'Methods include a carefully selected population.',fontsize=13)
        path=tmp_path/'paper.pdf';pdf.save(path)
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(url)
        page.locator('#file-input').set_input_files(str(path))
        expect(page.locator('#upload-results')).to_contain_text('ready for review',timeout=30000)
        page.locator('[data-open-upload]').click()
        page.get_by_role('button',name='Advanced reader',exact=True).click()
        r=page.locator('#research-dialog')
        expect(r.locator('.page-stage img')).to_be_visible()
        r.locator('.page-stage img').evaluate('(img)=>img.decode()')
        box=r.locator('.page-stage').bounding_box()
        page.mouse.move(box['x']+box['width']*.06,box['y']+box['height']*.07)
        page.mouse.down();page.mouse.move(box['x']+box['width']*.8,box['y']+box['height']*.23,steps=8);page.mouse.up()
        expect(r.locator('#region-form')).to_be_visible()
        r.locator('#region-form [name=text]').fill('Results region')
        r.locator('#region-form [name=comment]').fill('Review against source.')
        with page.expect_download() as captured:
            r.get_by_role('button',name='Download region image',exact=True).click()
        assert captured.value.suggested_filename.endswith('.png')
        r.get_by_role('button',name='Save region annotation',exact=True).click()
        expect(r.locator('.page-annotation')).to_have_count(1)
        with page.expect_download() as annotated:
            r.get_by_role('link',name='Export annotated PDF',exact=True).click()
        assert annotated.value.suggested_filename.endswith('-annotated.pdf')
        r.get_by_role('button',name='Highlight this passage',exact=True).first.click()
        expect(r.locator('.annotation-card')).to_have_count(2)
        page.screenshot(path='artifacts/advanced-reader.png',full_page=True)
        assert errors==[]
        browser.close()
