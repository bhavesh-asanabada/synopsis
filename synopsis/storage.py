"""SQLite persistence. Each update is atomic, including background job progress."""
import json
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.default_uploads = self.root / 'uploads'
        self.default_uploads.mkdir(exist_ok=True)
        self.path = self.root / 'synopsis.sqlite3'
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collections (id TEXT PRIMARY KEY, name TEXT NOT NULL, parent TEXT);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS entities (kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS embeddings (key TEXT PRIMARY KEY, model TEXT NOT NULL, vector TEXT NOT NULL);
            ''')

    @property
    def uploads(self):
        return Path(self.setting('uploadDirectory', '') or self.default_uploads)

    def document_path(self, item):
        # Legacy files stay in the default folder; new files remember their destination.
        filename = item.get('filePath', '')
        if not filename or Path(filename).name != filename or '\\' in filename or filename in ('.', '..'):
            raise ValueError('Invalid document path.')
        return Path(item.get('uploadDirectory') or self.default_uploads) / filename

    def validate_upload_directory(self, value):
        if not isinstance(value, str) or len(value) > 2000 or '\0' in value:
            raise ValueError('Enter a valid upload folder path.')
        path = Path(value.strip()).expanduser() if value.strip() else self.default_uploads
        if not path.is_absolute():
            raise ValueError('Use an absolute folder path, or a path starting with ~.')
        try:
            path = path.resolve()
            for watcher in self.entities('watchers'):
                intake = Path(watcher['path']).resolve()
                if path == intake or intake in path.parents or path in intake.parents:
                    raise ValueError('Choose an upload folder separate from watched intake folders.')
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=path) as probe:
                probe.write(b'Synopsis write check')
                probe.flush()
        except OSError as exc:
            raise ValueError('This folder could not be created or written to. Check the path and permissions.') from exc
        return str(path)

    def storage_directories(self):
        return {self.default_uploads, self.uploads} | {
            self.document_path(item).parent for item in self.items() if item.get('filePath')
        }

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def items(self, query=''):
        with self.connect() as db:
            rows = db.execute('SELECT data FROM items').fetchall()
        items = [json.loads(row['data']) for row in rows]
        if query:
            terms = query.casefold().split()
            def searchable(item):
                return ' '.join(str(item.get(k, '')) for k in (
                    'title', 'authors', 'abstract', 'journal', 'year', 'doi', 'tags', 'notes', 'text', 'annotations'
                )).casefold()
            items = [item for item in items if all(t in searchable(item) for t in terms)]
        return sorted(items, key=lambda i: i['createdAt'], reverse=True)

    def get(self, item_id):
        with self.connect() as db:
            row = db.execute('SELECT data FROM items WHERE id=?', (item_id,)).fetchone()
        return json.loads(row['data']) if row else None

    def create(self, fields):
        item = dict(id=str(uuid4()), title='Untitled reference', authors=[], year='', journal='',
                    doi='', url='', abstract='', type='article-journal', volume='', issue='', pages='',
                    publisher='', tags=[], collections=[], notes=[], annotations=[], starred=False,
                    read=False, trashed=False, status='ready', progress='', text='', fileName='',
                    filePath='', fileSize=0, pageCount=0, source='manual', warnings=[], reviewed=True,
                    createdAt=now(), updatedAt=now())
        item.update(pageTexts=[], provenance={}, tables=[], references=[], attachments=[], versionGroup='',
                    language='', analysis={}, extractionVersion=0)
        item.update(fields)
        with self.connect() as db:
            db.execute('INSERT INTO items VALUES (?, ?)', (item['id'], json.dumps(item)))
        return item

    def update(self, item_id, fields):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM items WHERE id=?', (item_id,)).fetchone()
            if not row:
                return None
            item = json.loads(row['data'])
            changes = fields(item) if callable(fields) else fields
            item.update(changes, updatedAt=now())
            db.execute('UPDATE items SET data=? WHERE id=?', (json.dumps(item), item_id))
        return item

    def delete(self, item_id):
        with self.connect() as db:
            db.execute('DELETE FROM items WHERE id=?', (item_id,))

    def collections(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM collections ORDER BY name COLLATE NOCASE')]

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, json.dumps(value)))

    def entities(self, kind):
        with self.connect() as db:
            return [json.loads(r['data']) for r in db.execute('SELECT data FROM entities WHERE kind=? ORDER BY rowid', (kind,))]

    def entity(self, kind, entity_id):
        with self.connect() as db:
            row = db.execute('SELECT data FROM entities WHERE kind=? AND id=?', (kind, entity_id)).fetchone()
            return json.loads(row['data']) if row else None

    def put_entity(self, kind, fields):
        entity = {'id': str(uuid4()), 'createdAt': now(), **fields, 'updatedAt': now()}
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO entities VALUES (?, ?, ?)', (kind, entity['id'], json.dumps(entity)))
        return entity

    def mutate_entity(self, kind, entity_id, fn):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM entities WHERE kind=? AND id=?', (kind, entity_id)).fetchone()
            if not row:
                raise ValueError('Research record not found.')
            entity = json.loads(row['data'])
            entity.update(fn(entity), updatedAt=now())
            db.execute('UPDATE entities SET data=? WHERE kind=? AND id=?', (json.dumps(entity), kind, entity_id))
        return entity

    def delete_entity(self, kind, entity_id):
        with self.connect() as db:
            db.execute('DELETE FROM entities WHERE kind=? AND id=?', (kind, entity_id))


def summary(item):
    return {k: v for k, v in item.items() if k not in ('text', 'filePath', 'uploadDirectory', 'pageTexts', 'tables', 'references', 'analysis')}
