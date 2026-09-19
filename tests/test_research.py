import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pymupdf
import pytest

from synopsis import create_app
from synopsis.documents import fingerprint, validate_rect, inverse_rect
from synopsis.intelligence import passages_for, validate_source, Intelligence
from synopsis.workflows import review_state, review_report
from tests_helpers import semantic_fixture

H={'X-Synopsis-Request':'1'}


@pytest.fixture
def app(tmp_path):
    app=create_app({'DATA_DIR':str(tmp_path/'library'),'TESTING':True,'PROCESS_JOBS':False,'EMBEDDER':semantic_fixture})
    app.extensions['store'].set_setting('metadataLookup',False)
    yield app
    app.extensions['watcher'].close()
    app.extensions['processor'].pool.shutdown(wait=True)


@pytest.fixture
def client(app):
    return app.test_client()


def document(app,title='Research on small datasets',text=None,**extra):
    text=text or ('Research question\nHow does data scarcity affect reliability?\n\nMethods\nWe evaluated models on a small dataset of 30 participants.\n\n'
                  'Results\nSmall datasets increased variance and reduced reliable generalization.\n\nLimitations\nThe sample was too small for causal conclusions.\n\n'
                  'Future work\nFurther research should evaluate larger populations.')
    return app.extensions['store'].create({'title':title,'authors':['Lovelace, Ada'],'year':'2024','text':text,
           'pageTexts':[{'page':1,'text':text,'hash':fingerprint(text),'method':'embedded-text','words':[]}],'pageCount':1,**extra})


def post(client,path,body):
    return client.post('/api/research'+path,json=body,headers=H)


def source(item):
    return passages_for(item)[0]


def test_insights_sources_and_section_absence(app,client):
    item=document(app)
    result=client.get(f"/api/research/items/{item['id']}/insights").json
    assert result['mode']=='local-extractive'
    assert 'small dataset' in result['sections']['methods']['text']
    assert result['sections']['limitations']['sources'][0]['page']==1
    for section in result['sections'].values():
        for s in section['sources']:
            assert s['text'] == item['pageTexts'][0]['text'][s['start']:s['end']]
    unknown=document(app,'Gardening',text='Apples and oranges are growing in the orchard.')
    missing=client.get(f"/api/research/items/{unknown['id']}/insights").json
    assert missing['sections']['methods']['status']=='not-found'


def test_semantic_search_filters_and_excludes_trash(app,client):
    relevant=document(app)
    document(app,'Gardening',text='The garden contains many apples and orange trees.',authors=['Gardener, Gary'],year='2021')
    document(app,'Secret discarded source',trashed=True)
    result=post(client,'/search',{'query':'scarce training data reliability','filters':{'year':'2024','author':'lovelace'}})
    assert result.status_code==200
    assert result.json['results']
    assert {r['itemId'] for r in result.json['results']}=={relevant['id']}
    assert all('probability' in r['scoreMeaning'] for r in result.json['results'])
    assert post(client,'/search',{'query':'reliability','filters':{'ids':[]}}).json['results']==[]
    for bad in [{'query':''},{'query':'hello','filters':[]},{'query':'hello','filters':{'ids':[3]}}]:
        assert post(client,'/search',bad).status_code==400


def test_ask_is_extract_only_unless_explicit(app,client,monkeypatch):
    document(app)
    monkeypatch.setattr('synopsis.intelligence.requests.post',lambda *a,**k:pytest.fail('Unexpected external document transmission'))
    result=post(client,'/ask',{'query':'small datasets reliability'})
    assert result.json['mode']=='extractive'
    assert result.json['claims']==[]
    assert result.json['sources']
    assert post(client,'/ask',{'query':'small dataset','useAI':True}).status_code==400
    assert post(client,'/ask',{'query':'small dataset','useAI':'yes'}).status_code==400


def configure_ai(client):
    result=client.patch('/api/research/settings',json={'ai':{'enabled':True,'endpoint':'https://ai.example/v1','model':'test-model'}},headers=H)
    assert result.status_code==200


def test_ai_validates_quotes_and_never_exposes_api_key(app,client,monkeypatch):
    item=document(app);s=source(item);configure_ai(client)
    monkeypatch.setenv('SYNOPSIS_AI_API_KEY','test-secret-do-not-display')
    requests=[]
    class Reply:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':json.dumps({'claims':[{'text':'Interpretation requiring review','citations':[{'id':s['id'],'quote':'How does data scarcity affect reliability?'}]}]})}}]}
    def fake(url,**kwargs):requests.append((url,kwargs));return Reply()
    monkeypatch.setattr('synopsis.intelligence.requests.post',fake)
    result=app.extensions['intelligence'].synthesize('Explain this',[s])
    assert result['claims'][0]['reviewRequired'] is True
    assert result['claims'][0]['citations'][0]['quote'] in s['text']
    assert requests[0][1]['headers']['Authorization']=='Bearer test-secret-do-not-display'
    assert requests[0][1]['allow_redirects'] is False
    assert 'test-secret-do-not-display' not in client.get('/api/research/overview').text
    assert 'test-secret-do-not-display' not in client.get('/api/backup').data.decode('latin1')


@pytest.mark.parametrize('claim',[
    {'text':'Invented','citations':[{'id':'not-a-real-source','quote':'Made up'}]},
    {'text':'Wrong quote','citations':[{'id':'VALID','quote':'A sentence the source never said.'}]},
    {'text':'No citation','citations':[]},
    {'text':42,'citations':[{'id':'VALID','quote':'anything'}]},
])
def test_ai_rejects_unsupported_output_atomically(app,client,monkeypatch,claim):
    item=document(app);s=source(item);configure_ai(client)
    claim=json.loads(json.dumps(claim).replace('VALID',s['id']))
    class Reply:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':json.dumps({'claims':[claim]})}}]}
    monkeypatch.setattr('synopsis.intelligence.requests.post',lambda *a,**k:Reply())
    with pytest.raises(ValueError):app.extensions['intelligence'].synthesize('What does it say?',[s])
    assert app.extensions['store'].entities('notebooks')==[]


def test_provider_failure_and_insecure_config(app,client,monkeypatch):
    item=document(app);configure_ai(client)
    monkeypatch.setattr('synopsis.intelligence.requests.post',lambda *a,**k:(_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(ValueError,match='provider failed'):
        app.extensions['intelligence'].synthesize('Question',[source(item)])
    for url in ['http://remote.example/v1','https://user:password@remote.example/v1','file:///etc/passwd','https://remote.example/v1?key=secret']:
        assert client.patch('/api/research/settings',json={'ai':{'enabled':True,'endpoint':url,'model':'x'}},headers=H).status_code==400


def test_evidence_quotes_staleness_and_protected_sources(app,client):
    item=document(app);s=source(item)
    notebook=post(client,'/notebooks',{'title':'Does sample size affect reliability?'}).json
    body={'claim':'Small samples reduce reliability','stance':'qualifies','source':s,'interpretation':'This source asks a question; it does not answer it.'}
    result=post(client,f"/notebooks/{notebook['id']}/claims",body)
    assert result.status_code==201
    assert result.json['claims'][0]['classification']=='user-interpretation'
    assert post(client,f"/notebooks/{notebook['id']}/claims",{**body,'source':{**s,'quote':'fabricated'}}).status_code==400
    assert client.get(f"/api/research/notebooks/{notebook['id']}/export").status_code==200
    app.extensions['store'].update(item['id'],{'pageTexts':[{'page':1,'text':'Completely different text.','hash':fingerprint('Completely different text.')}]})
    assert post(client,f"/notebooks/{notebook['id']}/claims",body).status_code==400
    client.patch('/api/items/'+item['id'],json={'trashed':True},headers=H)
    assert client.delete('/api/items/'+item['id'],headers=H).status_code==400
    client.delete(f"/api/research/records/notebooks/{notebook['id']}",headers=H)
    assert client.delete('/api/items/'+item['id'],headers=H).status_code==200


def test_concurrent_claim_appends_do_not_lose_entries(app,client):
    item=document(app);n=post(client,'/notebooks',{'title':'Concurrent evidence'}).json
    def append(number):
        with app.test_client() as c:
            return post(c,f"/notebooks/{n['id']}/claims",{'claim':f'Claim {number}','stance':'context','source':source(item)}).status_code
    with ThreadPoolExecutor(max_workers=5) as pool:
        assert list(pool.map(append,range(15)))==[201]*15
    assert len(app.extensions['store'].entity('notebooks',n['id'])['claims'])==15


def test_matrix_manual_columns_source_validation_audit_and_csv(app,client):
    a=document(app);b=document(app,'Another study')
    matrix=post(client,'/matrices',{'title':'Evidence matrix','ids':[a['id'],b['id']],'columns':['methods','Sample quality']}).json
    assert matrix['rows'][0]['cells']['Sample quality']['status']=='not-found'
    body={'itemId':a['id'],'column':'Sample quality','text':'=A potentially dangerous CSV cell','sources':[source(a)]}
    result=client.patch(f"/api/research/matrices/{matrix['id']}/cell",json=body,headers=H)
    assert result.status_code==200
    assert len(result.json['history'])==1
    assert result.json['rows'][0]['cells']['Sample quality']['status']=='user-reviewed'
    bad=client.patch(f"/api/research/matrices/{matrix['id']}/cell",json={**body,'sources':[source(b)]},headers=H)
    assert bad.status_code==400
    exported=client.get(f"/api/research/matrices/{matrix['id']}/export")
    assert "'=A potentially dangerous" in exported.data.decode('utf-8-sig')
    assert source(a)['id'] in exported.text


def test_review_gating_conflicts_adjudication_and_revisions(app,client):
    item=document(app)
    review=post(client,'/reviews',{'title':'Systematic review','criteria':'Include empirical datasets','reviewers':['A','B'],'ids':[item['id']]}).json
    url=f"/reviews/{review['id']}/decisions"
    base={'itemId':item['id'],'stage':'abstract','reviewer':'A','decision':'include','reason':''}
    assert post(client,url,{**base,'stage':'fulltext'}).status_code==400
    assert post(client,url,{**base,'decision':'exclude'}).status_code==400
    assert post(client,url,{**base,'reviewer':'Unknown'}).status_code==400
    assert post(client,url,base).json['results'][0]['abstract']['status']=='pending'
    conflict=post(client,url,{**base,'reviewer':'B','decision':'exclude','reason':'Wrong design'}).json
    assert conflict['counts']['conflicts']==1
    resolved=post(client,url,{**base,'adjudication':True,'reason':'Consensus meeting: empirical evidence qualifies'}).json
    assert resolved['results'][0]['abstract']['status']=='include'
    post(client,url,{**base,'stage':'fulltext'})
    complete=post(client,url,{**base,'stage':'fulltext','reviewer':'B'}).json
    assert complete['counts']['fulltextIncluded']==1
    revised=post(client,url,{**base,'decision':'exclude','reason':'Criterion corrected'}).json
    assert revised['results'][0]['fulltext']['status']=='blocked'
    assert revised['counts']['fulltextIncluded']==0
    assert len(revised['decisions'])==6
    assert client.get(f"/api/research/reviews/{review['id']}/export").status_code==200


def test_versions_and_diff_do_not_move_annotations(app,client):
    a=document(app,'Preprint',text='Methods\nThirty subjects were recruited.\n\nResults\nAn effect was observed.')
    b=document(app,'Published',text='Methods\nSixty subjects were recruited.\n\nResults\nNo effect was observed.')
    app.extensions['store'].update(a['id'],{'annotations':[{'id':'a1','page':1,'text':'Thirty subjects were recruited.'}]})
    result=post(client,'/versions',{'title':'Versions of our study','ids':[a['id'],b['id']]})
    assert result.status_code==201
    assert post(client,'/versions',{'title':'Duplicate grouping','ids':[a['id'],b['id']]}).status_code==400
    diff=client.get(f"/api/research/diff?left={a['id']}&right={b['id']}").json
    assert diff['annotationsRemainOnOriginal'] is True
    assert any('Thirty' in c['before'] and 'Sixty' in c['after'] for c in diff['changes'])
    assert app.extensions['store'].get(b['id'])['annotations']==[]


def test_graph_distinguishes_candidate_and_asserted_links(app,client):
    a=document(app,doi='10.1234/one',tags=['Methods'])
    b=document(app,'Followup',references=[{'text':'See 10.1234/one for earlier research.'}])
    post(client,'/relations',{'source':a['id'],'target':b['id'],'kind':'conflicts','note':'User interpretation, not inferred from citations.'})
    graph=client.get('/api/research/graph').json
    assert any(e['kind']=='citation-candidate' for e in graph['edges'])
    assert any(e['kind']=='conflicts' and e['provenance']=='user-asserted' for e in graph['edges'])
    assert any(n['kind']=='author' for n in graph['nodes'])
    assert post(client,'/relations',{'source':a['id'],'target':a['id'],'kind':'cites'}).status_code==400


def test_services_preserve_results_on_outage(app,client,monkeypatch):
    item=document(app,doi='10.1234/a')
    monkeypatch.setattr('synopsis.research.publication_status',lambda doi:{'doi':doi,'status':'updates-reported','updates':[{'doi':'10.1234/notice','type':'retraction'}],'checkedAt':'2026-09-18'})
    assert post(client,f"/items/{item['id']}/status",{}).status_code==200
    monkeypatch.setattr('synopsis.research.publication_status',lambda doi:(_ for _ in ()).throw(TimeoutError()))
    assert post(client,f"/items/{item['id']}/status",{}).status_code==502
    retained=app.extensions['store'].entity('status',item['id'])
    assert retained['updates'][0]['type']=='retraction'
    assert 'stale' in retained['error']
    monkeypatch.setattr('synopsis.research.openalex_work',lambda doi:{'id':'https://openalex.org/W1','referenced_works':['https://openalex.org/W2']})
    assert post(client,f"/items/{item['id']}/discover",{}).status_code==200
    assert any(e['provenance']=='openalex' for e in client.get('/api/research/graph').json['edges'])


def test_crossref_update_direction_is_checked(monkeypatch):
    from synopsis.services import publication_status
    monkeypatch.setattr('synopsis.services.get_json',lambda *a,**kw:{'message':{'items':[
        {'DOI':'10.1234/notice','title':['Retraction'],'update-to':[{'DOI':'10.1234/a','type':'retraction','source':'retraction-watch'}]},
        {'DOI':'10.1234/unrelated','update-to':[{'DOI':'10.1234/other','type':'correction'}]}]}})
    result=publication_status('10.1234/a')
    assert len(result['updates'])==1
    assert result['updates'][0]['source']=='retraction-watch'


def pdf_document(app,client):
    with pymupdf.open() as pdf:
        page=pdf.new_page(width=500,height=700)
        page.insert_text((40,80),'Research evidence has a stable source.',fontsize=16)
        page.insert_text((40,120),'Methods include thirty participants.',fontsize=14)
        data=pdf.tobytes()
    response=client.post('/api/upload',data={'files':(io.BytesIO(data),'research.pdf')},headers=H)
    item=response.json['items'][0];app.extensions['processor'].process(item['id'])
    return app.extensions['store'].get(item['id']),data


def test_page_geometry_region_capture_and_annotated_pdf(app,client,tmp_path):
    destination=tmp_path/'custom-document-storage'
    assert client.patch('/api/settings',json={'uploadDirectory':str(destination)},headers=H).status_code==200
    item,original=pdf_document(app,client)
    assert app.extensions['store'].document_path(item).parent==destination
    assert client.patch('/api/settings',json={'uploadDirectory':''},headers=H).status_code==200
    image=client.get(f"/api/research/items/{item['id']}/pages/1/image")
    assert image.status_code==200 and image.data.startswith(b'\x89PNG')
    page=item['pageTexts'][0]
    assert page['words'] and page['hash']
    rect=page['words'][0]['rect']
    result=post(client,f"/items/{item['id']}/annotations",{'page':1,'pageHash':page['hash'],'kind':'region','rects':[rect],'text':'Evidence label','comment':'Check this finding'})
    assert result.status_code==201
    captured=post(client,f"/items/{item['id']}/capture",{'page':1,'rect':[.05,.05,.8,.3]})
    assert captured.status_code==200 and captured.data.startswith(b'\x89PNG')
    exported=client.get(f"/api/research/items/{item['id']}/annotated.pdf")
    with pymupdf.open(stream=exported.data,filetype='pdf') as pdf:
        annotations=list(pdf[0].annots())
        assert len(annotations)==1
        assert annotations[0].info['content']=='Check this finding'
    assert client.get(f"/api/items/{item['id']}/file?download=1").data==original
    bad=post(client,f"/items/{item['id']}/annotations",{'page':1,'pageHash':'outdated','kind':'region','rects':[rect],'text':'bad'})
    assert bad.status_code==400
    assert post(client,f"/items/{item['id']}/capture",{'page':1,'rect':[-1,0,1,1]}).status_code==400
    assert client.get(f"/api/research/items/{item['id']}/pages/999/image").status_code==400


def test_text_annotation_rejects_fabricated_excerpt(app,client):
    item=document(app);p=item['pageTexts'][0]
    assert post(client,f"/items/{item['id']}/annotations",{'page':1,'pageHash':p['hash'],'kind':'highlight','text':'Invented quotation','rects':[]}).status_code==400
    assert post(client,f"/items/{item['id']}/annotations",{'page':1,'pageHash':p['hash'],'kind':'highlight','text':'How does data scarcity affect reliability?','rects':[]}).status_code==201


def test_rules_and_watched_folder_are_idempotent(app,client,tmp_path):
    destination=tmp_path/'saved-papers'
    assert client.patch('/api/settings',json={'uploadDirectory':str(destination)},headers=H).status_code==200
    collection=client.post('/api/collections',json={'name':'Small datasets'},headers=H).json
    rule=post(client,'/rules',{'field':'text','contains':'participants','tags':['study'],'collections':[collection['id']]}).json
    intake=tmp_path/'intake';intake.mkdir();file=intake/'article.txt';file.write_text('Study of small datasets\nMethods\nThirty participants were included.\n')
    os.utime(file,(time.time()-5,time.time()-5))
    watcher=post(client,'/watchers',{'path':str(intake),'collection':collection['id']}).json
    result=post(client,f"/watchers/{watcher['id']}/scan",{})
    assert result.status_code==200 and len(result.json['files'])==1
    item_id=result.json['files'][0]['id']
    for _ in range(100):
        if app.extensions['store'].get(item_id)['status']=='ready':break
        time.sleep(.02)
    item=app.extensions['store'].get(item_id)
    assert app.extensions['store'].document_path(item).parent==destination
    assert item['tags']==['study'] and collection['id'] in item['collections']
    assert file.exists()
    assert post(client,f"/watchers/{watcher['id']}/scan",{}).json['files']==[]
    assert post(client,'/watchers',{'path':str(app.extensions['store'].uploads)}).status_code==400
    post(client,'/rules/apply',{})
    assert app.extensions['store'].get(item_id)['tags']==['study']


def test_merge_preserves_every_original_and_notes(app,client):
    a=document(app,'Primary',tags=['a']);b,data=pdf_document(app,client)
    store=app.extensions['store'];store.update(b['id'],{'tags':['b'],'notes':[{'id':'note1','text':'Keep me','createdAt':'2026-01-01'}],
                                                            'annotations':[{'id':'ann1','page':1,'text':'Research evidence'}]})
    result=post(client,'/merge',{'target':a['id'],'sources':[b['id']]})
    assert result.status_code==200
    assert result.json['tags']==['a','b']
    assert result.json['notes'][0]['sourceItemId']==b['id']
    assert b['id'] in result.json['attachments']
    assert client.get('/api/library').json['counts']['all']==1
    assert client.get(f"/api/items/{b['id']}/file?download=1").data==data
    assert store.get(b['id'])['annotations'][0]['id']=='ann1'
    assert post(client,'/merge',{'target':a['id'],'sources':[b['id']]}).status_code==400


def test_advanced_records_survive_backup_without_auto_transmitting(app,client,tmp_path):
    from manage import restore_backup
    item=document(app);notebook=post(client,'/notebooks',{'title':'Recovered evidence'}).json
    post(client,f"/notebooks/{notebook['id']}/claims",{'claim':'A claim','stance':'context','source':source(item)})
    configure_ai(client)
    intake=tmp_path/'incoming';intake.mkdir();post(client,'/watchers',{'path':str(intake)})
    backup=tmp_path/'backup.zip';backup.write_bytes(client.get('/api/backup').data)
    restored=tmp_path/'restored';restore_backup(backup,restored)
    other=create_app({'DATA_DIR':str(restored),'TESTING':True,'PROCESS_JOBS':False})
    restored_data=other.test_client().get('/api/research/overview').json
    assert restored_data['notebooks'][0]['claims'][0]['source']['id']==source(item)['id']
    assert restored_data['ai']['enabled'] is False
    assert restored_data['watchers'][0]['enabled'] is False
    other.extensions['processor'].pool.shutdown()


def test_invalid_research_payloads_return_actionable_errors(app,client):
    for path,body in [('/notebooks',{'title':''}),('/matrices',{'title':'x','ids':[]}),('/reviews',{'title':'x','ids':[]}),
                      ('/relations',{'source':'missing','target':'missing','kind':'cites'}),('/rules',{'field':'untrusted'}),
                      ('/watchers',{'path':'/nonexistent-folder-for-synopsis-test'})]:
        assert post(client,path,body).status_code==400,(path,body)
    assert client.post('/api/research/search',json={'query':'research'}).status_code==403


def test_real_local_semantic_model_understands_paraphrase(tmp_path):
    # This is an actual ONNX inference check, not a stubbed service response.
    from synopsis.storage import Store
    store=Store(tmp_path/'semantic')
    text='A limited number of training examples causes unstable predictions and poor performance on unseen observations.'
    relevant=store.create({'title':'Data limitations','text':text,'pageTexts':[{'page':1,'text':text,'hash':fingerprint(text)}]})
    other='Apple trees require fertile soil, sunlight, and regular pruning for a productive harvest.'
    store.create({'title':'Orchards','text':other,'pageTexts':[{'page':1,'text':other,'hash':fingerprint(other)}]})
    result=Intelligence(store).search('Why do small datasets hurt model generalization?')
    assert result[0]['itemId']==relevant['id']
    assert result[0]['score']>result[1]['score']


def test_export_rejects_stale_geometry_after_reprocessing(app,client):
    item,_=pdf_document(app,client);page=item['pageTexts'][0]
    post(client,f"/items/{item['id']}/annotations",{'page':1,'pageHash':page['hash'],'kind':'region','rects':[[.1,.1,.3,.2]],'text':'Original area'})
    app.extensions['store'].update(item['id'],{'pageTexts':[{**page,'text':'Changed extraction','hash':fingerprint('Changed extraction')}]})
    result=client.get(f"/api/research/items/{item['id']}/annotated.pdf")
    assert result.status_code==400 and 'stale' in result.json['error']


def test_text_highlight_has_geometry_and_repeated_quote_uses_offset(app,client):
    from synopsis.documents import rects_for_quote
    item,_=pdf_document(app,client);page=item['pageTexts'][0]
    result=post(client,f"/items/{item['id']}/annotations",{'page':1,'pageHash':page['hash'],'kind':'highlight','text':'Research evidence','start':page['text'].index('Research evidence')})
    assert result.status_code==201
    assert result.json['anchorStatus']=='positioned'
    assert result.json['rects']
    repeated={'text':'same same','words':[{'text':'same','rect':[0,.1,.2,.2]},{'text':'same','rect':[.3,.1,.5,.2]}]}
    assert rects_for_quote(repeated,'same',5)==[[.3,.1,.5,.2]]
    with pytest.raises(ValueError):rects_for_quote(repeated,'same',1)


def test_rotation_transform_and_pdf_table_extraction(app,client):
    assert inverse_rect([.1,.2,.3,.4],90)==[.2,.7,.4,.9]
    with pymupdf.open() as pdf:
        p=pdf.new_page(width=500,height=500)
        p.insert_text((30,35),'Technical report on a controlled experiment',fontsize=12)
        for x in (40,220,400):p.draw_line((x,80),(x,230))
        for y in (80,130,180,230):p.draw_line((40,y),(400,y))
        for point,text in [((50,110),'Group'),((230,110),'Participants'),((50,160),'Control'),((230,160),'30'),((50,210),'Treatment'),((230,210),'40')]:
            p.insert_text(point,text,fontsize=12)
        data=pdf.tobytes()
    result=client.post('/api/upload',data={'files':(io.BytesIO(data),'table.pdf')},headers=H).json['items'][0]
    app.extensions['processor'].process(result['id'])
    item=app.extensions['store'].get(result['id'])
    assert item['status']=='ready'
    assert item['type']=='report'
    assert item['tables'][0]['rows'][1]==['Control','30']
    assert item['tables'][0]['reviewed'] is False
    assert item['provenance']['type']['reviewRequired'] is True


def test_processing_resumes_after_restart(tmp_path):
    from synopsis.storage import Store
    store=Store(tmp_path/'restart');store.set_setting('metadataLookup',False)
    (store.uploads/'restart.txt').write_text('Restarted research document\nAuthor: Ada Lovelace\n')
    item=store.create({'title':'Waiting','fileName':'restart.txt','filePath':'restart.txt','status':'processing','reviewed':False})
    app=create_app({'DATA_DIR':str(store.root),'TESTING':True,'PROCESS_JOBS':True})
    for _ in range(100):
        if store.get(item['id'])['status']=='ready':break
        time.sleep(.03)
    assert store.get(item['id'])['status']=='ready'
    assert store.get(item['id'])['title']=='Restarted research document'
    app.extensions['processor'].pool.shutdown()


def test_no_evidence_response_does_not_invent_an_answer(app,client,monkeypatch):
    document(app)
    monkeypatch.setattr(app.extensions['intelligence'],'search',lambda *args,**kwargs:[])
    result=post(client,'/ask',{'query':'An unanswerable question','useAI':True})
    assert result.status_code==200
    assert result.json['status']=='not-found'
    assert result.json['claims']==[]


def test_local_ai_compatible_http_contract(app,client):
    # Exercise real HTTP request/response parsing, with a deterministic local provider fixture.
    from flask import Flask, request, jsonify
    from werkzeug.serving import make_server
    from threading import Thread
    item=document(app);s=source(item);provider=Flask('ai-fixture')
    received=[]
    @provider.post('/v1/chat/completions')
    def completion():
        body=request.get_json();received.append(body)
        return jsonify(choices=[{'message':{'content':json.dumps({'claims':[{'text':'A draft grounded in the supplied question.',
                            'citations':[{'id':s['id'],'quote':s['text']}]}]})}}])
    server=make_server('127.0.0.1',0,provider);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        client.patch('/api/research/settings',json={'ai':{'enabled':True,'endpoint':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}},headers=H)
        result=app.extensions['intelligence'].synthesize('Question',[s])
        assert result['status']=='draft'
        assert received[0]['response_format']=={'type':'json_object'}
        assert json.loads(received[0]['messages'][1]['content'])['passages'][0]['id']==s['id']
    finally:
        server.shutdown()


def test_watched_file_change_during_copy_is_retried_not_committed(app,tmp_path,monkeypatch):
    from synopsis.services import import_local_file
    import shutil
    intake=tmp_path/'changing.txt';intake.write_text('Original document body.')
    original_copy=shutil.copyfile
    def changing_copy(source,target):
        result=original_copy(source,target)
        source.write_text('A concurrently rewritten document with different content.')
        return result
    monkeypatch.setattr('synopsis.services.shutil.copyfile',changing_copy)
    with pytest.raises(ValueError,match='changed while being copied'):
        import_local_file(app.extensions['store'],app.extensions['processor'],intake)
    assert app.extensions['store'].items()==[]
    assert list(app.extensions['store'].uploads.iterdir())==[]


def test_suggestions_and_publication_alerts_surface_in_library(app,client):
    collection=client.post('/api/collections',json={'name':'Dataset reliability'},headers=H).json
    item=document(app)
    app.extensions['store'].put_entity('status',{'id':item['id'],'status':'updates-reported','updates':[{'type':'retraction','doi':'10.1234/notice'}]})
    insights=client.get(f"/api/research/items/{item['id']}/insights").json
    assert insights['suggestedCollections'][0]['id']==collection['id']
    assert client.get('/api/library').json['items'][0]['publicationStatus']['updates'][0]['type']=='retraction'
    assert client.get('/api/items/'+item['id']).json['publicationStatus']['status']=='updates-reported'


def test_reversed_merge_is_rejected_and_detach_restores_source(app,client):
    a=document(app,'A');b=document(app,'B')
    assert post(client,'/merge',{'target':a['id'],'sources':[b['id']]}).status_code==200
    assert post(client,'/merge',{'target':b['id'],'sources':[a['id']]}).status_code==400
    assert client.get('/api/library').json['counts']['all']==1
    result=client.delete(f"/api/research/items/{a['id']}/attachments/{b['id']}",headers=H)
    assert result.status_code==200
    assert client.get('/api/library').json['counts']['all']==2
    assert app.extensions['store'].get(a['id'])['attachments']==[]


def test_summary_endpoint_reports_selected_source_coverage(app,client,monkeypatch):
    item=document(app)
    response=post(client,f"/items/{item['id']}/summary",{})
    assert response.status_code==200 and response.json['mode']=='local-extractive'
    received=[]
    def synthesize(question,sources):
        received.extend(sources)
        return {'mode':'ai','status':'draft','claims':[],'message':'Fixture draft'}
    monkeypatch.setattr(app.extensions['intelligence'],'synthesize',synthesize)
    response=post(client,f"/items/{item['id']}/summary",{'useAI':True})
    assert response.status_code==200
    assert response.json['coverage']['selectedPassages']==len(received)
    assert response.json['coverage']['totalPassages']==len(passages_for(item))
    assert all(validate_source(app.extensions['store'],s) for s in received)


def test_background_automation_and_daily_status_throttle(app,client,tmp_path,monkeypatch):
    from synopsis.services import WatchService
    store=app.extensions['store'];item=document(app,doi='10.1234/a')
    intake=tmp_path/'scheduled';intake.mkdir()
    watcher=post(client,'/watchers',{'path':str(intake)}).json
    service=app.extensions['watcher'];scanned=[];checked=[]
    monkeypatch.setattr(service,'scan',lambda watcher_id:scanned.append(watcher_id))
    monkeypatch.setattr('synopsis.services.publication_status',lambda doi:(checked.append(doi) or {'status':'no-updates-reported','updates':[],'checkedAt':'today'}))
    class OneTick:
        def __init__(self):self.n=0
        def wait(self,seconds):self.n+=1;return self.n>1
        def set(self):pass
    store.set_setting('automaticStatusChecks',True)
    service.stop_event=OneTick();service.run()
    assert scanned==[watcher['id']] and checked==['10.1234/a']
    service.stop_event=OneTick();service.run()
    assert checked==['10.1234/a']
    client.patch('/api/research/watchers/'+watcher['id'],json={'enabled':False},headers=H)
    service.stop_event=OneTick();service.run()
    assert scanned==[watcher['id'],watcher['id']]
