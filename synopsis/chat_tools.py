"""Optional web retrieval and image generation for chat."""
import base64
import html
import io
import os
import re
from urllib.parse import urlsplit

import requests
from PIL import Image

from .ai import ai_changes, ai_key, public_ai, validate_ai
from .documents import fingerprint
from .storage import now


def public_chat_settings(store):
    return {'imageAI': public_ai(store, 'imageAI'),
            'imageBase64': store.setting('imageBase64', False),
            'webSearch': {'enabled':store.setting('webSearch', {}).get('enabled', False),
                          'hasApiKey':bool(store.setting('webSearchCredential', '') or os.environ.get('SYNOPSIS_WEB_SEARCH_KEY')),
                          'hasSavedApiKey':bool(store.setting('webSearchCredential', ''))}}


def chat_settings_changes(store, data):
    changes = {}
    if 'imageAI' in data:changes.update(ai_changes(store, data['imageAI'], 'imageAI'))
    if 'imageBase64' in data:
        if not isinstance(data['imageBase64'], bool):raise ValueError('Image response preference must be true or false.')
        changes['imageBase64'] = data['imageBase64']
    if 'webSearch' in data:
        web = data['webSearch']
        if not isinstance(web, dict) or not isinstance(web.get('enabled'), bool):raise ValueError('Choose whether web search is enabled.')
        key, clear = web.get('apiKey', ''), web.get('clearApiKey', False)
        if not isinstance(key, str) or len(key)>8192 or any(ord(c)<32 for c in key) or not isinstance(clear,bool) or (clear and key.strip()):
            raise ValueError('Enter a valid web search key, or choose to remove it.')
        changes['webSearch'] = {'enabled':web['enabled']}
        changes['webSearchCredential'] = '' if clear else key.strip() or store.setting('webSearchCredential', '')
    return changes


def search_web(store, query):
    if not store.setting('webSearch', {}).get('enabled'):
        raise ValueError('Enable web search in Settings before using Search web.')
    key = store.setting('webSearchCredential', '') or os.environ.get('SYNOPSIS_WEB_SEARCH_KEY', '')
    if not key:raise ValueError('Add your Brave Search API key in Settings to search the web.')
    try:
        response = requests.get('https://api.search.brave.com/res/v1/web/search',
                                params={'q':query[:2000], 'count':6, 'extra_snippets':'true'},
                                headers={'X-Subscription-Token':key,'Accept':'application/json'},
                                timeout=(10,30), allow_redirects=False)
        response.raise_for_status()
        results = response.json().get('web', {}).get('results', [])
        if not isinstance(results,list):raise ValueError()
    except Exception as exc:
        raise ValueError('Web search failed. Check the search API key and try again.') from exc
    sources = []
    def plain(value):return html.unescape(re.sub(r'<[^>]+>', '', str(value)))
    for result in results[:6]:
        if not isinstance(result,dict):continue
        url = result.get('url', '')
        if not isinstance(url,str):continue
        parsed = urlsplit(url)
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password:continue
        snippets = result.get('extra_snippets', [])
        if not isinstance(snippets,list):snippets=[]
        text = plain('\n'.join(str(v) for v in [result.get('description',''),*snippets[:3]]))[:2500].strip()
        if text:sources.append({'id':'web-'+fingerprint(url+text)[:24], 'kind':'web', 'title':plain(result.get('title', url))[:300],
                                'url':url,'text':text,'retrievedAt':now(),'notice':'Search-result excerpts; full page not fetched.'})
    return sources


def generate_image(store, prompt):
    config = validate_ai(store.setting('imageAI', {'enabled':False,'endpoint':'','model':''}))
    if not config['enabled']:raise ValueError('Configure and enable an image model in Settings to generate images.')
    key = ai_key(store,config,namespace='imageAI')
    if not key and config['endpoint']==store.setting('ai',{}).get('endpoint'):
        key = ai_key(store,config)
    payload = {'model':config['model'], 'prompt':prompt[:24000], 'n':1, 'size':'1024x1024'}
    if store.setting('imageBase64',False):payload['response_format']='b64_json'
    try:
        response = requests.post(config['endpoint']+'/images/generations', json=payload,
                                 headers={'Authorization':'Bearer '+key} if key else {},
                                 timeout=(10,180), allow_redirects=False)
        response.raise_for_status()
        encoded = response.json()['data'][0].get('b64_json')
        if not isinstance(encoded,str) or len(encoded)>16_000_000:
            raise ValueError('Image data unavailable')
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            if image.width*image.height>16_000_000 or image.format not in ('PNG','JPEG','WEBP'):
                raise ValueError('Unsupported image')
            output=io.BytesIO()
            image.convert('RGB').save(output,format='PNG')
        if output.tell()>12_000_000:raise ValueError('Image too large')
    except Exception as exc:
        raise ValueError('Image generation failed. Check the image model, key, and base64 response setting. The provider must return PNG, JPEG, or WebP image data.') from exc
    return config['model'], base64.b64encode(output.getvalue()).decode('ascii')
