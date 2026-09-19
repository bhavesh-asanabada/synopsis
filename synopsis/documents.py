"""Page geometry, OCR confidence, table extraction, and immutable source anchors."""
import hashlib
import io
import re
from threading import RLock

import pymupdf
import pytesseract
from PIL import Image, ImageOps
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 0
PDF_LOCK = RLock()


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


def detect_language(text):
    try:
        return detect(text[:10000]) if len(text.strip()) > 40 else 'und'
    except Exception:
        return 'und'


def inverse_rect(rect, angle):
    x0, y0, x1, y1 = rect
    if angle == 90:
        return [y0, 1-x1, y1, 1-x0]
    if angle == 180:
        return [1-x1, 1-y1, 1-x0, 1-y0]
    if angle == 270:
        return [1-y1, x0, 1-y0, x1]
    return rect


def rects_for_quote(page, quote, start=None):
    """Map an exact excerpt to word boxes; repeated text may specify its offset."""
    text=page['text']
    start=text.find(quote) if start is None else start
    if not isinstance(start,int) or start<0 or text[start:start+len(quote)]!=quote:
        raise ValueError('The quote and its page offset do not match.')
    stop=start+len(quote);cursor=0;rects=[]
    for word in page.get('words',[]):
        at=text.find(word['text'],cursor)
        if at<0:
            continue
        cursor=at+len(word['text'])
        if at<stop and cursor>start:
            r=word['rect']
            if rects and abs(rects[-1][1]-r[1])<.009 and r[0]>=rects[-1][0]:
                previous=rects[-1];rects[-1]=[previous[0],min(previous[1],r[1]),max(previous[2],r[2]),max(previous[3],r[3])]
            else:
                rects.append(r)
    return rects


def ocr_page(image, language='eng'):
    image = ImageOps.exif_transpose(image).convert('RGB')
    image.thumbnail((4000, 4000))
    rotation = 0
    try:
        rotation = int(pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT, timeout=25).get('rotate', 0))
    except (pytesseract.TesseractError, RuntimeError):
        pass
    corrected = image.rotate(-rotation, expand=True) if rotation else image
    data = pytesseract.image_to_data(corrected, lang=language, output_type=pytesseract.Output.DICT, timeout=120)
    words, lines, last_line = [], [], None
    for j, raw in enumerate(data['text']):
        word = raw.strip()
        if not word:
            continue
        line_key = (data['block_num'][j], data['par_num'][j], data['line_num'][j])
        if line_key != last_line:
            lines.append([])
        last_line = line_key
        lines[-1].append(word)
        rect = [data['left'][j]/corrected.width, data['top'][j]/corrected.height,
                (data['left'][j]+data['width'][j])/corrected.width,
                (data['top'][j]+data['height'][j])/corrected.height]
        words.append({'text': word, 'rect': inverse_rect(rect, rotation), 'confidence': max(0, float(data['conf'][j]))/100})
    confidence = sum(w['confidence'] for w in words)/len(words) if words else 0
    return dict(text='\n'.join(' '.join(line) for line in lines), words=words, confidence=round(confidence, 3),
                method='ocr', rotation=rotation, width=image.width, height=image.height)


def pdf_geometry(path):
    pages, tables = [], []
    with PDF_LOCK, pymupdf.open(path) as document:
        if document.needs_pass:
            raise ValueError('This PDF is password-protected. Upload an unlocked copy.')
        for index, page in enumerate(document):
            width, height = page.rect.width, page.rect.height
            words = []
            for w in page.get_text('words', sort=True):
                r = pymupdf.Rect(w[:4]) * page.rotation_matrix
                words.append({'text': w[4], 'rect': [r.x0/width, r.y0/height, r.x1/width, r.y1/height], 'confidence': None})
            pages.append(dict(page=index+1, width=width, height=height, words=words))
            try:
                for table in page.find_tables().tables:
                    tables.append({'page':index+1, 'rows':table.extract(), 'rect':list(table.bbox), 'method':'pdf-table', 'reviewed':False})
            except Exception:
                pass  # Absence of detected table geometry is not a document failure.
    return pages, tables


def render_page(path, number, crop=None):
    with PDF_LOCK, pymupdf.open(path) as document:
        if not 1 <= number <= len(document):
            raise ValueError('Page does not exist.')
        page = document[number-1]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.7, 1.7), alpha=False)
        image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    if crop:
        x0,y0,x1,y1 = crop
        image = image.crop((int(x0*image.width), int(y0*image.height), int(x1*image.width), int(y1*image.height)))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def validate_rect(rect):
    if not isinstance(rect, list) or len(rect) != 4 or any(isinstance(x, bool) or not isinstance(x, (int,float)) for x in rect):
        raise ValueError('A region needs four normalized coordinates.')
    if not (0 <= rect[0] < rect[2] <= 1 and 0 <= rect[1] < rect[3] <= 1):
        raise ValueError('The selected region must lie within the page.')
    return rect


def annotated_pdf(path, annotations):
    with PDF_LOCK, pymupdf.open(path) as document:
        for entry in annotations:
            if not 1 <= entry['page'] <= len(document):
                continue
            page = document[entry['page']-1]
            rects = entry.get('rects', [])
            for r in rects:
                validate_rect(r)
                width, height = page.rect.width, page.rect.height
                rect = pymupdf.Rect(r[0]*width,r[1]*height,r[2]*width,r[3]*height) * page.derotation_matrix
                annotation = page.add_rect_annot(rect) if entry.get('kind') == 'region' else page.add_highlight_annot(rect)
                annotation.set_info(content=entry.get('comment') or entry['text'], title='Synopsis')
                annotation.update()
            if not rects:
                matches = page.search_for(entry['text'], quads=True)
                if matches:
                    annotation = page.add_highlight_annot(matches)
                    annotation.set_info(content=entry.get('comment',''), title='Synopsis')
                    annotation.update()
                else:
                    # Preserve unlocatable legacy excerpts as comments, never pretend to locate them.
                    page.add_text_annot((20,20), 'Unanchored excerpt: '+entry['text'])
        return document.tobytes()


def reference_candidates(text):
    match = re.search(r'(?im)^\s*(?:references|bibliography)\s*$', text)
    if not match:
        return []
    entries = re.split(r'\n(?=\s*(?:\[\d+\]|\d+[.)]))|\n\s*\n', text[match.end():])
    return [{'text': t.strip(), 'reviewed':False} for t in entries if len(t.strip()) > 15][:500]
