"""Offline backup recovery. Restores into a new directory without overwriting a library."""
import argparse
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from synopsis.storage import Store


def restore_backup(backup, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Choose a new directory. Existing libraries are never overwritten.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.synopsis-restore-', dir=destination.parent))
    try:
        with zipfile.ZipFile(backup) as archive:
            payload = json.loads(archive.read('library.json'))
            if payload.get('version') not in (1, 2) or not isinstance(payload.get('items'), list) or not isinstance(payload.get('collections'), list):
                raise ValueError('Unsupported or invalid Synopsis backup.')
            store = Store(staging)
            with store.connect() as db:
                for collection in payload['collections']:
                    db.execute('INSERT INTO collections VALUES (?, ?, ?)',
                               (collection['id'], collection['name'], collection.get('parent')))
            for item in payload['items']:
                # Restored documents always belong to the new library's uploads folder.
                item.pop('uploadDirectory', None)
                if item.get('cloudStorage', {}).get('status') in ('queued', 'uploading', 'error'):
                    item['cloudStorage'].update(status='paused', error='Restored backup. Connect a cloud account and use Save to cloud to resume.')
                filename = item.get('filePath', '')
                if filename:
                    if Path(filename).name != filename or '\\' in filename or filename in ('.', '..'):
                        raise ValueError('Invalid attachment path in backup.')
                    with archive.open('uploads/' + filename) as source, (store.uploads / filename).open('wb') as target:
                        shutil.copyfileobj(source, target)
                store.create(item)
            for key in ('metadataLookup', 'ocrLanguage'):
                if key in payload.get('settings', {}):
                    store.set_setting(key, payload['settings'][key])
            for entity in payload.get('entities',[]):
                fields=entity['data']
                if entity['kind']=='watchers':
                    fields={**fields,'enabled':False}
                store.put_entity(entity['kind'],fields)
            if 'ai' in payload.get('settings',{}):
                store.set_setting('ai',{**payload['settings']['ai'],'enabled':False})
            for key in ('imageAI','webSearch'):
                if key in payload.get('settings',{}):
                    store.set_setting(key,{**payload['settings'][key],'enabled':False})
            store.set_setting('imageBase64',payload.get('settings',{}).get('imageBase64',False))
        staging.rename(destination)
        return len(payload['items'])
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['restore'])
    parser.add_argument('backup', type=Path)
    parser.add_argument('--data-dir', type=Path, required=True, help='A new, nonexistent directory for the recovered library')
    args = parser.parse_args()
    try:
        count = restore_backup(args.backup, args.data_dir)
        print(f'Restored {count} references to {args.data_dir.resolve()}')
        print('Start Synopsis with SYNOPSIS_DATA_DIR pointing to this directory.')
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, f'Restore failed: {exc}\n')
