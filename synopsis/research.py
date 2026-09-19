"""Advanced research API. Source-dependent writes validate their anchors on the server."""
import csv
import io
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from flask import Blueprint, request, jsonify, send_file
from PIL import Image, ImageOps

from .documents import render_page, annotated_pdf, validate_rect, fingerprint, rects_for_quote
from .intelligence import Intelligence, passages_for, validate_source, SECTION_TERMS, pages_for
from .workflows import selected, active_item, text_field, record_decision, review_report, document_diff, local_graph
from .services import publication_status, openalex_work, apply_rules, WatchService
from .storage import now, summary


def csv_response(rows, filename):
    buffer=io.StringIO();writer=csv.writer(buffer)
    # Prevent exported free text from becoming spreadsheet formulas.
    for row in rows:
        writer.writerow(["'"+str(v) if str(v).startswith(('=','+','-','@','\t','\r')) else str(v) for v in row])
    return send_file(io.BytesIO(buffer.getvalue().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,download_name=filename)


def register_research(app,store,processor):
    bp=Blueprint('research',__name__,url_prefix='/api/research')
    intelligence=Intelligence(store,app.config.get('EMBEDDER'))
    watcher=WatchService(store,processor)
    app.extensions.update(intelligence=intelligence,watcher=watcher)

    def payload():
        result=request.get_json()
        if not isinstance(result,dict):
            raise ValueError('Expected a JSON object.')
        return result

    def entity(kind,entity_id):
        result=store.entity(kind,entity_id)
        if not result:
            raise ValueError('Research record not found.')
        return result

    def filters(data):
        f=data.get('filters',{})
        if not isinstance(f,dict):
            raise ValueError('Filters must be an object.')
        for key in ('author','year','type','collection'):
            if key in f and not isinstance(f[key],str):
                raise ValueError('Filter values must be text.')
        if 'ids' in f and (not isinstance(f['ids'],list) or any(not isinstance(i,str) for i in f['ids'])):
            raise ValueError('Document scope must be a list of IDs.')
        return f

    @bp.get('/overview')
    def overview():
        return jsonify(notebooks=store.entities('notebooks'),matrices=store.entities('matrices'),
                       reviews=[review_report(r) for r in store.entities('reviews')],versions=store.entities('versions'),
                       rules=store.entities('rules'),watchers=store.entities('watchers'),statuses=store.entities('status'),
                       ai={**store.setting('ai',{'enabled':False,'endpoint':'','model':''}),'hasApiKey':bool(os.environ.get('SYNOPSIS_AI_API_KEY'))},
                       automaticStatusChecks=store.setting('automaticStatusChecks',False))

    @bp.post('/search')
    def search():
        data=payload()
        return jsonify(results=intelligence.search(data.get('query',''),filters(data)))

    @bp.post('/ask')
    def ask():
        data=payload()
        if not isinstance(data.get('useAI',False),bool):
            raise ValueError('AI synthesis must be enabled explicitly.')
        return jsonify(intelligence.ask(data.get('query',''),filters(data),data.get('useAI',False)))

    @bp.get('/items/<item_id>/insights')
    def insights(item_id):
        item=active_item(store,item_id)
        result=intelligence.summary(item)
        searchable=(item['title']+' '+item.get('text','')[:20000]).casefold()
        suggested_collections=[{'id':c['id'],'name':c['name'],'reason':'Collection name terms occur in this document; confirm relevance.'}
                               for c in store.collections() if c['id'] not in item['collections']
                               and any(word in searchable for word in re.findall(r'\w{4,}',c['name'].casefold()))]
        return jsonify(**result,provenance=item.get('provenance',{}),language=item.get('language',''),
                       pages=[{k:v for k,v in p.items() if k not in ('text','words')} for p in pages_for(item)],
                       passages=passages_for(item),tables=item.get('tables',[]),references=item.get('references',[]),
                       suggestedCollections=suggested_collections,
                       suggestedTags=[t for t in sorted({t for i in store.items() if not i['trashed'] for t in i['tags']})
                                      if t not in item['tags'] and t.casefold() in item.get('text','').casefold()][:12])

    @bp.post('/items/<item_id>/summary')
    def ai_summary(item_id):
        item=active_item(store,item_id)
        data=payload()
        if data.get('useAI') is not True:
            return jsonify(intelligence.summary(item))
        passages=passages_for(item)
        # Bounded selected context is explicit; avoid implying whole-document coverage.
        selected_passages=[]
        for section in intelligence.summary(item)['sections'].values():
            for source in section['sources']:
                if source['id'] not in {p['id'] for p in selected_passages}:
                    selected_passages.append(source)
        selected_passages=selected_passages[:16] or passages[:12]
        if not selected_passages:
            raise ValueError('This document has no extracted text to summarize.')
        result=intelligence.synthesize('Summarize the research question, methods, datasets, findings, limitations, and unanswered questions. Label each claim by section. State missing information explicitly.',selected_passages)
        result['coverage']={'selectedPassages':len(selected_passages),'totalPassages':len(passages)}
        return jsonify(result)

    @bp.patch('/settings')
    def configure():
        data=payload()
        if 'ai' in data:
            ai=data['ai']
            if not isinstance(ai,dict) or not isinstance(ai.get('enabled'),bool):
                raise ValueError('Choose whether AI is enabled.')
            endpoint=text_field(ai.get('endpoint',''),'API base URL',2000,required=ai['enabled']).rstrip('/')
            model=text_field(ai.get('model',''),'Model',200,required=ai['enabled'])
            if endpoint:
                url=urlsplit(endpoint)
                if not url.hostname or url.username or url.password or url.query or url.fragment or url.scheme not in ('http','https'):
                    raise ValueError('Use an API base URL without credentials, query parameters, or fragments.')
                if url.scheme=='http' and url.hostname not in ('localhost','127.0.0.1','::1'):
                    raise ValueError('External APIs require HTTPS.')
            store.set_setting('ai',{'enabled':ai['enabled'],'endpoint':endpoint,'model':model})
        if 'automaticStatusChecks' in data:
            if not isinstance(data['automaticStatusChecks'],bool):
                raise ValueError('Automatic checks must be true or false.')
            store.set_setting('automaticStatusChecks',data['automaticStatusChecks'])
        return jsonify(ok=True)

    @bp.post('/notebooks')
    def notebook():
        data=payload()
        return jsonify(store.put_entity('notebooks',{'title':text_field(data.get('title'),'Notebook title',200),'claims':[]})),201

    @bp.post('/notebooks/<notebook_id>/claims')
    def claim(notebook_id):
        data=payload();source=validate_source(store,data.get('source'))
        stance=data.get('stance')
        if stance not in ('supports','conflicts','qualifies','context'):
            raise ValueError('Choose how this evidence relates to your claim.')
        entry={'id':str(uuid4()),'claim':text_field(data.get('claim'),'Claim'),
               'interpretation':text_field(data.get('interpretation',''),'Interpretation',required=False),
               'stance':stance,'source':source,'createdAt':now(),'classification':'user-interpretation'}
        return jsonify(store.mutate_entity('notebooks',notebook_id,lambda n:{'claims':n['claims']+[entry]})),201

    @bp.delete('/notebooks/<notebook_id>/claims/<claim_id>')
    def remove_claim(notebook_id,claim_id):
        return jsonify(store.mutate_entity('notebooks',notebook_id,lambda n:{'claims':[c for c in n['claims'] if c['id']!=claim_id]}))

    @bp.get('/notebooks/<notebook_id>/export')
    def export_notebook(notebook_id):
        notebook=entity('notebooks',notebook_id)
        rows=[['Claim','Relationship (user classification)','Interpretation','Source','Page','Exact quote','Passage ID','Document ID']]
        for c in notebook['claims']:
            s=c['source'];rows.append([c['claim'],c['stance'],c['interpretation'],s['title'],s['page'],s['quote'],s['id'],s['itemId']])
        return csv_response(rows,'synopsis-evidence.csv')

    @bp.post('/matrices')
    def matrix():
        data=payload();items=selected(store,data.get('ids',[]))
        columns=data.get('columns',list(SECTION_TERMS))
        if not isinstance(columns,list) or not 1<=len(columns)<=20 or any(not isinstance(c,str) or not c.strip() or len(c)>100 for c in columns):
            raise ValueError('Choose 1–20 column names (up to 100 characters each).')
        columns=list(dict.fromkeys(c.strip() for c in columns));rows=[]
        for item in items:
            sections=intelligence.summary(item)['sections'];cells={}
            for column in columns:
                cells[column]=sections.get(column,{'text':'','sources':[],'status':'not-found'})
            rows.append({'itemId':item['id'],'title':item['title'],'cells':cells})
        return jsonify(store.put_entity('matrices',{'title':text_field(data.get('title'),'Matrix title',200),'columns':columns,'rows':rows,'history':[]})),201

    @bp.patch('/matrices/<matrix_id>/cell')
    def matrix_cell(matrix_id):
        data=payload();text=text_field(data.get('text',''),'Cell text',20000,required=False)
        sources=data.get('sources',[])
        if not isinstance(sources,list) or len(sources)>20:
            raise ValueError('Choose up to 20 source passages.')
        sources=[validate_source(store,s) for s in sources]
        if any(s['itemId']!=data.get('itemId') for s in sources):
            raise ValueError('A matrix cell must cite the document in its row.')
        def change(matrix):
            row=next((r for r in matrix['rows'] if r['itemId']==data.get('itemId')),None)
            if row is None or data.get('column') not in matrix['columns']:
                raise ValueError('Matrix cell not found.')
            old=row['cells'][data['column']]
            row['cells'][data['column']]={'text':text,'sources':sources,'status':'user-reviewed' if sources else 'user-entry-uncited'}
            return {'rows':matrix['rows'],'history':matrix['history']+[{'at':now(),'itemId':data['itemId'],'column':data['column'],'before':old}]}
        return jsonify(store.mutate_entity('matrices',matrix_id,change))

    @bp.get('/matrices/<matrix_id>/export')
    def matrix_export(matrix_id):
        matrix=entity('matrices',matrix_id);rows=[['Document']+[f'{c} (text / source pages)' for c in matrix['columns']]]
        for row in matrix['rows']:
            values=[]
            for col in matrix['columns']:
                cell=row['cells'][col];refs='; '.join(f"p. {s['page']} [{s['id']}]" for s in cell['sources'])
                values.append(cell['text']+ ('\nSources: '+refs if refs else '\nNo cited passage'))
            rows.append([row['title']]+values)
        return csv_response(rows,'synopsis-comparison.csv')

    @bp.post('/reviews')
    def create_review():
        data=payload();items=selected(store,data.get('ids',[]),5000)
        reviewers=data.get('reviewers',[])
        if not isinstance(reviewers,list) or not 1<=len(reviewers)<=10:
            raise ValueError('Specify 1–10 reviewers.')
        reviewers=list(dict.fromkeys(text_field(r,'Reviewer',100) for r in reviewers))
        return jsonify(store.put_entity('reviews',{'title':text_field(data.get('title'),'Review title',200),
                       'criteria':text_field(data.get('criteria'),'Inclusion/exclusion criteria',20000),
                       'reviewers':reviewers,'items':[i['id'] for i in items], 'decisions':[]})),201

    @bp.get('/reviews/<review_id>')
    def get_review(review_id):
        return jsonify(review_report(entity('reviews',review_id)))

    @bp.post('/reviews/<review_id>/decisions')
    def decision(review_id):
        return jsonify(record_decision(store,review_id,payload()))

    @bp.get('/reviews/<review_id>/export')
    def export_review(review_id):
        review=entity('reviews',review_id)
        return csv_response([['Document ID','Stage','Reviewer','Decision','Reason','Timestamp','Adjudication','Event ID']]+[
            [e['itemId'],e['stage'],e['reviewer'],e['decision'],e['reason'],e['at'],e.get('adjudication',False),e['id']] for e in review['decisions']], 'synopsis-review-audit.csv')

    @bp.post('/versions')
    def versions():
        data=payload();items=selected(store,data.get('ids',[]))
        if len(items)<2:
            raise ValueError('Select at least two document versions.')
        for group in store.entities('versions'):
            if any(i['id'] in group['items'] for i in items):
                raise ValueError('A selected document already belongs to a version group. Remove that group before regrouping.')
        return jsonify(store.put_entity('versions',{'title':text_field(data.get('title'),'Version group',200),
                       'items':[i['id'] for i in items],'relationship':'user-confirmed-versions'})),201

    @bp.get('/diff')
    def diff():
        return jsonify(document_diff(active_item(store,request.args.get('left')),active_item(store,request.args.get('right'))))

    @bp.get('/graph')
    def graph():
        return jsonify(local_graph(store))

    @bp.post('/relations')
    def relation():
        data=payload();a=active_item(store,data.get('source'));b=active_item(store,data.get('target'))
        kind=data.get('kind')
        if a['id']==b['id'] or kind not in ('cites','supports','conflicts','related'):
            raise ValueError('Choose different papers and a valid relationship.')
        return jsonify(store.put_entity('relations',{'source':a['id'],'target':b['id'],'kind':kind,
                       'note':text_field(data.get('note',''),'Relationship note',required=False),'provenance':'user-asserted'})),201

    @bp.post('/items/<item_id>/discover')
    def discover(item_id):
        item=active_item(store,item_id)
        try:
            record=openalex_work(item['doi'])
        except ValueError:
            raise
        except Exception:
            return jsonify(error='OpenAlex is unavailable or this DOI is not indexed. No relationships were added.'),502
        store.put_entity('openalex',{'id':item_id,'record':record,'checkedAt':now()})
        return jsonify(record)

    @bp.post('/items/<item_id>/status')
    def check_status(item_id):
        item=active_item(store,item_id)
        try:
            result=publication_status(item['doi'])
        except ValueError:
            raise
        except Exception:
            previous=store.entity('status',item_id) or {}
            store.put_entity('status',{**previous,'id':item_id,'error':'Status lookup failed; previous results may be stale.','attemptedTimestamp':time.time()})
            return jsonify(error='Crossref status lookup failed. Previous results were retained and marked stale.'),502
        return jsonify(store.put_entity('status',{'id':item_id,**result,'attemptedTimestamp':time.time()}))

    @bp.get('/items/<item_id>/pages/<int:page_number>')
    def page_data(item_id,page_number):
        item=active_item(store,item_id);pages=pages_for(item)
        page=next((p for p in pages if p['page']==page_number),None)
        if not page:
            raise ValueError('Page not found. Reprocess older documents to extract page information.')
        return jsonify(page=page,annotations=[a for a in item['annotations'] if a['page']==page_number],
                       passages=[p for p in passages_for(item) if p['page']==page_number])

    @bp.get('/items/<item_id>/pages/<int:page_number>/image')
    def page_image(item_id,page_number):
        item=active_item(store,item_id)
        path=store.document_path(item)
        if path.suffix.lower()=='.pdf':
            content=render_page(path,page_number)
        elif path.suffix.lower() in ('.png','.jpg','.jpeg','.tif','.tiff','.webp'):
            with Image.open(path) as img:
                try:
                    img.seek(page_number-1)
                except EOFError:
                    raise ValueError('Page not found.')
                buffer=io.BytesIO();ImageOps.exif_transpose(img).convert('RGB').save(buffer,format='PNG');content=buffer.getvalue()
        else:
            raise ValueError('This document has a text view but no page image.')
        return send_file(io.BytesIO(content),mimetype='image/png')

    @bp.post('/items/<item_id>/annotations')
    def anchored_annotation(item_id):
        item=active_item(store,item_id);data=payload();page_number=data.get('page')
        page=next((p for p in pages_for(item) if p['page']==page_number),None)
        if not page:
            raise ValueError('Choose an extracted page.')
        if data.get('pageHash') != (page.get('hash') or fingerprint(page['text'])):
            raise ValueError('The page text changed. Reload the reader before annotating.')
        kind=data.get('kind','highlight');rects=data.get('rects',[])
        if kind not in ('highlight','region','comment') or not isinstance(rects,list) or len(rects)>200:
            raise ValueError('Invalid annotation.')
        rects=[validate_rect(r) for r in rects]
        text=text_field(data.get('text',''),'Excerpt / label',10000,required=kind!='comment')
        comment=text_field(data.get('comment',''),'Comment',10000,required=kind=='comment')
        if kind=='highlight' and text not in page['text']:
            raise ValueError('A text highlight must quote the selected page exactly.')
        if kind=='highlight':
            rects=rects_for_quote(page,text,data.get('start'))
        entry={'id':str(uuid4()),'page':page_number,'pageHash':data['pageHash'],'fileHash':item.get('sha256',''),
               'kind':kind,'text':text,'rects':rects,'comment':comment,'createdAt':now(),
               'anchorStatus':'positioned' if rects else 'text-only'}
        store.update(item_id,lambda current:{'annotations':current['annotations']+[entry]})
        return jsonify(entry),201

    @bp.get('/items/<item_id>/annotated.pdf')
    def export_pdf(item_id):
        item=active_item(store,item_id);path=store.document_path(item)
        if path.suffix.lower()!='.pdf':
            raise ValueError('PDF annotation export requires an original PDF.')
        page_hashes={p['page']:p.get('hash') or fingerprint(p['text']) for p in pages_for(item)}
        if any(a.get('pageHash') and a['pageHash']!=page_hashes.get(a['page']) for a in item['annotations']):
            raise ValueError('Some annotations refer to older extracted text. Review or remove those stale annotations before exporting.')
        return send_file(io.BytesIO(annotated_pdf(path,item['annotations'])),mimetype='application/pdf',
                         as_attachment=True,download_name=Path(item['fileName']).stem+'-annotated.pdf')

    @bp.post('/items/<item_id>/capture')
    def capture(item_id):
        item=active_item(store,item_id);data=payload();rect=validate_rect(data.get('rect'))
        page_number=data.get('page')
        if not isinstance(page_number,int) or page_number<1:
            raise ValueError('Choose a valid page.')
        path=store.document_path(item)
        if path.suffix.lower()!='.pdf':
            raise ValueError('Region capture currently requires a PDF.')
        return send_file(io.BytesIO(render_page(path,page_number,rect)),mimetype='image/png',as_attachment=True,download_name=f'figure-page-{page_number}.png')

    @bp.post('/rules')
    def rule():
        data=payload()
        if data.get('field') not in ('title','authors','journal','text'):
            raise ValueError('Choose a supported rule field.')
        tags=data.get('tags',[]);collections=data.get('collections',[])
        if not isinstance(tags,list) or not isinstance(collections,list) or len(tags)>50:
            raise ValueError('Tags and collections must be lists.')
        tags=[text_field(t,'Tag',100) for t in tags]
        valid={c['id'] for c in store.collections()}
        if any(not isinstance(c,str) or c not in valid for c in collections):
            raise ValueError('Choose an existing collection.')
        return jsonify(store.put_entity('rules',{'field':data['field'],'contains':text_field(data.get('contains'),'Match text',500),
                       'tags':tags,'collections':collections,'enabled':True})),201

    @bp.post('/rules/apply')
    def run_rules():
        count=0
        for item in store.items():
            if not item['trashed'] and apply_rules(store,item):
                count+=1
        return jsonify(matched=count)

    @bp.post('/watchers')
    def add_watcher():
        data=payload();path=Path(text_field(data.get('path'),'Folder path',2000)).expanduser().resolve()
        if not path.is_dir():
            raise ValueError('The folder must exist on the computer running Synopsis.')
        data_root=store.root.resolve()
        if path==data_root or data_root in path.parents:
            raise ValueError('Choose an intake folder outside Synopsis data storage.')
        if any(path==folder or folder in path.parents or path in folder.parents for folder in store.storage_directories()):
            raise ValueError('Choose an intake folder separate from document storage folders.')
        collection=data.get('collection','')
        if collection and collection not in {c['id'] for c in store.collections()}:
            raise ValueError('Choose an existing destination collection.')
        return jsonify(store.put_entity('watchers',{'path':str(path),'collection':collection,'enabled':True,'seen':{},'errors':[]})),201

    @bp.post('/watchers/<watcher_id>/scan')
    def scan(watcher_id):
        return jsonify(watcher.scan(watcher_id))

    @bp.patch('/watchers/<watcher_id>')
    def pause_watcher(watcher_id):
        enabled=payload().get('enabled')
        if not isinstance(enabled,bool):
            raise ValueError('Enabled must be true or false.')
        return jsonify(store.mutate_entity('watchers',watcher_id,lambda w:{'enabled':enabled}))

    @bp.post('/merge')
    def merge():
        data=payload();target=active_item(store,data.get('target'));sources=selected(store,data.get('sources',[]))
        if target.get('mergedInto') or target['id'] in {s['id'] for s in sources} or any(s.get('mergedInto') for s in sources):
            raise ValueError('Choose distinct references that have not already been merged.')
        if any(i['status'] in ('queued','processing') for i in [target]+sources):
            raise ValueError('Wait for processing to finish before merging references.')
        # Keep every source record and original attachment addressable; only hide it from the main list.
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            target=json.loads(db.execute('SELECT data FROM items WHERE id=?',(target['id'],)).fetchone()['data'])
            if target.get('mergedInto') or target['trashed']:
                raise ValueError('The target changed during this merge. Refresh the library and try again.')
            for source in sources:
                source=json.loads(db.execute('SELECT data FROM items WHERE id=?',(source['id'],)).fetchone()['data'])
                if source.get('mergedInto') or source['trashed']:
                    raise ValueError('A source changed during this merge. Refresh the library and try again.')
                target['tags']=list(dict.fromkeys(target['tags']+source['tags']))
                target['collections']=list(dict.fromkeys(target['collections']+source['collections']))
                target['notes'] += [{**n,'sourceItemId':source['id']} for n in source['notes'] if n['id'] not in {n['id'] for n in target['notes']}]
                target['attachments']=list(dict.fromkeys(target.get('attachments',[])+[source['id']]+source.get('attachments',[])))
                source['mergedInto']=target['id'];source['updatedAt']=now()
                db.execute('UPDATE items SET data=? WHERE id=?',(json.dumps(source),source['id']))
            target['updatedAt']=now()
            db.execute('UPDATE items SET data=? WHERE id=?',(json.dumps(target),target['id']))
        return jsonify(summary(target))

    @bp.post('/items/<item_id>/attachments')
    def attach(item_id):
        target=active_item(store,item_id);other=active_item(store,payload().get('attachmentId'))
        if target['id']==other['id'] or not other['fileName']:
            raise ValueError('Choose another reference with a document attachment.')
        # Attachments stay independent immutable sources, including their own notes and geometry.
        store.update(item_id,lambda current:{'attachments':list(dict.fromkeys(current.get('attachments',[])+[other['id']]))})
        return jsonify(ok=True)

    @bp.delete('/items/<item_id>/attachments/<attachment_id>')
    def detach(item_id,attachment_id):
        active_item(store,item_id)
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM items WHERE id=?',(item_id,)).fetchone()
            target=json.loads(row['data'])
            target['attachments']=[a for a in target.get('attachments',[]) if a!=attachment_id]
            db.execute('UPDATE items SET data=? WHERE id=?',(json.dumps(target),item_id))
            row=db.execute('SELECT data FROM items WHERE id=?',(attachment_id,)).fetchone()
            if row:
                attachment=json.loads(row['data'])
                if attachment.get('mergedInto')==item_id:
                    attachment.pop('mergedInto')
                    db.execute('UPDATE items SET data=? WHERE id=?',(json.dumps(attachment),attachment_id))
        return jsonify(ok=True)

    @bp.delete('/records/<kind>/<record_id>')
    def remove_record(kind,record_id):
        if kind not in ('notebooks','matrices','reviews','versions','relations','rules','watchers'):
            raise ValueError('Unsupported research record.')
        store.delete_entity(kind,record_id)
        return jsonify(ok=True)

    app.register_blueprint(bp)
    if app.config.get('START_SERVICES',not app.config.get('TESTING',False)):
        watcher.start()
