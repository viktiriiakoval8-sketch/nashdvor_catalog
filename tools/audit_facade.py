"""Offline diagnostic inference; never creates leads or trains model weights.

Run from the checkout: python tools/audit_facade.py --output PATH PHOTO [PHOTO ...]
Small photos are processed for diagnosis, with upload failures recorded explicitly.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('HF_HOME', str(ROOT / '.facade-data/model-cache'))
os.environ.setdefault('HF_HUB_OFFLINE', '1')

import numpy as np
from PIL import Image, ImageOps
from facade.core import Segmenter, facade_geometry, validate_photo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('photos', type=Path, nargs='+')
    args = parser.parse_args()
    # Preserve earlier baselines; accidental reruns must not overwrite evidence.
    args.output.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT / 'facade/config.json').read_text(encoding='utf-8'))
    model = Segmenter(config)
    rows = []
    for number, path in enumerate(args.photos, 1):
        quality_error = None
        try:
            image = validate_photo(path.read_bytes(), config)
        except ValueError as exc:
            quality_error = str(exc)
            with Image.open(path) as original:
                image = ImageOps.exif_transpose(original).convert('RGB')
            image.thumbnail((1600, 1600))
        probability, wall, detection = model.predict(image)
        mask, corners, confidence, factors = facade_geometry(probability, wall, config, detection)
        if mask is None:
            mask = np.zeros(wall.shape, np.uint8)
        preview = np.array(image)
        for label, region, color in (
            ('facade', mask > 0, (40, 210, 90)),
            ('openings', detection['openingMask'], (255, 65, 80)),
            ('plinth', detection['plinthMask'], (30, 130, 255)),
        ):
            Image.fromarray(region.astype(np.uint8)*255).save(args.output / f'{number:02}-{label}.png')
            preview[region] = (preview[region]*.45 + np.array(color)*.55).astype(np.uint8)
        Image.fromarray(preview).save(args.output / f'{number:02}-review.png')
        row = dict(filename=path.name, size=list(image.size), qualityError=quality_error,
                   openingSuggestions=detection.get('openingSuggestions', []),
                   confidence=confidence, factors=factors,
                   openingPixels=int(detection['openingMask'].sum()),
                   plinthPixels=int(detection['plinthMask'].sum()),
                   diagnosticOnly=True, trainingPerformed=False)
        rows.append(row)
        (args.output / 'report.json').write_text(json.dumps(
            dict(config=config, images=rows), ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
