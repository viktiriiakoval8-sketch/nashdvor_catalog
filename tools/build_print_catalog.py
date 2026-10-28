#!/usr/bin/env python3
"""Печатный каталог A4 из единственного источника данных index.html.
Запуск: python3 tools/build_print_catalog.py
Требуются reportlab, шрифты Noto Sans (или DejaVu Sans); сеть не используется.
PNG не изменяются: прозрачные поля ограничиваются только при размещении в PDF.
"""
from pathlib import Path
import base64, io, json, math, re
from html import escape
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / 'index.html').read_text()
start = text.index('const CATALOG = ') + len('const CATALOG = ')
end = text.index(';\nconst $=', start)
CATALOG = json.loads(text[start:end])
OUT = ROOT / 'print'
OUT.mkdir(exist_ok=True)
PDF = OUT / 'nash-dvor-catalog.pdf'
MM = 72 / 25.4
W, H = 210 * MM, 297 * MM
M = 14 * MM
CW = W - 2 * M
ORANGE = colors.HexColor(CATALOG['brand']['accent'])
INK = colors.HexColor(CATALOG['brand']['ink'])
PAPER = colors.HexColor(CATALOG['brand']['background'])
MUTED = colors.HexColor('#64615c')
LINE = colors.HexColor('#dcd8d0')
WHITE = colors.white
for face, filename in [('Body', 'NotoSans-Regular.ttf'), ('Bold', 'NotoSans-Bold.ttf')]:
    path = Path('/usr/share/fonts/truetype/noto') / filename
    if not path.exists():
        path = Path('/usr/share/fonts/truetype/dejavu') / ('DejaVuSans-Bold.ttf' if face == 'Bold' else 'DejaVuSans.ttf')
    pdfmetrics.registerFont(TTFont(face, str(path)))
pdfmetrics.registerFontFamily('Body', normal='Body', bold='Bold', italic='Body', boldItalic='Bold')
C = canvas.Canvas(str(PDF), pagesize=(W, H), pageCompression=1)
C.setTitle('NASH DVOR — Каталог фасадних термопанелей')
C.setAuthor('NASH DVOR · Центр благоустрою')
C.setSubject('58 панелей, 4 розділи. Основи, товщини та ціни з одиницями виміру.')
C.setCreator('NASH DVOR print catalog builder')
C.setViewerPreference('DisplayDocTitle', 'true')
IMAGES = {}
MANIFEST = {'pages': [], 'products': [], 'photoCounts': {'embedded': 0, 'onlineQR': 0, 'missing': 0}}


def rgb(color):
    C.setFillColor(color)


def label(txt, x, y, size=8, color=INK, bold=False):
    rgb(color)
    C.setFont('Bold' if bold else 'Body', size)
    C.drawString(x, y, str(txt))


def right(txt, x, y, size=8, color=INK, bold=False):
    rgb(color)
    C.setFont('Bold' if bold else 'Body', size)
    C.drawRightString(x, y, str(txt))


def para(txt, x, top, width, size=9, color=INK, bold=False, leading=None, maxh=None):
    style = ParagraphStyle('p', fontName='Bold' if bold else 'Body', fontSize=size,
                           leading=leading or size * 1.38, textColor=color, spaceAfter=0)
    p = Paragraph(txt, style)
    _, h = p.wrap(width, H)
    if maxh is not None and h > maxh + 0.1:
        raise ValueError(f'Text overflow ({h:.1f}>{maxh:.1f}): {txt[:80]}')
    p.drawOn(C, x, top - h)
    return h


def line(x1, y, x2, color=LINE, width=.55):
    C.setStrokeColor(color)
    C.setLineWidth(width)
    C.line(x1, y, x2, y)


def image_reader(data):
    if data not in IMAGES:
        IMAGES[data] = ImageReader(io.BytesIO(base64.b64decode(data.split(',', 1)[1])))
    return IMAGES[data]


def image_crop(data, box, crop):
    """Отображение неизменённого PNG через окно — как SVG viewBox в веб-каталоге."""
    x, y, w, h = box
    left, top, cw, ch = crop
    im = image_reader(data)
    iw, ih = im.getSize()
    scale = min(w / cw, h / ch)
    dx, dy = x + (w - cw * scale) / 2, y + (h - ch * scale) / 2
    C.saveState()
    path = C.beginPath()
    path.rect(x, y, w, h)
    C.clipPath(path, stroke=0, fill=0)
    C.drawImage(im, dx - left * scale, dy - (ih - top - ch) * scale,
                width=iw * scale, height=ih * scale, mask='auto')
    C.restoreState()


def brand(x, y, width):
    height = width * 440 / 2030
    scale = width / 2030
    image_crop(CATALOG['brand']['symbol'], (x, y, 275 * scale, height), (340, 150, 660, 1040))
    image_crop(CATALOG['brand']['wordmark'], (x + 330 * scale, y, 1700 * scale, height), (250, 160, 1700, 440))


def sign(x, y, height):
    image_crop(CATALOG['brand']['symbol'], (x, y, height * 660 / 1040, height), (340, 150, 660, 1040))


def page_start(kind, title):
    C.setPageSize((W, H))
    C.setFillColor(PAPER if kind in ['cover', 'back'] else WHITE)
    C.rect(0, 0, W, H, fill=1, stroke=0)
    MANIFEST['pages'].append({'page': C.getPageNumber(), 'kind': kind, 'title': title})


def footer(section='КАТАЛОГ ТЕРМОПАНЕЛЕЙ'):
    line(M, 17 * MM, W - M)
    label('NASH DVOR  /  ' + section, M, 11 * MM, 6.8, MUTED)
    right(f'{C.getPageNumber():02d}', W - M, 11 * MM, 8, INK, True)


def page_end():
    C.showPage()


def qr(url, x, y, side):
    widget = QrCodeWidget(url, barLevel='M', barBorder=3)
    bx, by, rx, ry = widget.getBounds()
    drawing = Drawing(side, side, transform=[side / (rx - bx), 0, 0, side / (ry - by), 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, C, x, y)
    C.linkURL(url, (x, y, x + side, y + side), relative=0)


def photo(i, x, y, w, h):
    rgb(PAPER)
    C.roundRect(x, y, w, h, 2 * MM, fill=1, stroke=0)
    src = i.get('image', '')
    if src.startswith('data:image/'):
        im = image_reader(src)
        C.drawImage(im, x, y, w, h, preserveAspectRatio=True, anchor='c', mask='auto')
        MANIFEST['photoCounts']['embedded'] += 1
    elif src.startswith('https://') and i.get('source'):
        side = min(h - 8 * MM, 29 * MM)
        qr(i['source'], x + (w - side) / 2, y + (h - side) / 2 + 2 * MM, side)
        label('ФОТО НА САЙТІ', x + 5 * MM, y + 3 * MM, 6.2, MUTED, True)
        MANIFEST['photoCounts']['onlineQR'] += 1
    else:
        sign(x + w / 2 - 4 * MM, y + h / 2 - 4 * MM, 12 * MM)
        label('ФОТО УТОЧНЮЙТЕ', x + 3.3 * MM, y + 4 * MM, 6.2, MUTED, True)
        MANIFEST['photoCounts']['missing'] += 1


def format_price(value):
    whole, fraction = f'{value:.2f}'.split('.')
    return f'{int(whole):,}'.replace(',', ' ') + (',' + fraction if fraction != '00' else '')


def price_table(i, x, top, width):
    ts = i['thicknesses']
    bases = i['bases']
    stub = 28 * MM if len(ts) <= 6 else 24 * MM
    col = (width - stub) / len(ts)
    rowh = (6.5 if len(bases) >= 3 else 8) * MM
    rgb(PAPER)
    C.rect(x, top - rowh, width, rowh, fill=1, stroke=0)
    label('Основа / мм', x + 2 * MM, top - 5.2 * MM, 6.7, MUTED, True)
    for k, t in enumerate(ts):
        header = 'Без утепл.' if t['mm'] == 0 else str(t['mm'])
        label(header, x + stub + k * col + 1.2 * MM, top - 5.2 * MM, 6 if t['mm'] == 0 else 7, INK, True)
    for bi, base in enumerate(bases):
        y = top - (bi + 1) * rowh
        if base['id'] == 'mesh':
            title = 'Скловолоконна<br/>сітка'
            para(title, x + 2 * MM, y - 1 * MM, stub - 3 * MM, 6.4, MUTED, leading=7.1, maxh=rowh)
        else:
            label(base['name'], x + 2 * MM, y - 5.2 * MM, 6.9, INK, True)
        for ti, t in enumerate(ts):
            key = f"{base['id']}_{t['mm']}"
            price = i.get('price', {}).get(key)
            if key not in i.get('combinations', list(i.get('price', {}))):
                value, color = '—', MUTED
            elif isinstance(price, (int, float)):
                value, color = format_price(price), INK
            else:
                value, color = '—', MUTED
            label(value, x + stub + ti * col + 1.2 * MM, y - 5.2 * MM,
                  7 if len(ts) >= 9 else 7.5, color, isinstance(price, (int, float)))
        line(x, y - rowh, x + width)
    return rowh * (len(bases) + 1)


# Обложка.
page_start('cover', 'Каталог фасадних термопанелей')
brand(M, H - 38 * MM, 92 * MM)
right('ЦЕНТР БЛАГОУСТРОЮ', W - M, H - 23 * MM, 7.3, MUTED)
right('Біляївка · Одеська область', W - M, H - 29 * MM, 7, MUTED)
label('МАТЕРІАЛИ ДЛЯ ВАШОГО ДОМУ', M, H - 62 * MM, 8.2, ORANGE, True)
para('Фасадні<br/>термопанелі.', M, H - 74 * MM, CW, 40, INK, True, leading=46)
para('Фактури. Основи. Товщина. Ціни.', M, H - 115 * MM, CW, 12, MUTED)
photos = [CATALOG['sections'][0]['items'][0], CATALOG['sections'][1]['items'][2], CATALOG['sections'][0]['items'][10]]
gap = 3 * MM
tilew = (CW - 2 * gap) / 3
for k, i in enumerate(photos):
    im = image_reader(i['image'])
    C.drawImage(im, M + k * (tilew + gap), 82 * MM, tilew, 72 * MM, preserveAspectRatio=True, anchor='c', mask='auto')
    rgb(ORANGE)
    C.rect(M + k * (tilew + gap), 79 * MM, tilew, .8 * MM, stroke=0, fill=1)
label('04', M, 57 * MM, 24, INK, True)
label('РОЗДІЛИ', M, 49 * MM, 7.5, MUTED)
label('58', M + 45 * MM, 57 * MM, 24, INK, True)
label('ПАНЕЛЕЙ', M + 45 * MM, 49 * MM, 7.5, MUTED)
para('Інформаційний каталог<br/>для вибору матеріалів фасаду.', M + 92 * MM, 62 * MM, 85 * MM, 10, MUTED)
line(M, 38 * MM, W - M)
label('nashdvor.com.ua', M, 29 * MM, 10, INK, True)
right('Основи · товщини · ціни', W - M, 29 * MM, 7.3, MUTED)
right('Основи, товщини та варіанти оздоблення', W - M, 23 * MM, 7, MUTED)
footer('ВІД ІДЕЇ ДО ВТІЛЕННЯ')
page_end()

# Оглавление и правила чтения таблиц.
page_start('contents', 'Зміст та позначення')
brand(M, H - 28 * MM, 64 * MM)
label('ДОВІДНИК КАТАЛОГУ', M, H - 44 * MM, 7.7, ORANGE, True)
para('Знайдіть свій фасад.', M, H - 52 * MM, CW, 26, INK, True)
contents = [('01', 'Керамограніт', '23 панелі · пінопласт / пінополістирол / сітка', 3, 8),
            ('02', 'Клінкер · Польща', '9 панелей · пінопласт / скловолоконна сітка', 9, 11),
            ('03', 'Під фарбування', '12 фактур · пінопласт 20–200 мм', 12, 15),
            ('04', 'Імітація клінкера', '14 декорів · термозамок', 16, 19)]
y = H - 78 * MM
for n, title, sub, first, last in contents:
    label(n, M, y, 17, ORANGE, True)
    label(title, M + 17 * MM, y + 1 * MM, 13, INK, True)
    label(sub, M + 17 * MM, y - 6 * MM, 7.8, MUTED)
    right(f'{first:02d}—{last:02d}', W - M, y, 11, INK, True)
    C.linkRect('', 'section-' + n, (M, y - 10 * MM, W - M, y + 9 * MM), relative=0, thickness=0)
    line(M, y - 12 * MM, W - M)
    y -= 28 * MM
para('Як читати таблиці', M, 98 * MM, CW, 14, INK, True)
para('<b>Одиниці цін зазначені в кожному розділі.</b> Керамограніт та імітація клінкера — грн/панель; польський клінкер і панелі під фарбування — грн/м². Стовпці — товщина в мм, рядки — основа. '
     '<b>«—»</b> — ціна не зазначена або поєднання основи й товщини не передбачене.', M, 88 * MM, CW, 9)
para('Керамограніт: одна панель покриває 0,564 м². Імітація клінкера: корисна площа панелі — 0,54 м². '
     'Для зручного порівняння звертайте увагу на одиниці виміру над таблицями.', M, 65 * MM, CW, 8.3, MUTED)
para('QR-код у полі фотографії відкриває картку товару на сайті: перегляньте фактуру та деталі онлайн. '
     'Контакти — на сторінці 20.', M, 43 * MM, CW, 8.3, MUTED)
footer('ЗМІСТ / ОСНОВИ / ПОЗНАЧЕННЯ')
page_end()

# Товарные страницы: фиксированная геометрия не допускает разрыва таблиц между страницами.
per_page = [4, 3, 3, 4]
expected_pages = [(3, 8), (9, 11), (12, 15), (16, 19)]
for si, sec in enumerate(CATALOG['sections']):
    chunk_size = per_page[si]
    chunks = [sec['items'][k:k + chunk_size] for k in range(0, len(sec['items']), chunk_size)]
    for pi, chunk in enumerate(chunks):
        page_start('products', sec['title'])
        page = C.getPageNumber()
        if pi == 0:
            assert page == expected_pages[si][0]
            C.bookmarkPage('section-' + f'{si + 1:02d}')
            C.addOutlineEntry(sec['title'], 'section-' + f'{si + 1:02d}', level=0)
        brand(M, H - 27 * MM, 57 * MM)
        right('ФАСАДНІ ТЕРМОПАНЕЛІ', W - M, H - 19 * MM, 7, MUTED)
        line(M, H - 32 * MM, W - M)
        label(f'{si + 1:02d}', M, H - 44 * MM, 20, ORANGE, True)
        label(sec['title'], M + 17 * MM, H - 43 * MM, 19, INK, True)
        right(f'{pi + 1} / {len(chunks)}', W - M, H - 43 * MM, 8, MUTED)
        subtitle = 'Ціни за м²' if si in [1, 2] else 'Ціни за одну панель'
        label(subtitle, M + 17 * MM, H - 51 * MM, 7.4, MUTED)
        top = H - 61 * MM
        row_height = 49 * MM if chunk_size == 4 else 62 * MM
        for idx, i in enumerate(chunk):
            ytop = top - idx * row_height
            tablex = M + 49 * MM
            tablew = CW - 49 * MM
            imageh = 36 * MM if chunk_size == 4 else 43 * MM
            photo(i, M, ytop - imageh, 43 * MM, imageh)
            # Короткое имя сохраняет фактуру и цвет, убирая повтор названия раздела.
            title = re.sub(r'^(Керамогранітна|Клінкерна) термопанель\s*', '', i['name'])
            title = re.sub(r'^Термопанель під фарбування\s*', '', title)
            title = re.sub(r'^Термопанель\s*', '', title)
            title = title.replace(' з термозамком', '')
            titleheight = para(escape(title), tablex, ytop + .5 * MM, tablew, 10.3, INK, True, leading=13, maxh=11 * MM)
            label('АРТИКУЛ  ' + i['sku'], tablex, ytop - titleheight - 3.5 * MM, 6.5, MUTED)
            C.linkURL(i['source'], (tablex, ytop - titleheight - 5 * MM, tablex + tablew, ytop + 2 * MM), relative=0)
            tabtop = ytop - 18 * MM
            th = price_table(i, tablex, tabtop, tablew)
            if i.get('status'):
                label(i['status'], tablex, tabtop - th - 5 * MM, 7, MUTED)
            elif si == 2:
                label('Панелі постачаються під фарбування.', tablex, tabtop - th - 5 * MM, 7, MUTED)
            elif si == 3:
                label('975×600 мм · корисна площа 0,54 м²', tablex, tabtop - th - 5 * MM, 7, MUTED)
            if idx < len(chunk) - 1:
                line(M, ytop - row_height + 4 * MM, W - M)
            MANIFEST['products'].append({'page': page, 'section': sec['id'], 'sku': i['sku'],
                                         'name': i['name'], 'prices': i['price'],
                                         'combinations': i.get('combinations', list(i['price']))})
        if si == 1:
            notes = 'Скловолоконна сітка — без утеплювача. «—» — ціна не зазначена або поєднання не передбачене.'
        elif si == 2:
            notes = 'Пінопласт М25, 11 кг/м³. Панелі постачаються під фарбування. Наявність позначених позицій уточнюйте.'
        elif si == 3:
            notes = 'Пінополістирол 50 / 80 / 100 мм. Розмір 975×600 мм, корисна площа 0,54 м². Ціни за одну панель.'
        else:
            notes = 'Ціна за панель площею 0,564 м². Сітка — без утеплювача. '
        para(escape(notes), M, 30 * MM, CW, 7.2, MUTED, maxh=12 * MM)
        footer(sec['title'].upper())
        page_end()
    assert C.getPageNumber() - 1 == expected_pages[si][1]

# Контакты на задней обложке.
page_start('back', 'Контакти')
brand(M, H - 46 * MM, 112 * MM)
label('ЦЕНТР БЛАГОУСТРОЮ', M, H - 66 * MM, 8.5, ORANGE, True)
para('Від ідеї<br/>до втілення.', M, H - 83 * MM, CW, 35, INK, True, leading=43)
para('Допоможемо зорієнтуватися у фактурах,<br/>основах та варіантах оздоблення фасаду.', M, H - 127 * MM, CW, 11, MUTED)
line(M, 133 * MM, W - M)
label('ЗВ’ЯЖІТЬСЯ З НАМИ', M, 120 * MM, 8.3, ORANGE, True)
for k, (display, phone) in enumerate([('+38 098 578 87 87', CATALOG['contacts']['phone']),
                                      ('+38 095 578 87 87', CATALOG['contacts']['phones'][0])]):
    y = (107 - k * 15) * MM
    label(display, M, y, 20, INK, True)
    C.linkURL('tel:' + phone, (M, y - 3 * MM, M + 110 * MM, y + 7 * MM), relative=0)
label('Біляївка, Одеська область', M, 73 * MM, 11, MUTED)
label('nashdvor.com.ua', M, 57 * MM, 13, INK, True)
C.linkURL('https://nashdvor.com.ua', (M, 54 * MM, M + 100 * MM, 64 * MM), relative=0)
label('Онлайн-каталог', W - M - 43 * MM, 117 * MM, 8, INK, True)
qr('https://catalog.nashdvor.com.ua', W - M - 43 * MM, 70 * MM, 43 * MM)
label('catalog.nashdvor.com.ua', W - M - 43 * MM, 65 * MM, 6.6, MUTED)
para('Переглядайте фактури та порівнюйте варіанти. Докладні характеристики — у картках товарів на сайті.',
     M, 39 * MM, CW, 8, MUTED)
footer('КОНТАКТИ')
page_end()
assert len(MANIFEST['pages']) == 20
assert len(MANIFEST['products']) == 58
assert len({p['sku'] for p in MANIFEST['products']}) == 58
assert not any('basalt_' in v for p in MANIFEST['products'] for v in p['combinations'])
C.save()
MANIFEST['knownPrices'] = sum(len(p['prices']) for p in MANIFEST['products'])
MANIFEST['unknownPrices'] = sum(len(p['combinations']) - len(p['prices']) for p in MANIFEST['products'])
(OUT / 'catalog-manifest.json').write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=2))
print(json.dumps({'pdf': str(PDF), 'pages': len(MANIFEST['pages']), 'items': len(MANIFEST['products']),
                  'prices': MANIFEST['knownPrices'], 'unknownPrices': MANIFEST['unknownPrices'],
                  'photos': MANIFEST['photoCounts'], 'bytes': PDF.stat().st_size}, ensure_ascii=False))

# Вторая версия — готовый спуск полос A3 для брошюры A4 на 5 листах.
# Порядок сторон: 20|1, 2|19, 18|3, 4|17 и т.д. На листе — две страницы A4.
import fitz
source = fitz.open(PDF)
booklet = fitz.open()
order = []
for sheet in range(len(source) // 4):
    for left, right_page in [(len(source) - 1 - 2 * sheet, 2 * sheet),
                             (2 * sheet + 1, len(source) - 2 - 2 * sheet)]:
        spread = booklet.new_page(width=2 * W, height=H)
        spread.show_pdf_page(fitz.Rect(0, 0, W, H), source, left)
        spread.show_pdf_page(fitz.Rect(W, 0, 2 * W, H), source, right_page)
        order.append([left + 1, right_page + 1])
booklet.set_metadata({'title': 'NASH DVOR — Спуск полос A3 для брошури A4', 'author': 'NASH DVOR'})
booklet.save(OUT / 'nash-dvor-catalog-booklet-a3.pdf', garbage=4, deflate=True)
booklet.close()
source.close()
MANIFEST['bookletA3'] = {'sides': 10, 'sheets': 5, 'order': order}
(OUT / 'catalog-manifest.json').write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=2))
print('Booklet A3: 10 sides / 5 sheets, order:', order)
