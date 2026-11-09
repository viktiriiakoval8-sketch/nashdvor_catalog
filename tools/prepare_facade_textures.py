"""Prepare and verify catalog textures before starting the facade service."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from facade.textures import load, prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify without any network requests')
    args = parser.parse_args()
    cache = Path(os.environ.get('FACADE_DATA_DIR', ROOT / '.facade-data')) / 'texture-cache'
    panels = json.loads((ROOT / 'catalog-data.json').read_text(encoding='utf-8'))['items']
    failures = []
    import httpx
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        for panel in panels:
            try:
                if args.check:
                    load(panel['visualizationTexture'], ROOT, cache).close()
                    state = 'verified'
                else:
                    state = prepare(panel['visualizationTexture'], ROOT, cache, client)
                print(f"{panel['id']}: {state}", flush=True)
            except Exception as exc:
                failures.append(panel['id'])
                print(f"{panel['id']}: FAILED ({type(exc).__name__})", flush=True)
    print(f'{len(panels)-len(failures)}/{len(panels)} textures ready', flush=True)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
