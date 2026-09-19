"""Research workflows with append-only decisions and explicit source relationships."""
import difflib
import re
from uuid import uuid4
from .storage import now
from .intelligence import passages_for, validate_source


def text_field(value, name='Value', maximum=10000, required=True):
    if not isinstance(value,str) or len(value)>maximum or (required and not value.strip()):
        raise ValueError(f'{name} must be text between {1 if required else 0} and {maximum} characters.')
    return value.strip()


def active_item(store, item_id):
    item=store.get(item_id) if isinstance(item_id,str) else None
    if not item or item['trashed']:
        raise ValueError('Choose a document that is in your active library.')
    return item


def selected(store, ids, limit=100):
    if not isinstance(ids,list) or not 1<=len(ids)<=limit or any(not isinstance(i,str) for i in ids):
        raise ValueError(f'Select between 1 and {limit} documents.')
    return [active_item(store,i) for i in dict.fromkeys(ids)]


def review_state(review, item_id, stage):
    events=[e for e in review['decisions'] if e['itemId']==item_id and e['stage']==stage]
    if stage=='fulltext':
        abstract=review_state(review,item_id,'abstract')
        if abstract['status']!='include':
            return {'status':'blocked','decisions':[], 'basis':''}
        basis=abstract['basis']
        events=[e for e in events if e.get('basis')==basis]
    latest={}
    adjudication=None
    for event in events:
        if event.get('adjudication'):
            adjudication=event
        else:
            latest[event['reviewer']]=event
            adjudication=None  # A changed vote invalidates a previous adjudication.
    votes=list(latest.values())
    basis='|'.join(e['id'] for e in votes)
    if adjudication:
        return {'status':adjudication['decision'],'decisions':votes,'basis':basis+'|'+adjudication['id'],'resolution':adjudication}
    if len({e['decision'] for e in votes})>1:
        return {'status':'conflict','decisions':votes,'basis':basis}
    if len(votes)<len(review['reviewers']):
        return {'status':'pending','decisions':votes,'basis':basis}
    return {'status':votes[0]['decision'] if votes else 'pending','decisions':votes,'basis':basis}


def review_report(review):
    results=[]
    counts={'identified':len(review['items']),'abstractIncluded':0,'abstractExcluded':0,'fulltextIncluded':0,'fulltextExcluded':0,'conflicts':0,'pending':0}
    for item_id in review['items']:
        a=review_state(review,item_id,'abstract'); f=review_state(review,item_id,'fulltext')
        results.append({'itemId':item_id,'abstract':a,'fulltext':f})
        if a['status'] in ('include','exclude'):
            counts['abstractIncluded' if a['status']=='include' else 'abstractExcluded']+=1
        if f['status'] in ('include','exclude'):
            counts['fulltextIncluded' if f['status']=='include' else 'fulltextExcluded']+=1
        if 'conflict' in (a['status'],f['status']):
            counts['conflicts']+=1
        elif a['status']=='pending' or (a['status']=='include' and f['status']=='pending'):
            counts['pending']+=1
    return {**review,'results':results,'counts':counts}


def record_decision(store, review_id, payload):
    item_id=payload.get('itemId');stage=payload.get('stage');decision=payload.get('decision');reviewer=payload.get('reviewer')
    reason=text_field(payload.get('reason',''),'Reason',required=False)
    adjudicate=payload.get('adjudication',False)
    if not isinstance(adjudicate,bool) or stage not in ('abstract','fulltext') or decision not in ('include','exclude'):
        raise ValueError('Choose a valid review stage and decision.')
    if decision=='exclude' and not reason:
        raise ValueError('Exclusion decisions need a reason.')
    def change(review):
        if item_id not in review['items'] or reviewer not in review['reviewers']:
            raise ValueError('Choose a document and reviewer assigned to this review.')
        current=review_state(review,item_id,stage)
        if current['status']=='blocked':
            raise ValueError('Complete abstract screening with an include decision before full-text screening.')
        if adjudicate and (current['status']!='conflict' or not reason):
            raise ValueError('Adjudication requires a conflict and a documented reason.')
        event={'id':str(uuid4()),'itemId':item_id,'stage':stage,'decision':decision,'reviewer':reviewer,'reason':reason,
               'at':now(),'adjudication':adjudicate,'basis':review_state(review,item_id,'abstract')['basis'] if stage=='fulltext' else ''}
        return {'decisions':review['decisions']+[event]}
    return review_report(store.mutate_entity('reviews',review_id,change))


def document_diff(left,right):
    a=left.get('text','').splitlines(); b=right.get('text','').splitlines()
    changes=[]
    for tag,i,j,k,l in difflib.SequenceMatcher(a=a,b=b,autojunk=False).get_opcodes():
        if tag!='equal':
            changes.append({'kind':tag,'before':'\n'.join(a[i:j]),'after':'\n'.join(b[k:l]),'leftLine':i+1,'rightLine':k+1})
    return {'left':left['id'],'right':right['id'],'changes':changes,'annotationsRemainOnOriginal':True}


def local_graph(store):
    items=[i for i in store.items() if not i['trashed']]
    nodes=[{'id':i['id'],'label':i['title'],'kind':'paper'} for i in items]
    edges=[];seen=set()
    by_doi={i['doi'].casefold():i['id'] for i in items if i['doi']}
    for item in items:
        for name in item['authors']:
            aid='author:'+name.casefold()
            if aid not in seen:
                nodes.append({'id':aid,'label':name,'kind':'author'});seen.add(aid)
            edges.append({'source':aid,'target':item['id'],'kind':'authored','provenance':'library-metadata'})
        for tag in item['tags']:
            tid='topic:'+tag.casefold()
            if tid not in seen:
                nodes.append({'id':tid,'label':tag,'kind':'topic'});seen.add(tid)
            edges.append({'source':item['id'],'target':tid,'kind':'tagged','provenance':'user-tag'})
        for ref in item.get('references',[]):
            for doi,target in by_doi.items():
                if target!=item['id'] and doi in ref['text'].casefold():
                    edges.append({'source':item['id'],'target':target,'kind':'citation-candidate','provenance':'extracted-reference-needs-review'})
    active_ids={i['id'] for i in items}
    for entity in store.entities('relations'):
        if entity['source'] in active_ids and entity['target'] in active_ids:
            edges.append(entity)
    for entity in store.entities('openalex'):
        if entity['id'] not in active_ids:
            continue
        record=entity['record']
        for work in record.get('referenced_works',[])[:100]:
            if work not in seen:
                nodes.append({'id':work,'label':work.rsplit('/',1)[-1],'kind':'external-paper'});seen.add(work)
            edges.append({'source':entity['id'],'target':work,'kind':'cites','provenance':'openalex'})
    return {'nodes':nodes,'edges':edges}
