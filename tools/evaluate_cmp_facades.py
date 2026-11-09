"""Evaluate actual painted opening pixels against CMP annotations, never train on predictions."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('HF_HOME',str(ROOT/'.facade-data/model-cache'))
os.environ.setdefault('HF_HUB_OFFLINE','1')
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from facade.core import Segmenter, facade_geometry


def reference_openings(path, size):
    # Keep palette indices: CMP label_names.txt defines window=3 and door=4.
    # XML's axes use matrix conventions; the supplied raster avoids transposition
    # and already respects annotation z-order (e.g. balconies over windows).
    with Image.open(path) as labels:
        if labels.mode not in {'P','L'}:
            raise ValueError('Expected indexed CMP label map')
        return np.isin(np.asarray(labels.resize(size,Image.Resampling.NEAREST)),[3,4])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ids',type=int,nargs='+',default=[1,31,61,91,121,151,181,211])
    parser.add_argument('--reuse-predictions',type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    config=json.loads((ROOT/'facade/config.json').read_text(encoding='utf-8'))
    cached = None
    if args.reuse_predictions:
        saved=json.loads((args.reuse_predictions/'report.json').read_text(encoding='utf-8'))
        config=saved['config']
        cached={row['id']:row for row in saved['images']}
    model=Segmenter(config) if cached is None else None
    rows=[]
    for number in args.ids:
        stem=f'cmp_b{number:04}'
        source=ROOT/'.facade-data/cmp-base'
        image=Image.open(source/(stem+'.jpg')).convert('RGB')
        image.thumbnail((1600,1600))
        reference=reference_openings(source/(stem+'.png'),image.size)
        started=time.monotonic()
        if cached is None:
            probability,wall,detection=model.predict(image)
            mask,corners,confidence,factors=facade_geometry(probability,wall,config,detection)
            predicted=detection['openingMask']
        else:
            with np.load(args.reuse_predictions/(stem+'.npz')) as saved:
                probability,wall,mask,predicted=(saved[k].copy() for k in ('probability','wall','mask','predicted'))
            confidence,factors=cached[stem]['confidence'],cached[stem]['factors']
        tp=int((reference&predicted).sum())
        painted=int(((mask>0)&reference).sum()) if mask is not None else 0
        row=dict(id=stem,seconds=cached[stem]['seconds'] if cached else round(time.monotonic()-started,2),confidence=confidence,
                 referencePixels=int(reference.sum()),excludedPixels=int(predicted.sum()),
                 intersectionPixels=tp,paintedOpeningPixels=painted,
                 openingRecall=tp/max(1,int(reference.sum())),
                 openingPrecision=tp/max(1,int(predicted.sum())),
                 accepted=confidence>=config['minimumConfidence'],factors=factors)
        rows.append(row)
        np.savez_compressed(args.output/(stem+'.npz'),reference=reference,predicted=predicted,
                            wall=wall,probability=probability,mask=mask if mask is not None else np.zeros_like(wall))
        preview=np.array(image)
        preview[reference]=(preview[reference]*.4+np.array([40,210,90])*.6).astype(np.uint8)
        missed=reference&~predicted
        preview[missed]=(preview[missed]*.4+np.array([255,40,40])*.6).astype(np.uint8)
        Image.fromarray(preview).save(args.output/(stem+'-review.png'))
        (args.output/'report.json').write_text(json.dumps(dict(config=config,images=rows,
            purpose='development evaluation; not held-out test; no training'),ensure_ascii=False,indent=2),encoding='utf-8')
        print(stem, 'recall',round(row['openingRecall'],3),'precision',round(row['openingPrecision'],3),
              'painted',painted,'accepted',row['accepted'],flush=True)
    (args.output/'ATTRIBUTION.md').write_text((ROOT/'.facade-data/cmp-base/ATTRIBUTION.md').read_text(encoding='utf-8'),encoding='utf-8')


if __name__=='__main__':
    main()
