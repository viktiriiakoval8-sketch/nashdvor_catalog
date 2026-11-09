"""Re-evaluate saved tiled proposals, including a crop-relative size guard."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from PIL import Image
from facade.openings import boxes_to_mask
from tools.diagnose_semantic_inputs import measure,summarize
from tools.diagnose_tiled_openings import tiles


def crop_size_guard(boxes,scores,width,height):
    x0,y0,x1,y1=tiles(width,height)[0]
    boxes=np.asarray(boxes).reshape(-1,4)
    area=(boxes[:,2]-boxes[:,0])*(boxes[:,3]-boxes[:,1])
    keep=(area>0)&(area<=(x1-x0)*(y1-y0)*.45)
    return boxes[keep],np.asarray(scores)[keep]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnostic',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads((args.diagnostic/'report.json').read_text())
    rows=[]
    for row in report['images']:
        with np.load(args.diagnostic/(row['id']+'.npz')) as cache:
            height,width=cache['buildingMask'].shape
            with Image.open(ROOT/'.facade-data/cmp-base'/(row['id']+'.png')) as image:
                labels=np.asarray(image.resize((width,height),Image.Resampling.NEAREST))
            count=len(cache['fullBoxes'])
            b,s=crop_size_guard(cache['combinedBoxes'][count:],cache['combinedScores'][count:],width,height)
            boxes=np.concatenate([cache['fullBoxes'],b]);scores=np.concatenate([cache['fullScores'],s])
            variants=dict(row['variants'])
            for threshold in [.3,.25,.2,.15,.1]:
                mask,_=boxes_to_mask(boxes,scores,cache['buildingMask'],dict(report['config'],openingDetectionThreshold=threshold))
                variants[f'guardedTiles-{threshold}']=measure(labels,mask|cache['semanticMask'])
            rows.append(dict(id=row['id'],variants=variants))
    summary={v:summarize([r['variants'][v] for r in rows]) for v in rows[0]['variants']}
    output=dict(purpose='Dev-only post-hoc crop-size experiment. Same proposals, no retraining. Wall exclusion includes frame margins.',
                images=len(rows),summary=summary,perImage=rows)
    (args.diagnostic/'comparison.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(dict(images=len(rows),summary=summary),indent=2))


if __name__=='__main__':main()
