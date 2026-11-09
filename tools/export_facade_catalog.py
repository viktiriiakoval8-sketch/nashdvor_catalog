"""Export exact catalog prices and original textures. Run after editing CATALOG."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / 'index.html').read_text(encoding='utf-8')
catalog, _ = json.JSONDecoder().raw_decode(text.split('const CATALOG = ', 1)[1])
items = []
for section in catalog['sections']:
    if section['id'] not in {'porcelain', 'polish-clinker', 'clinker-imitation'}:
        continue
    for source in section['items']:
        item = dict(source, section=section['id'], colors=source.get('color', ''),
                    tileSize=source.get('tileSize'), tier=source.get('tier'),
                    visualizationTexture=source.get('visualizationTexture') or source['image'],
                    textureSource='catalog-original')
        items.append(item)
(ROOT / 'catalog-data.json').write_text(json.dumps({'items': items}, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Exported {len(items)} panels with unchanged prices and original images.')
