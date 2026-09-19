"""Conservative metadata extraction: DOI records, embedded fields, then text hints."""
import re
from pathlib import Path
from urllib.parse import quote
import requests

DOI_RE = re.compile(r'\b10\.\d{4,9}/[^\s<>"\]]+', re.I)


def clean_doi(value):
    match = DOI_RE.search(value or '')
    return match.group(0).rstrip('.,;:)') if match else ''


def from_csl(record):
    date = record.get('issued', {}).get('date-parts', [[]])
    item_type = record.get('type', 'article-journal')
    item_type = {'journal-article': 'article-journal', 'book-chapter': 'chapter',
                 'proceedings-article': 'paper-conference', 'dissertation': 'thesis',
                 'posted-content': 'document', 'monograph': 'book', 'edited-book': 'book'}.get(item_type, item_type)
    if item_type not in {'article-journal', 'book', 'chapter', 'paper-conference', 'thesis', 'report', 'webpage', 'document'}:
        item_type = 'document'
    return dict(title=record.get('title') or 'Untitled reference',
                authors=[a.get('literal') or ', '.join(filter(None, [a.get('family'), a.get('given')]))
                         for a in record.get('author', [])],
                year=str(date[0][0]) if date and date[0] else '',
                journal=record.get('container-title', ''), doi=record.get('DOI', ''),
                url=record.get('URL', ''), abstract=re.sub('<[^>]+>', '', record.get('abstract', '')),
                type=item_type, volume=str(record.get('volume', '')),
                issue=str(record.get('issue', '')), pages=str(record.get('page', '')),
                publisher=record.get('publisher', ''))


def lookup_doi(doi):
    doi = clean_doi(doi)
    if not doi:
        raise ValueError('Enter a valid DOI, such as 10.1038/nature14539.')
    # A fixed host prevents user-provided URLs from becoming arbitrary server requests.
    response = requests.get('https://api.crossref.org/works/' + quote(doi, safe=''), timeout=(5, 15),
                            headers={'User-Agent': 'Synopsis/0.1 (local research library)'})
    if response.status_code == 404:
        raise ValueError('This DOI was not found in Crossref. You can enter its metadata manually.')
    response.raise_for_status()
    r = response.json()['message']
    date = r.get('published') or r.get('issued') or {}
    return from_csl({**r, 'title': (r.get('title') or ['Untitled reference'])[0],
                     'container-title': (r.get('container-title') or [''])[0], 'issued': date})


def infer_metadata(text, filename, embedded=None):
    embedded = embedded or {}
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text[:12000].splitlines() if line.strip()]
    title = embedded.get('title', '').strip()
    if title.lower() in ('untitled', 'document', 'microsoft word', ''):
        title = next((s for s in lines[:20] if 15 <= len(s) <= 250 and
                      not re.match(r'^(https?://|doi\b|arxiv\b|www\.|copyright|©)', s, re.I)), '')
    result = dict(title=title or Path(filename).stem.replace('_', ' '),
                  authors=[a.strip() for a in re.split(r';|\band\b', embedded.get('author', '')) if a.strip()],
                  doi=clean_doi(text[:20000]), year='', abstract='')
    # Explicit labels are stronger evidence than guessing from arbitrary prose.
    author = re.search(r'(?im)^(?:authors?|by)\s*:\s*(.+)$', text[:5000])
    if author and not result['authors']:
        result['authors'] = [a.strip() for a in re.split(r';|\band\b', author.group(1)) if a.strip()]
    year = re.search(r'(?im)^(?:year|published|publication date)\s*:\s*.*?\b((?:19|20)\d{2})\b', text[:5000])
    if year:
        result['year'] = year.group(1)
    abstract = re.search(r'\babstract\b\s*[:.\-]?\s*(.*?)(?=\n\s*(?:keywords|introduction|1\.?\s+introduction)\b|\Z)', text[:12000], re.I | re.S)
    if abstract:
        result['abstract'] = abstract.group(1).strip()[:5000]
    return result
