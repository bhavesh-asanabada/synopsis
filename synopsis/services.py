"""Optional external metadata and explicitly configured local-folder intake."""
import hashlib
import os
import shutil
import time
from pathlib import Path
from threading import Event, Thread, Lock
from urllib.parse import quote
from uuid import uuid4

import requests
from .metadata import clean_doi
from .storage import now
from .processing import ALLOWED


def get_json(url, **kwargs):
    response=requests.get(url,timeout=(5,20),**kwargs)
    response.raise_for_status()
    return response.json()


def publication_status(doi):
    doi=clean_doi(doi)
    if not doi:
        raise ValueError('A DOI is required to check publication status.')
    result=get_json('https://api.crossref.org/works',params={'filter':'updates:'+doi,'rows':100})
    updates=[]
    for record in result['message']['items']:
        for update in record.get('update-to',[]):
            if clean_doi(update.get('DOI','')).casefold()==doi.casefold():
                updates.append({'doi':record.get('DOI',''),'title':(record.get('title') or ['Publication update'])[0],
                                'type':update.get('type','update'),'source':update.get('source','publisher'),
                                'date':update.get('updated',{}).get('date-time','')})
    return {'doi':doi,'checkedAt':now(),'updates':updates,'status':'updates-reported' if updates else 'no-updates-reported',
            'notice':'No reported updates is not a guarantee that a publication is unaffected. Coverage depends on registered metadata.',
            'truncated':result['message'].get('total-results',0)>100}


def openalex_work(doi):
    doi=clean_doi(doi)
    if not doi:
        raise ValueError('A DOI is required for citation discovery.')
    key=os.environ.get('SYNOPSIS_OPENALEX_KEY','')
    headers={'Authorization':'Bearer '+key} if key else {}
    return get_json('https://api.openalex.org/works/https://doi.org/'+quote(doi,safe=''),headers=headers)


def apply_rules(store, item):
    tags=set(item['tags']); collections=set(item['collections']); matched=[]
    valid_collections={c['id'] for c in store.collections()}
    for rule in store.entities('rules'):
        if not rule.get('enabled',True):
            continue
        field=rule['field']
        text=' '.join(item['authors']) if field=='authors' else str(item.get(field,''))
        if rule['contains'].casefold() in text.casefold():
            tags.update(rule.get('tags',[]));collections.update(set(rule.get('collections',[])) & valid_collections);matched.append(rule['id'])
    if matched:
        store.update(item['id'],lambda current:{'tags':sorted(set(current['tags'])|tags),'collections':sorted(set(current['collections'])|collections),'rulesApplied':matched})
    return matched


def import_local_file(store, processor, path, collection=''):
    if path.suffix.lower() not in ALLOWED or path.is_symlink() or not path.is_file():
        raise ValueError('Unsupported file.')
    if path.stat().st_size>100*1024*1024:
        raise ValueError('Watched documents must be under 100 MB.')
    if path.stat().st_size==0:
        raise ValueError('Empty file.')
    before=path.stat()
    name=str(uuid4())+path.suffix.lower()
    copied=store.uploads/name
    shutil.copyfile(path,copied)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        copied.unlink(missing_ok=True)
        raise ValueError('The file changed while being copied. It will be retried on the next scan.')
    digest=hashlib.sha256()
    with copied.open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):
            digest.update(chunk)
    hash_value=digest.hexdigest()
    duplicate=next((i for i in store.items() if i.get('sha256')==hash_value and not i['trashed']),None)
    if duplicate:
        copied.unlink(missing_ok=True)
        return {'id':duplicate['id'],'duplicate':True}
    item=store.create({'title':path.stem,'fileName':path.name,'filePath':name,'uploadDirectory':str(copied.parent),'fileSize':path.stat().st_size,
                       'sha256':hash_value,'collections':[collection] if collection else [],'status':'queued','reviewed':False,'source':'watched-folder'})
    processor.submit(item['id'])
    return {'id':item['id'],'duplicate':False}


class WatchService:
    def __init__(self, store, processor):
        self.store=store;self.processor=processor;self.stop_event=Event();self.lock=Lock()
        self.thread=None

    def scan(self, watcher_id):
        with self.lock:
            watcher=self.store.entity('watchers',watcher_id)
            if not watcher:
                raise ValueError('Watched folder not found.')
            root=Path(watcher['path'])
            if not root.is_dir():
                raise ValueError('The watched folder is unavailable.')
            known=dict(watcher.get('seen',{}));results=[];errors=[]
            valid_collections={c['id'] for c in self.store.collections()}
            collection=watcher.get('collection','')
            if collection and collection not in valid_collections:
                raise ValueError('The destination collection was removed. Edit or recreate this watcher.')
            for path in sorted(root.iterdir()):
                if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ALLOWED:
                    continue
                stat=path.stat();stamp=f'{stat.st_size}:{stat.st_mtime_ns}'
                if known.get(path.name)==stamp or time.time()-stat.st_mtime<2:
                    continue
                try:
                    results.append(import_local_file(self.store,self.processor,path,collection));known[path.name]=stamp
                except Exception as exc:
                    errors.append({'file':path.name,'error':str(exc)[:200]})
            self.store.mutate_entity('watchers',watcher_id,lambda current:{'seen':known,'lastScan':now(),'errors':errors})
            return {'files':results,'errors':errors}

    def run(self):
        while not self.stop_event.wait(30):
            for watcher in self.store.entities('watchers'):
                if watcher.get('enabled',True):
                    try:
                        self.scan(watcher['id'])
                    except Exception as exc:
                        try:
                            self.store.mutate_entity('watchers',watcher['id'],lambda current:{'errors':[{'error':str(exc)[:200]}]})
                        except ValueError:
                            pass  # A user may remove a watcher while its scan is finishing.
            if self.store.setting('automaticStatusChecks',False):
                for item in self.store.items():
                    if item['trashed'] or not item['doi']:
                        continue
                    previous=self.store.entity('status',item['id'])
                    if previous and (time.time()-previous.get('attemptedTimestamp',0))<86400:
                        continue
                    try:
                        self.store.put_entity('status',{'id':item['id'],**publication_status(item['doi']),'attemptedTimestamp':time.time()})
                    except Exception:
                        self.store.put_entity('status',{**(previous or {}),'id':item['id'],'error':'Status service unavailable; previous results may be stale.','attemptedTimestamp':time.time()})

    def start(self):
        self.thread=Thread(target=self.run,name='synopsis-watch',daemon=True);self.thread.start()

    def close(self):
        self.stop_event.set()
