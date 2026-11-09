"""Compare thresholds on cached dev proposals without running or modifying models."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from facade.openings import boxes_to_mask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnostic',type=Path,required=True)
    args = parser.parse_args()
    report = json.loads((args.diagnostic/'report.json').read_text())
    results = []
    for threshold in (.3,.25,.2):
        for mode in ('interior','ring'):
            tp = ref = excluded = 0
            for row in report['images']:
                with np.load(args.diagnostic/(row['id']+'.npz'),allow_pickle=False) as cache:
                    config = dict(report['config'],openingDetectionThreshold=threshold)
                    mask,_ = boxes_to_mask(cache['rawBoxes'],cache['rawScores'],cache['buildingMask'],config,context_mode=mode)
                    mask |= cache['semanticOpeningMask']
                    reference = cache['reference']
                    tp += int((mask & reference).sum())
                    ref += int(reference.sum())
                    excluded += int(mask.sum())
            results.append(dict(threshold=threshold,mode=mode,pixelRecall=tp/max(1,ref),
                                strictPrecision=tp/max(1,excluded),excludedPixels=excluded))
    output=dict(purpose='Dev diagnostic, protection masks only. Not final rendered results. Raw proposal cutoff was 0.2; lower thresholds cannot be evaluated.',
                images=len(report['images']),results=results)
    (args.diagnostic/'threshold-comparison.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output,indent=2))


if __name__ == '__main__':
    main()
