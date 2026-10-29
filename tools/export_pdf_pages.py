#!/usr/bin/env python3
"""Экспорт всех страниц актуального PDF в ZIP с PNG (A4, 150 dpi) и общий обзор."""
from pathlib import Path
from math import ceil
import hashlib, zipfile, tempfile
import fitz
from PIL import Image, ImageDraw, ImageFont
ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / 'print/nash-dvor-catalog.pdf'
DOC = fitz.open(PDF)
with tempfile.TemporaryDirectory(prefix='nashdvor-pages-') as tmp:
    paths = []
    for n, page in enumerate(DOC, 1):
        p = Path(tmp) / f'page-{n:02d}.png'
        page.get_pixmap(dpi=150, alpha=False).save(p)
        paths.append(p)
    archive = ROOT / 'print/nash-dvor-pages.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as z:
        for p in paths:
            z.write(p, p.name)
        z.writestr('README.txt', f'NASH DVOR — актуальні сторінки PDF-каталогу\n{len(paths)} PNG повних сторінок A4, 150 dpi.\nУсі ціни — у гривнях (грн). Для імітації клінкера ціни наведено за м².\nSHA-256 PDF: {hashlib.sha256(PDF.read_bytes()).hexdigest()}\n')
    width, height, gap, label, cols = 240, 340, 18, 24, 5
    rows = ceil(len(paths) / cols)
    overview = Image.new('RGB', (cols * width + (cols + 1) * gap, rows * (height + label) + (rows + 1) * gap), '#e7e4dd')
    draw = ImageDraw.Draw(overview)
    font = ImageFont.truetype('/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf', 15)
    for n, p in enumerate(paths):
        im = Image.open(p)
        im.thumbnail((width, height), Image.Resampling.LANCZOS)
        x = gap + n % cols * (width + gap)
        y = gap + n // cols * (height + label + gap)
        overview.paste(im, (x + (width - im.width) // 2, y))
        draw.text((x + width / 2, y + height + 2), f'{n + 1:02d}', font=font, fill='#202020', anchor='mt')
    overview.save(ROOT / 'print/nash-dvor-pages-overview.png', optimize=True)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len([n for n in z.namelist() if n.endswith('.png')]) == len(DOC)
    print(f'Exported {len(DOC)} pages; ZIP {archive.stat().st_size} bytes')
