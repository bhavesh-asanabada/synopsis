"""Shared AI configuration for workspace settings and research requests."""
import json
import os
from urllib.parse import urlsplit

import requests


def validate_ai(config):
    if not isinstance(config, dict) or not isinstance(config.get('enabled'), bool):
        raise ValueError('Choose whether AI is enabled.')
    result = {'enabled': config['enabled']}
    for field, label, limit in [('endpoint', 'API base URL', 2000), ('model', 'Model', 200)]:
        value = config.get(field, '')
        if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError(f'Enter a valid {label}.')
        value = value.strip()
        if result['enabled'] and not value:
            raise ValueError(f'{label} is required when AI is enabled.')
        result[field] = value.rstrip('/') if field == 'endpoint' else value
    if result['endpoint']:
        url = urlsplit(result['endpoint'])
        if not url.hostname or url.username or url.password or url.query or url.fragment or url.scheme not in ('http', 'https'):
            raise ValueError('Use an API base URL without credentials, query parameters, or fragments.')
        if url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('External APIs require HTTPS.')
    return result


def ai_changes(store, submitted, namespace='ai'):
    config = validate_ai(submitted)
    secret = submitted.get('apiKey', '')
    if not isinstance(secret, str) or len(secret) > 8192 or any(ord(c) < 32 for c in secret):
        raise ValueError('Enter a valid API key.')
    secret = secret.strip()
    clear = submitted.get('clearApiKey', False)
    if not isinstance(clear, bool) or (clear and secret):
        raise ValueError('Choose either to replace or remove the saved API key.')
    previous = store.setting(namespace + 'Credential', {})
    credential = previous if previous.get('endpoint') == config['endpoint'] else {}
    if clear:
        credential = {}
    elif secret:
        if not config['endpoint']:
            raise ValueError('Enter an API base URL before saving its key.')
        credential = {'endpoint': config['endpoint'], 'key': secret}
    return {namespace: config, namespace + 'Credential': credential}


def ai_key(store, config, credential=None, namespace='ai'):
    saved = store.setting(namespace + 'Credential', {}) if credential is None else credential
    if saved.get('endpoint') == config.get('endpoint') and saved.get('key'):
        return saved['key']
    return os.environ.get('SYNOPSIS_AI_API_KEY' if namespace == 'ai' else 'SYNOPSIS_IMAGE_API_KEY', '')


def public_ai(store, namespace='ai'):
    config = validate_ai(store.setting(namespace, {'enabled': False, 'endpoint': '', 'model': ''}))
    saved = store.setting(namespace + 'Credential', {})
    has_saved = bool(saved.get('key') and saved.get('endpoint') == config['endpoint'])
    environment = bool(os.environ.get('SYNOPSIS_AI_API_KEY' if namespace == 'ai' else 'SYNOPSIS_IMAGE_API_KEY'))
    return {**config, 'hasApiKey': has_saved or environment, 'hasSavedApiKey': has_saved,
            'keySource': 'saved' if has_saved else 'environment' if environment else 'none'}


def complete(config, key, messages):
    payload = {'model': config['model'], 'messages': messages, 'response_format': {'type': 'json_object'}}
    headers = {'Authorization': 'Bearer ' + key} if key else {}
    try:
        response = requests.post(config['endpoint'] + '/chat/completions', json=payload,
                                 headers=headers, timeout=(10, 90), allow_redirects=False)
        response.raise_for_status()
        return json.loads(response.json()['choices'][0]['message']['content'])
    except Exception as exc:
        raise ValueError('The AI provider failed or returned invalid JSON. Check the API URL, model, and key. No generated claims were saved.') from exc


def test_model(store, submitted):
    changes = ai_changes(store, submitted)
    config = changes['ai']
    if not config['endpoint'] or not config['model']:
        raise ValueError('Enter an API base URL and model to test.')
    result = complete(config, ai_key(store, config, changes['aiCredential']), [
        {'role': 'system', 'content': 'This is a connection test. Return JSON only: {"ok": true}.'},
        {'role': 'user', 'content': 'Confirm you can return the requested JSON object.'},
    ])
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise ValueError('The model responded but did not pass the JSON output test. Choose a model that supports JSON responses.')
    return {'ok': True, 'model': config['model'], 'message': 'Model connection succeeded. Save preferences to apply this configuration.'}
