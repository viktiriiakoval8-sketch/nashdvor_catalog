"""Paired full-frame/tiled DINO dev evaluation with proposals down to 0.10."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.diagnose_semantic_inputs import DEV_IDS,measure,summarize
import numpy as np
from PIL import Image
from facade.core import Segmenter
from facade.openings import boxes_to_mask


def tiles(width,height):
    """Four 60%-size crops, with 20% full-image overlap on each axis."""
    w,h=max(1,round(width*.6)),max(1,round(height*.6))
    return [(x,y,x+w,y+h) for y in (0,height-h) for x in (0,width-w)]


def shift_boxes(boxes,x,y):
    return np.asarray(boxes,dtype=float).reshape(-1,4)+np.array([x,y,x,y])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ids',type=int,nargs='+',default=DEV_IDS)
    args=parser.parse_args()
    if not set(args.ids)<=set(DEV_IDS) or len(set(args.ids))!=len(args.ids):
        parser.error('Only unique known dev images allowed')
    args.output.mkdir(parents=True,exist_ok=True)
    config=json.loads((ROOT/'facade/config.json').read_text(encoding='utf-8'))
    config['openingSuggestionThreshold']=.1
    manifest=dict(config=config,ids=args.ids,protocol='four-60-percent-crops-v1')
    manifest_path=args.output/'manifest.json'
    if manifest_path.exists():
        if json.loads(manifest_path.read_text())!=manifest:
            raise ValueError('Existing experiment has a different configuration or image list')
    elif any(args.output.glob('cmp_b*.json')):
        raise ValueError('Cannot resume an experiment without a configuration manifest')
    else:
        manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    model=Segmenter(config)
    if model.opening_detector is None:raise RuntimeError('DINO unavailable')
    rows=[]
    for number in args.ids:
        stem=f'cmp_b{number:04}'
        row_path=args.output/f'{stem}.json'
        if row_path.exists():
            rows.append(json.loads(row_path.read_text()));continue
        started=time.monotonic()
        image=Image.open(ROOT/'.facade-data/cmp-base'/f'{stem}.jpg').convert('RGB')
        image.thumbnail((1600,1600))
        with Image.open(ROOT/'.facade-data/cmp-base'/f'{stem}.png') as source:
            gt=np.asarray(source.resize(image.size,Image.Resampling.NEAREST))
        diagnostic={}
        model.predict(image,diagnostics=diagnostic)
        if 'rawBoxes' not in diagnostic:raise RuntimeError('Full-frame detector failed')
        all_boxes=[diagnostic['rawBoxes']];all_scores=[diagnostic['rawScores']]
        for x0,y0,x1,y1 in tiles(*image.size):
            crop_diag={}
            model.opening_detector.predict(image.crop((x0,y0,x1,y1)),np.ones((y1-y0,x1-x0),bool),crop_diag)
            all_boxes.append(shift_boxes(crop_diag['rawBoxes'],x0,y0));all_scores.append(crop_diag['rawScores'])
            print(stem,'crop',len(all_boxes)-1,'/4',flush=True)
        boxes=np.concatenate(all_boxes);scores=np.concatenate(all_scores)
        variants={}
        for name,b,s in [('full',all_boxes[0],all_scores[0]),('tilesPlusFull',boxes,scores)]:
            for threshold in [.3,.25,.2,.15,.1]:
                mask,_=boxes_to_mask(b,s,diagnostic['buildingMask'],dict(config,openingDetectionThreshold=threshold))
                variants[f'{name}-{threshold}']=measure(gt,mask|diagnostic['semanticOpeningMask'])
        variants['semantic']=measure(gt,diagnostic['semanticOpeningMask'])
        row=dict(id=stem,seconds=round(time.monotonic()-started,2),variants=variants,
                 fullProposals=len(all_boxes[0]),tileProposals=len(boxes)-len(all_boxes[0]))
        np.savez_compressed(args.output/f'{stem}.npz',fullBoxes=all_boxes[0],fullScores=all_scores[0],
                            combinedBoxes=boxes,combinedScores=scores,buildingMask=diagnostic['buildingMask'],semanticMask=diagnostic['semanticOpeningMask'])
        row_path.write_text(json.dumps(row,indent=2),encoding='utf-8')
        rows.append(row)
        (args.output/'report.json').write_text(json.dumps(dict(config=config,
            purpose='Dev only; masks, not final renders. Four overlapping crops plus full frame; global production duplicate suppression. No training.',
            images=rows,summary={v:summarize([r['variants'][v] for r in rows]) for v in variants}),indent=2),encoding='utf-8')
        print(stem,'seconds',row['seconds'],'full',round(variants['full-0.3']['protectedPixels']/max(1,variants['full-0.3']['referencePixels']),3),
              'tiles',round(variants['tilesPlusFull-0.3']['protectedPixels']/max(1,variants['tilesPlusFull-0.3']['referencePixels']),3),flush=True)
    # Rebuild even when all per-image checkpoints were resumed.
    (args.output/'report.json').write_text(json.dumps(dict(config=config,
        purpose='Dev only; exclusion masks, not final renders; no training.',images=rows,
        summary={v:summarize([r['variants'][v] for r in rows]) for v in rows[0]['variants']}),indent=2),encoding='utf-8')


if __name__=='__main__':main()
