"""Offline SegFormer input/label/probability audit on the 32 known CMP dev images."""
import json
import os
from pathlib import Path
import sys
import argparse
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('HF_HOME',str(ROOT/'.facade-data/model-cache'))
os.environ.setdefault('HF_HUB_OFFLINE','1')
import cv2
import numpy as np
from PIL import Image
from facade.core import Segmenter
from facade.structure import opening_mask
from tools.opening_metrics import image_metrics,aggregate

DEV_IDS=list(range(1,26))+[31,61,91,121,151,181,211]


def measure(labels,mask):
    gt=np.isin(labels,[3,4])
    metrics=image_metrics(gt,np.isin(labels,[6,7,8]),mask,np.zeros_like(mask))
    metrics.pop('coveredPixels')
    metrics.update(wallPixels=int((labels==2).sum()),excludedWallPixels=int(((labels==2)&mask).sum()))
    return metrics


def summarize(rows):
    result=aggregate([dict(r,coveredPixels=0) for r in rows])
    result.pop('leakage')
    excluded=sum(r['excludedPixels'] for r in rows)
    result['strictPrecision']=sum(r['protectedPixels'] for r in rows)/excluded if excluded else None
    result['excludedWallFraction']=sum(r['excludedWallPixels'] for r in rows)/max(1,sum(r['wallPixels'] for r in rows))
    return result


def distribution(values):
    if not values.size:return None
    return dict(zip(['p0','p25','p50','p75','p90','p99','p100'],map(float,np.percentile(values,[0,25,50,75,90,99,100]))))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ids',type=int,nargs='+',default=DEV_IDS)
    args=parser.parse_args()
    if not set(args.ids)<=set(DEV_IDS) or len(set(args.ids))!=len(args.ids):
        parser.error('Only unique known dev images allowed')
    args.output.mkdir(parents=True,exist_ok=False)
    config=json.loads((ROOT/'facade/config.json').read_text(encoding='utf-8'))
    model=Segmenter(dict(config,openingDetectorModel=None))
    torch=model.torch
    meta=dict(model=config['model'],openingClasses={str(i):model.model.config.id2label[i] for i in model.opening_ids},
              processor=model.processor.to_dict(),purpose='Dev diagnostic; no training; masks only, not final rendering')
    rows=[]
    for number in args.ids:
        stem=f'cmp_b{number:04}'
        image=Image.open(ROOT/'.facade-data/cmp-base'/f'{stem}.jpg').convert('RGB')
        image.thumbnail((1600,1600))
        with Image.open(ROOT/'.facade-data/cmp-base'/f'{stem}.png') as source:
            gt=np.asarray(source.resize(image.size,Image.Resampling.NEAREST))
        for mode in ['default','long512','long1024']:
            started=time.monotonic()
            options={}
            if mode!='default':
                side=int(mode[4:]); scale=side/max(image.size)
                options['size']={'height':max(32,round(image.height*scale)), 'width':max(32,round(image.width*scale))}
            inputs=model.processor(images=image,return_tensors='pt',**options)
            with torch.inference_mode():
                logits=model.model(**inputs).logits
                prob=logits.softmax(dim=1)[0]
            labels=cv2.resize(prob.argmax(dim=0).numpy().astype('uint8'),image.size,interpolation=cv2.INTER_NEAREST)
            opening=cv2.resize(prob[model.opening_ids].sum(dim=0).numpy(),image.size,interpolation=cv2.INTER_LINEAR)
            variants={}
            for threshold in [.4,.2,.1]:
                mask=opening_mask(labels,opening,model.opening_ids,dict(config,openingProbability=threshold))
                variants[str(threshold)]=measure(gt,mask)
            raw=np.isin(labels,model.opening_ids)|(opening>=.4)
            row=dict(id=stem,mode=mode,seconds=round(time.monotonic()-started,2),inputShape=list(inputs['pixel_values'].shape),
                     inputRange=[float(inputs['pixel_values'].min()),float(inputs['pixel_values'].max())],
                     probabilityInside=distribution(opening[np.isin(gt,[3,4])]),probabilityOutside=distribution(opening[~np.isin(gt,[3,4])]),
                     rawOpeningPixels=int(raw.sum()),argmaxOpeningPixels=int(np.isin(labels,model.opening_ids).sum()),variants=variants)
            rows.append(row)
            np.savez_compressed(args.output/f'{stem}-{mode}.npz',openingProbability=opening,labels=labels)
            summary={m:{t:summarize([r['variants'][t] for r in rows if r['mode']==m]) for t in variants}
                     for m in {r['mode'] for r in rows}}
            (args.output/'report.json').write_text(json.dumps(dict(**meta,images=rows,summary=summary),indent=2,default=str),encoding='utf-8')
            print(stem,mode,'max',round(float(opening.max()),5),'raw',int(raw.sum()),'recall',round(variants['0.4']['protectedPixels']/max(1,variants['0.4']['referencePixels']),3),flush=True)


if __name__=='__main__':main()
