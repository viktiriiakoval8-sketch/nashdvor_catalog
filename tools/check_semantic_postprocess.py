"""Check bilinear-logits-before-argmax against the existing CMP dev audit."""
import argparse
import json
import time
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.diagnose_semantic_inputs import DEV_IDS,measure,summarize
import numpy as np
from PIL import Image
from facade.core import Segmenter
from facade.structure import opening_mask


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    config=json.loads((ROOT/'facade/config.json').read_text(encoding='utf-8'))
    model=Segmenter(dict(config,openingDetectorModel=None))
    torch=model.torch
    rows=[]
    for number in DEV_IDS:
        stem=f'cmp_b{number:04}'
        image=Image.open(ROOT/'.facade-data/cmp-base'/f'{stem}.jpg').convert('RGB')
        image.thumbnail((1600,1600))
        with Image.open(ROOT/'.facade-data/cmp-base'/f'{stem}.png') as source:
            gt=np.asarray(source.resize(image.size,Image.Resampling.NEAREST))
        started=time.monotonic()
        with torch.inference_mode():
            logits=model.model(**model.processor(images=image,return_tensors='pt')).logits
            resized=torch.nn.functional.interpolate(logits,size=image.size[::-1],mode='bilinear',align_corners=False)[0]
            labels=resized.argmax(dim=0).numpy().astype('uint8')
            # Sum selected exp(logit-logsumexp) without allocating a full probability tensor.
            normalizer=torch.logsumexp(resized,dim=0)
            opening=(resized[model.opening_ids]-normalizer).exp().sum(dim=0).numpy()
            del resized,normalizer,logits
        mask=opening_mask(labels,opening,model.opening_ids,config)
        row=dict(id=stem,seconds=round(time.monotonic()-started,2),
                 argmaxPixels=int(np.isin(labels,model.opening_ids).sum()),
                 maxOpeningProbability=float(opening.max()),metrics=measure(gt,mask))
        rows.append(row)
        (args.output/'report.json').write_text(json.dumps(dict(purpose='Dev-only default 512 input; standard bilinear logits before argmax, no training',
            images=rows,summary=summarize([r['metrics'] for r in rows])),indent=2),encoding='utf-8')
        print(stem,'argmax',row['argmaxPixels'],'max',round(row['maxOpeningProbability'],5),flush=True)


if __name__=='__main__':main()
