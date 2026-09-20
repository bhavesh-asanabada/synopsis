import base64
import io
import json
import threading

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from synopsis import create_app
from tests_helpers import semantic_fixture


@pytest.fixture
def chat_app(tmp_path,monkeypatch):
    app=create_app({'TESTING':True,'DATA_DIR':str(tmp_path/'data'),'EMBEDDER':semantic_fixture})
    store=app.extensions['store'];store.set_setting('metadataLookup',False)
    store.set_setting('ai',{'enabled':True,'endpoint':'https://chat.example/v1','model':'research-model'})
    store.set_setting('imageAI',{'enabled':True,'endpoint':'https://images.example/v1','model':'image-model'})
    store.set_setting('webSearch',{'enabled':True});store.set_setting('webSearchCredential','fixture-key')
    first=store.create({'title':'Dataset reliability','fileName':'datasets.txt','text':'Methods\nThirty participants formed a small dataset.\n\nResults\nReliability was reduced.'})
    store.create({'title':'Unselected private paper','fileName':'private.txt','text':'Keep this unrelated secret out of the prompt.'})
    calls=[]
    class Reply:
        def __init__(self,value):self.value=value
        def raise_for_status(self):pass
        def json(self):return self.value
    def provider(url,**kwargs):
        calls.append((url,kwargs))
        if '/images/' in url:
            output=io.BytesIO();Image.new('RGB',(64,64),'#a8bb92').save(output,'PNG')
            return Reply({'data':[{'b64_json':base64.b64encode(output.getvalue()).decode()}]})
        context=json.loads(kwargs['json']['messages'][-1]['content'])
        answer={'answer':'The selected evidence suggests limited reliability.','citations':[{'id':s['id'],'quote':s['text']} for s in context['sources']]}
        if context['mode']=='architecture':
            answer['answer']='Proposed architecture: the web client sends requests to the API, which uses the research database.'
            answer['diagram']={'title':'Research platform architecture','groups':[{'id':'users','label':'Experience'},{'id':'backend','label':'Application'},{'id':'storage','label':'Data'}],
                               'nodes':[{'id':'web','label':'Web client','group':'users'},{'id':'api','label':'Research API','group':'backend'},{'id':'db','label':'Research database','group':'storage'}],
                               'edges':[{'from':'web','to':'api','label':'HTTPS'},{'from':'api','to':'db','label':'Read and write'}]}
        return Reply({'choices':[{'message':{'content':json.dumps(answer)}}]})
    monkeypatch.setattr('synopsis.ai.requests.post',provider)
    monkeypatch.setattr('synopsis.chat_tools.requests.get',lambda *a,**k:Reply({'web':{'results':[{'title':'Published study','url':'https://example.org/paper','description':'A published study discusses dataset reliability.'}]}}))
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    yield app,f'http://127.0.0.1:{server.server_port}',first,calls
    server.shutdown();app.extensions['watcher'].close();app.extensions['processor'].pool.shutdown(wait=True)


def test_floating_chat_files_followups_and_workspace_history(chat_app):
    app,url,first,calls=chat_app
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':900})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(url)
        page.get_by_role('button',name='Open Synopsis chat',exact=True).click()
        expect(page.locator('#chat-dialog')).to_have_class('chat-mini')
        page.get_by_role('button',name='Choose chat files',exact=True).click()
        page.locator(f'[data-chat-file="{first["id"]}"]').check()
        page.get_by_role('button',name='Choose chat files',exact=True).click()
        page.get_by_label('Chat message',exact=True).fill('What does the paper say about reliability?')
        page.get_by_label('Chat message',exact=True).press('Enter')
        expect(page.locator('.chat-assistant .chat-message-text')).to_contain_text('limited reliability')
        assert 'Keep this unrelated secret' not in json.dumps(calls)
        page.get_by_label('Chat message',exact=True).fill('Explain that further')
        page.get_by_role('button',name='Send chat message',exact=True).click()
        expect(page.locator('.chat-assistant')).to_have_count(2)
        assert any(m['role']=='assistant' for m in calls[-1][1]['json']['messages'])
        page.screenshot(path='artifacts/chat-floating.png')
        page.get_by_role('button',name='Expand chat workspace',exact=True).click()
        expect(page.locator('#chat-dialog')).to_have_class('chat-full')
        expect(page.locator('.chat-assistant')).to_have_count(2)
        expect(page.locator(f'[data-chat-file="{first["id"]}"]')).to_be_checked()
        saved_id=page.locator('#chat-history').input_value()
        page.get_by_role('button',name='New conversation',exact=True).click()
        expect(page.locator('.chat-assistant')).to_have_count(0)
        page.locator('#chat-history').select_option(saved_id)
        expect(page.locator('.chat-assistant')).to_have_count(2)
        page.get_by_role('button',name='Close chat',exact=True).click()
        page.reload()
        page.get_by_role('button',name='Chat workspace',exact=True).click()
        page.locator('#chat-history').select_option(saved_id)
        expect(page.locator('.chat-assistant')).to_have_count(2)
        with page.expect_download() as download:page.locator('.chat-history-actions').get_by_role('link',name='Export',exact=True).click()
        assert download.value.suggested_filename=='synopsis-conversation.json'
        assert errors==[]
        browser.close()


def test_chat_web_images_and_architecture_downloads(chat_app):
    app,url,first,calls=chat_app
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
        page.goto(url);page.get_by_role('button',name='Chat workspace',exact=True).click()
        page.locator('#chat-web').check()
        page.get_by_label('Chat message',exact=True).fill('Find recent dataset research')
        page.get_by_role('button',name='Send chat message',exact=True).click()
        expect(page.locator('.chat-source summary')).to_contain_text('Web · Published study')
        page.locator('#chat-web').uncheck()
        page.locator('#chat-mode').select_option('architecture')
        page.get_by_label('Chat message',exact=True).fill('Design a research platform architecture')
        page.get_by_role('button',name='Send chat message',exact=True).click()
        expect(page.get_by_alt_text('Research platform architecture')).to_be_visible()
        assert page.get_by_alt_text('Research platform architecture').evaluate('(img)=>img.complete && img.naturalWidth>0')
        page.get_by_role('button',name='Zoom in diagram',exact=True).click()
        with page.expect_download() as download:page.get_by_role('link',name='Download SVG',exact=True).click()
        assert download.value.suggested_filename=='architecture.svg'
        with page.expect_download() as download:page.get_by_role('link',name='Diagram data',exact=True).click()
        assert download.value.suggested_filename=='architecture.json'
        page.screenshot(path='artifacts/chat-architecture.png')
        page.locator('#chat-mode').select_option('image')
        page.get_by_label('Chat message',exact=True).fill('Illustrate a quiet research library')
        page.get_by_role('button',name='Send chat message',exact=True).click()
        expect(page.get_by_alt_text('Image generated from your prompt')).to_be_visible()
        with page.expect_download() as download:page.get_by_role('link',name='Download PNG',exact=True).click()
        assert download.value.suggested_filename=='synopsis-image.png'
        assert any(request['json']['model']=='image-model' for _,request in calls)
        browser.close()


def test_mobile_chat_upload_and_error_recovery(chat_app,monkeypatch):
    app,url,first,calls=chat_app
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':390,'height':844})
        page.goto(url);page.get_by_role('button',name='Open Synopsis chat',exact=True).click()
        page.locator('#chat-upload').set_input_files({'name':'new-study.txt','mimeType':'text/plain','buffer':b'Research on dataset reliability\nMethods\nWe studied thirty participants.\n'})
        expect(page.locator('#chat-file-count')).to_have_text('1')
        page.get_by_label('Chat message',exact=True).fill('Explain dataset reliability')
        expect(page.get_by_role('button',name='Send chat message',exact=True)).to_be_enabled(timeout=30000)
        original=app.extensions['store'].setting('ai')
        app.extensions['store'].set_setting('ai',{**original,'enabled':False})
        page.locator('#chat-mode').select_option('architecture')
        page.get_by_role('button',name='Send chat message',exact=True).click()
        expect(page.locator('#chat-error')).to_contain_text('Enable an AI model')
        expect(page.get_by_label('Chat message',exact=True)).to_have_value('Explain dataset reliability')
        app.extensions['store'].set_setting('ai',original)
        page.get_by_role('button',name='Send chat message',exact=True).click()
        expect(page.locator('.chat-artifact')).to_have_count(1)
        assert len(app.extensions['store'].entities('chats')[0]['messages'])==2
        page.get_by_role('button',name='Expand chat workspace',exact=True).click()
        assert page.evaluate('document.scrollingElement.scrollHeight === innerHeight && document.scrollingElement.scrollWidth === innerWidth')
        page.get_by_role('button',name='Choose chat files',exact=True).click()
        expect(page.get_by_label('Filter chat files',exact=True)).to_be_visible()
        page.get_by_role('button',name='Choose chat files',exact=True).click()
        page.screenshot(path='artifacts/chat-mobile.png')
        page.get_by_role('button',name='Chat settings',exact=True).click()
        expect(page.get_by_label('AI model identifier',exact=True)).to_be_visible()
        page.get_by_role('tab',name='Chat tools',exact=True).click()
        expect(page.get_by_label('Image model identifier',exact=True)).to_be_visible()
        browser.close()
