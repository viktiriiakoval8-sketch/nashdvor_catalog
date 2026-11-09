"""Download model assets explicitly, before starting the local facade service."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('HF_HOME', str(ROOT / '.facade-data/model-cache'))


def main():
    from huggingface_hub import snapshot_download
    config = json.loads((ROOT / 'facade/config.json').read_text(encoding='utf-8'))
    models = [(config['model'], 'main')]
    if config.get('openingDetectorModel'):
        models.append((config['openingDetectorModel'], config.get('openingDetectorRevision', 'main')))
    for name, revision in models:
        path = snapshot_download(name, revision=revision, allow_patterns=[
            '*.json', '*.txt', '*.safetensors'])
        print(f'{name}: {path}', flush=True)


if __name__ == '__main__':
    main()
