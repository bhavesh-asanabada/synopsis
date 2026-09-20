import base64
import io
import json
import threading
import zipfile
from uuid import uuid4

import pytest
from PIL import Image

from synopsis import create_app
from synopsis.diagrams import diagram_svg
from tests_helpers import semantic_fixture

H={'X-Synopsis-Request':'1'}


@pytest.fixture
def app(tmp_path):
    app=create_app({'TESTING':True,'DATA_DIR':str(tmp_path/'data'),'PROCESS_JOBS':False,'EMBEDDER':semantic_fixture})
    yield app
    app.extensions['watcher'].close();app.extensions['processor'].pool.shutdown(wait=True)


@pytest.fixture
def client(app):return app.test_client()


def new_chat(client):return client.post('/api/chat/conversations',json={},headers=H).json


def send(client,chat,**fields):
    payload={'message':'Explain dataset reliability','requestId':str(uuid4()),**fields}
    return client.post(f"/api/chat/conversations/{chat['id']}/messages",json=payload,headers=H)


def doc(app,title='Selected paper',text='Methods\nThirty participants formed a small dataset. Reliability was limited.'):
    return app.extensions['store'].create({'title':title,'text':text,'fileName':title+'.txt'})


def configure(client):
    response=client.patch('/api/settings',json={'ai':{'enabled':True,'endpoint':'https://chat.example/v1','model':'chosen-chat','apiKey':'chat-secret'},
                          'imageAI':{'enabled':True,'endpoint':'https://image.example/v1','model':'chosen-image','apiKey':'image-secret'},
                          'webSearch':{'enabled':True,'apiKey':'web-secret'}},headers=H)
    assert response.status_code==200,response.json


@pytest.fixture
def provider(monkeypatch):
    calls=[]
    class Reply:
        def __init__(self,data):self.data=data
        def raise_for_status(self):pass
        def json(self):return self.data
    def post(url,**kwargs):
        calls.append((url,kwargs));payload=kwargs['json']
        if url.endswith('/images/generations'):
            output=io.BytesIO();Image.new('RGB',(32,32),'green').save(output,'PNG')
            return Reply({'data':[{'b64_json':base64.b64encode(output.getvalue()).decode()}]})
        context=json.loads(payload['messages'][-1]['content'])
        result={'answer':'A supported research answer.','citations':[{'id':s['id'],'quote':s['text']} for s in context['sources']]}
        if context['mode']=='architecture':
            result['diagram']={'title':'Research platform','groups':[{'id':'client','label':'Client'},{'id':'services','label':'Services'}],
                               'nodes':[{'id':'web','label':'Web app','group':'client'},{'id':'api','label':'Flask API','group':'services'},{'id':'db','label':'Research database','group':'services'}],
                               'edges':[{'from':'web','to':'api','label':'HTTPS'},{'from':'api','to':'db','label':'Queries'}]}
        return Reply({'choices':[{'message':{'content':json.dumps(result)}}]})
    monkeypatch.setattr('synopsis.ai.requests.post',post)
    return calls


def test_scoped_chat_history_model_and_idempotency(app,client,provider):
    configure(client);selected=doc(app);other=doc(app,'Private unselected paper','A secret orchard document.')
    chat=new_chat(client);rid=str(uuid4())
    response=send(client,chat,fileIds=[selected['id']],requestId=rid)
    assert response.status_code==200,response.json
    messages=response.json['messages']
    assert messages[-1]['model']=='chosen-chat'
    assert {s['itemId'] for s in messages[-1]['sources']}=={selected['id']}
    context=json.loads(provider[-1][1]['json']['messages'][-1]['content'])
    assert all(s['itemId']==selected['id'] for s in context['sources'])
    assert other['text'] not in json.dumps(provider)
    replay=send(client,chat,fileIds=[selected['id']],requestId=rid)
    assert replay.status_code==200 and len(provider)==1
    assert send(client,chat,message='Different request',fileIds=[selected['id']],requestId=rid).status_code==409
    assert send(client,chat,message='Explain that further',fileIds=[selected['id']]).status_code==200
    assert any(m['role']=='assistant' for m in provider[-1][1]['json']['messages'])
    assert send(client,chat,message='Switch topics',fileIds=[other['id']]).status_code==200
    assert selected['text'] not in json.dumps(provider[-1][1]['json']['messages'])
    assert not any(m['role']=='assistant' for m in provider[-1][1]['json']['messages'])
    assert len(client.get(f"/api/chat/conversations/{chat['id']}").json['messages'])==6


def test_local_chat_and_missing_processing_documents(app,client):
    item=doc(app);chat=new_chat(client)
    result=send(client,chat,fileIds=[item['id']])
    assert result.status_code==200 and result.json['messages'][-1]['model']=='local retrieval'
    assert result.json['messages'][-1]['sources'][0]['itemId']==item['id']
    app.extensions['store'].update(item['id'],{'status':'processing'})
    assert send(client,chat,fileIds=[item['id']]).status_code==400
    app.extensions['store'].update(item['id'],{'status':'ready','trashed':True})
    assert send(client,chat,fileIds=[item['id']]).status_code==400
    assert send(client,chat,fileIds=['missing']).status_code==400
    assert len(client.get(f"/api/chat/conversations/{chat['id']}").json['messages'])==2
    assert send(client,chat,mode='architecture').status_code==400
    assert send(client,chat,mode='image').status_code==400


def test_web_search_explicit_scope_and_citations(app,client,provider,monkeypatch):
    configure(client);item=doc(app);chat=new_chat(client);searches=[]
    class Reply:
        def raise_for_status(self):pass
        def json(self):return {'web':{'results':[{'title':'Dataset study','url':'https://example.org/study','description':'A <b>small dataset</b> needs careful evaluation.','extra_snippets':['Use uncertainty estimates.']}]}}
    def get(url,**kwargs):searches.append((url,kwargs));return Reply()
    monkeypatch.setattr('synopsis.chat_tools.requests.get',get)
    assert send(client,chat,fileIds=[item['id']]).status_code==200
    assert searches==[]
    result=send(client,chat,message='Latest dataset research',fileIds=[item['id']],web=True)
    assert result.status_code==200,result.json
    sources=result.json['messages'][-1]['sources']
    assert {s['kind'] for s in sources}=={'web','document'}
    assert next(s for s in sources if s['kind']=='web')['url']=='https://example.org/study'
    assert searches[0][0]=='https://api.search.brave.com/res/v1/web/search'
    assert searches[0][1]['params']['q']=='Latest dataset research'
    assert item['text'] not in json.dumps(searches)
    assert searches[0][1]['headers']['X-Subscription-Token']=='web-secret'
    assert '<b>' not in json.dumps(sources)


def test_images_diagrams_download_and_backup_restore(app,client,provider,tmp_path):
    from manage import restore_backup
    configure(client);chat=new_chat(client)
    image=send(client,chat,message='Generate an image of a library')
    assert image.status_code==200,image.json
    artifact=image.json['messages'][-1]['artifact']
    assert artifact['kind']=='image' and 'data' not in artifact
    assert client.get(artifact['url']).data.startswith(b'\x89PNG')
    assert provider[-1][1]['json']['model']=='chosen-image'
    assert provider[-1][1]['headers']['Authorization']=='Bearer image-secret'
    assert 'response_format' not in provider[-1][1]['json']
    diagram=send(client,chat,message='Design a research platform architecture')
    assert diagram.status_code==200,diagram.json
    artifact=diagram.json['messages'][-1]['artifact']
    svg=client.get(artifact['url']+'?download=1')
    assert svg.status_code==200 and svg.mimetype=='image/svg+xml' and b'Flask API' in svg.data
    assert client.get(artifact['url']+'?format=json').json['nodes'][0]['id']=='web'
    assert client.get(f"/api/chat/conversations/{chat['id']}/export").json['messages'][-1]['artifact']['data']
    backup=client.get('/api/backup')
    with zipfile.ZipFile(io.BytesIO(backup.data)) as archive:
        payload=archive.read('library.json')
        assert all(secret not in payload for secret in [b'image-secret',b'chat-secret',b'web-secret'])
    path=tmp_path/'backup.zip';path.write_bytes(backup.data)
    restored=tmp_path/'restored';restore_backup(path,restored)
    other=create_app({'TESTING':True,'DATA_DIR':str(restored),'PROCESS_JOBS':False,'EMBEDDER':semantic_fixture})
    try:
        assert other.test_client().get(artifact['url']).data==svg.data
        settings=other.test_client().get('/api/settings').json
        assert not settings['imageAI']['enabled'] and not settings['webSearch']['enabled']
        assert not settings['imageAI']['hasSavedApiKey']
    finally:other.extensions['watcher'].close();other.extensions['processor'].pool.shutdown(wait=True)


def test_chat_sources_protect_documents_until_conversation_deleted(app,client):
    item=doc(app);chat=new_chat(client)
    assert send(client,chat,fileIds=[item['id']]).status_code==200
    app.extensions['store'].update(item['id'],{'trashed':True,'filePath':''})
    assert client.delete('/api/items/'+item['id'],headers=H).status_code==400
    assert client.delete('/api/chat/conversations/'+chat['id'],headers=H).status_code==200
    assert client.delete('/api/items/'+item['id'],headers=H).status_code==200
    assert client.get('/api/chat/conversations/'+chat['id']).status_code==404


@pytest.mark.parametrize('bad',[{'citations':[]},{'citations':[{'id':'invented','quote':'x'}]}, {'answer':42}])
def test_invalid_answers_leave_conversation_unchanged(app,client,monkeypatch,bad):
    configure(client);item=doc(app);chat=new_chat(client)
    class Reply:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':json.dumps({'answer':'Unsupported answer','citations':[],**bad})}}]}
    monkeypatch.setattr('synopsis.ai.requests.post',lambda *a,**k:Reply())
    assert send(client,chat,fileIds=[item['id']]).status_code==400
    assert client.get('/api/chat/conversations/'+chat['id']).json['messages']==[]


def test_diagram_validation_and_passive_svg():
    data={'title':'Safe <script>title</script>','nodes':[{'id':'a','label':'<script>alert(1)</script>'},{'id':'b','label':'Database'}],'edges':[{'from':'a','to':'b','label':'<image onload="bad">'}]}
    clean,svg=diagram_svg(data)
    assert '<script>' not in svg and '<image' not in svg and '&lt;script&gt;' in svg
    assert len(clean['nodes'])==2
    for bad in [{}, {'nodes':[]},{**data,'edges':[{'from':'missing','to':'a'}]},{**data,'nodes':[{'id':'a','label':'One'},{'id':'a','label':'Two'}]}]:
        with pytest.raises(ValueError):diagram_svg(bad)


def test_image_url_not_fetched_and_provider_errors_preserve_history(app,client,monkeypatch):
    configure(client);chat=new_chat(client)
    class Reply:
        def raise_for_status(self):pass
        def json(self):return {'data':[{'url':'http://127.0.0.1/private'}]}
    monkeypatch.setattr('synopsis.ai.requests.post',lambda *a,**k:Reply())
    monkeypatch.setattr('synopsis.chat_tools.requests.get',lambda *a,**k:pytest.fail('Image URL must never be fetched'))
    assert send(client,chat,mode='image').status_code==400
    assert client.get('/api/chat/conversations/'+chat['id']).json['messages']==[]


def test_chat_input_validation_and_write_origin(app,client):
    chat=new_chat(client)
    for fields in [{'message':''},{'message':'x'*4001},{'fileIds':'all'},{'fileIds':[5]},{'mode':'shell'},{'web':'yes'},{'requestId':'x'}]:
        assert send(client,chat,**fields).status_code==400
    assert client.post('/api/chat/conversations',json={}).status_code==403


def test_concurrent_send_and_delete_are_rejected(app,client,monkeypatch):
    configure(client);chat=new_chat(client);entered=threading.Event();finish=threading.Event();responses=[]
    def blocking(*a,**k):
        entered.set();assert finish.wait(10)
        return {'answer':'Completed','citations':[]}
    monkeypatch.setattr('synopsis.chat.complete',blocking)
    def first():
        with app.test_client() as other:responses.append(send(other,chat))
    thread=threading.Thread(target=first);thread.start()
    try:
        assert entered.wait(5)
        assert send(client,chat).status_code==409
        assert client.delete('/api/chat/conversations/'+chat['id'],headers=H).status_code==409
    finally:finish.set();thread.join()
    assert responses[0].status_code==200
    assert len(client.get('/api/chat/conversations/'+chat['id']).json['messages'])==2
