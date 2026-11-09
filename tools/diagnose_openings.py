"""Dev-only paired opening-filter diagnostic, using identical model proposals."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('HF_HOME', str(ROOT / '.facade-data/model-cache'))
os.environ.setdefault('HF_HUB_OFFLINE', '1')
import numpy as np
from PIL import Image
from facade.core import Segmenter, facade_geometry
from facade.openings import boxes_to_mask
from tools.opening_metrics import image_metrics, aggregate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ids', type=int, nargs='+', default=[1,31,61,91,121,151,181,211])
    args = parser.parse_args()
    # Only already-inspected development images; do not consume the draft test.
    allowed = set(range(1,26)) | {31,61,91,121,151,181,211}
    if not set(args.ids) <= allowed or len(set(args.ids)) != len(args.ids):
        parser.error('Use unique, already-inspected development IDs only')
    args.output.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT/'facade/config.json').read_text(encoding='utf-8'))
    model = Segmenter(config)
    rows = []
    for number in args.ids:
        stem = f'cmp_b{number:04}'
        with Image.open(ROOT/'.facade-data/cmp-base'/f'{stem}.jpg') as source:
            image = source.convert('RGB')
        image.thumbnail((1600,1600))
        with Image.open(ROOT/'.facade-data/cmp-base'/f'{stem}.png') as source:
            labels = np.asarray(source.resize(image.size,Image.Resampling.NEAREST))
        diagnostic = {}
        probability, wall, detection = model.predict(image, diagnostics=diagnostic)
        if detection['openingDetectorStatus'] != 'ready':
            raise RuntimeError(f'{stem}: detector unavailable; comparison invalid')
        paint, _, confidence, _ = facade_geometry(probability,wall,config,detection)
        counts = {}
        ring, _ = boxes_to_mask(diagnostic['rawBoxes'],diagnostic['rawScores'],
                               diagnostic['buildingMask'],config,counts,context_mode='ring')
        semantic, dino = diagnostic['semanticOpeningMask'], diagnostic['dinoOpeningMask']
        variants = dict(semantic=semantic,dino=dino,union=semantic|dino,
                        ring=ring,unionRing=semantic|ring)
        reference = np.isin(labels,[3,4])
        attach = np.isin(labels,[6,7,8])
        # Paint is held fixed: variant leakage is not an end-to-end counterfactual.
        actual_paint = np.zeros_like(reference) if paint is None else paint>0
        metrics = {name:image_metrics(reference,attach,mask,actual_paint)
                   for name,mask in variants.items()}
        rows.append(dict(id=stem,confidence=confidence,
                         interiorCounts=diagnostic['rejections'],ringCounts=counts,
                         variants=metrics))
        arrays = {key:value for key,value in diagnostic.items() if isinstance(value,np.ndarray)}
        np.savez_compressed(args.output/f'{stem}.npz',**arrays,ringMask=ring,
                            finalPaintMask=actual_paint,reference=reference)
        for name, mask in variants.items():
            Image.fromarray(mask.astype('uint8')*255).save(args.output/f'{stem}-{name}.png')
        report = dict(purpose='Dev diagnostic only; no training. Leakage uses unchanged production paint in every variant; compare protection recall/precision, not variant leakage.',
                      config=config,images=rows,
                      summary={name:aggregate([r['variants'][name] for r in rows]) for name in variants},
                      interiorCounts=dict(sum((Counter(r['interiorCounts']) for r in rows),Counter())),
                      ringCounts=dict(sum((Counter(r['ringCounts']) for r in rows),Counter())))
        (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(stem, 'union recall',round(metrics['union']['protectedPixels']/max(1,reference.sum()),3),
              'ring union',round(metrics['unionRing']['protectedPixels']/max(1,reference.sum()),3),flush=True)


if __name__ == '__main__':
    main()
