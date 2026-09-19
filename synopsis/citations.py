"""Interoperable references and CSL-formatted bibliographies."""
import html
import json
import re
import bibtexparser
import rispy
from citeproc import CitationStylesStyle, CitationStylesBibliography, Citation, CitationItem, formatter
from citeproc.source.json import CiteProcJSON
from citeproc_styles import get_style_filepath
from .metadata import from_csl

STYLES = {'apa': 'APA 7th edition', 'modern-language-association': 'MLA 9th edition',
          'chicago-author-date': 'Chicago author–date', 'vancouver': 'Vancouver'}
TYPES = {'article': 'article-journal', 'book': 'book', 'incollection': 'chapter',
         'inproceedings': 'paper-conference', 'phdthesis': 'thesis', 'misc': 'webpage'}
RIS_TYPES = {'JOUR': 'article-journal', 'BOOK': 'book', 'CHAP': 'chapter', 'CONF': 'paper-conference',
             'THES': 'thesis', 'ELEC': 'webpage', 'RPRT': 'report'}


def to_csl(item, escape_html=False):
    esc = html.escape if escape_html else (lambda value: value)
    authors = []
    for author in item.get('authors', []):
        if ',' in author:
            family, given = author.split(',', 1)
            authors.append({'family': esc(family.strip()), 'given': esc(given.strip())})
        else:
            parts = author.rsplit(' ', 1)
            authors.append({'family': esc(parts[-1]), 'given': esc(parts[0])} if len(parts) == 2 else {'literal': esc(author)})
    result = {'id': item['id'], 'type': item['type'], 'title': esc(item['title'])}
    if authors:
        result['author'] = authors
    # Omit blank fields entirely: citeproc treats an empty string as present, which breaks conditional macros (e.g. "In " before a container title).
    for csl_key, value in (('container-title', item.get('journal', '')), ('DOI', item.get('doi', '')),
                           ('URL', item.get('url', '')), ('abstract', item.get('abstract', '')),
                           ('volume', item.get('volume', '')), ('issue', item.get('issue', '')),
                           ('page', item.get('pages', '')), ('publisher', item.get('publisher', ''))):
        if value:
            result[csl_key] = esc(value)
    if re.fullmatch(r'\d{4}', item.get('year', '')):
        result['issued'] = {'date-parts': [[int(item['year'])]]}
    return result


def bibliography(items, style):
    if style not in STYLES:
        raise ValueError('Choose a supported citation style.')
    # Fields are HTML-escaped beforehand so citeproc's own italic/bold markup can be trusted as-is.
    source = CiteProcJSON([to_csl(i, escape_html=True) for i in items])
    csl = CitationStylesStyle(get_style_filepath('vancouver-nlm' if style == 'vancouver' else style), validate=False)
    result = CitationStylesBibliography(csl, source, formatter.html)
    for item in items:
        result.register(Citation([CitationItem(item['id'])]))
    result.sort()
    entries = [str(entry) for entry in result.bibliography()]
    if style == 'vancouver':
        # citeproc-py does not implement second-field-align hanging indents, so numbered entries
        # otherwise run the number straight into the text (e.g. "1.Smith").
        entries = [re.sub(r'^(\d+)\.(?=\S)', r'\1. ', entry) for entry in entries]
    plain = '\n\n'.join(html.unescape(re.sub(r'<[^>]+>', '', entry)) for entry in entries)
    # The style itself dictates hanging indent, line spacing and spacing between entries (e.g. APA
    # is double-spaced with a hanging indent); citeproc-py only renders the text, so the HTML clipboard
    # copy needs these applied explicitly or every entry collapses onto one squashed, unindented line.
    bib_options = csl.root.bibliography
    entry_style = 'margin:0;padding-left:2em;text-indent:-2em;' if bib_options.get_option('hanging-indent') else 'margin:0;'
    entry_spacing = bib_options.get_option('entry-spacing') or 0
    entry_style += f'margin-bottom:{entry_spacing}em;'
    divs = ''.join(f'<div style="{entry_style}">{entry}</div>' for entry in entries)
    formatted = f'<div style="line-height:{bib_options.get_option("line-spacing") or 1};">{divs}</div>'
    return formatted, plain


def export_references(items, format_name):
    if format_name == 'csl':
        return json.dumps([to_csl(i) for i in items], indent=2, ensure_ascii=False), 'json'
    if format_name == 'bibtex':
        db = bibtexparser.bibdatabase.BibDatabase()
        reverse = {v: k for k, v in TYPES.items()}
        db.entries = [dict(ENTRYTYPE=reverse.get(i['type'], 'misc'), ID='synopsis_' + i['id'].replace('-', ''),
                           title=i['title'], author=' and '.join(i['authors']), year=i['year'],
                           journal=i['journal'], doi=i['doi'], url=i['url'], abstract=i['abstract'],
                           volume=i['volume'], number=i['issue'], pages=i['pages'], publisher=i['publisher']) for i in items]
        return bibtexparser.dumps(db), 'bib'
    if format_name == 'ris':
        reverse = {v: k for k, v in RIS_TYPES.items()}
        return rispy.dumps([dict(type_of_reference=reverse.get(i['type'], 'GEN'), title=i['title'],
                                 authors=i['authors'], year=i['year'], secondary_title=i['journal'],
                                 doi=i['doi'], urls=[i['url']] if i['url'] else [], abstract=i['abstract'], volume=i['volume'],
                                 number=i['issue'], start_page=i['pages'], publisher=i['publisher']) for i in items]), 'ris'
    raise ValueError('Choose BibTeX, RIS, or CSL-JSON.')


def import_references(text, suffix):
    if suffix in ('.bib', '.bibtex'):
        entries = bibtexparser.loads(text).entries
        result = [dict(title=e.get('title', 'Untitled reference'), authors=e.get('author', '').split(' and ') if e.get('author') else [],
                       type=TYPES.get(e.get('ENTRYTYPE'), 'article-journal'), year=e.get('year', ''),
                       journal=e.get('journal', e.get('booktitle', '')), doi=e.get('doi', ''), url=e.get('url', ''),
                       abstract=e.get('abstract', ''), volume=e.get('volume', ''), issue=e.get('number', ''),
                       pages=e.get('pages', ''), publisher=e.get('publisher', '')) for e in entries]
    elif suffix == '.ris':
        entries = rispy.loads(text)
        result = [dict(title=e.get('title', e.get('primary_title', 'Untitled reference')), authors=e.get('authors', []),
                       type=RIS_TYPES.get(e.get('type_of_reference'), 'article-journal'), year=e.get('year', '')[:4],
                       journal=e.get('secondary_title', e.get('journal_name', '')), doi=e.get('doi', ''), url=(e.get('urls') or [''])[0],
                       abstract=e.get('abstract', ''), volume=e.get('volume', ''), issue=e.get('number', ''),
                       pages='-'.join(filter(None, [e.get('start_page', ''), e.get('end_page', '')])), publisher=e.get('publisher', '')) for e in entries]
    elif suffix == '.json':
        entries = json.loads(text)
        if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
            raise ValueError('CSL-JSON must contain an array of reference objects.')
        result = [from_csl(e) for e in entries]
    else:
        raise ValueError('Import a .bib, .ris, or CSL .json file.')
    if not result:
        raise ValueError('No references were found in this file.')
    if len(result) > 5000:
        raise ValueError('Import up to 5,000 references at a time.')
    return result
