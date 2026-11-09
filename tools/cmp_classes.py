"""CMP -> project class taxonomy for SegFormer fine-tuning (labels only; no training here).

CMP PNGs are indexed images: read the palette INDEX (never convert to RGB) and resize only with
nearest-neighbour. Indices follow CMP label_names.txt (1-based); 0 is not used by CMP and is
treated as 'unlabelled' -> ignore.

Project ids (contiguous, 255 = ignore). CMP has no roof or plinth class, so ids 4 and 5 receive
NO CMP examples: they exist only so the classifier head need not be resized again when private
house labels are added. Predictions for these classes are not reliable until trained and validated.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

CLASSES = ['background', 'wall', 'window', 'door', 'roof', 'plinth', 'attachment']
IGNORE = 255
CMP_NAMES = {1: 'background', 2: 'facade', 3: 'window', 4: 'door', 5: 'cornice', 6: 'sill', 7: 'balcony',
             8: 'blind', 9: 'deco', 10: 'molding', 11: 'pillar', 12: 'shop'}
# 'attachments-ignored' (default for a first experiment): cornices, sills, balconies, blinds, decor,
#   mouldings, pillars and shop fronts are left out of the loss, so CMP-specific European decoration
#   cannot teach the model what a 'wall' is. On the 32 inspected CMP images these classes cover
#   roughly as many pixels as 'facade' itself, so labelling them 'non-wall' would redefine the class.
# 'conservative': they become class 'attachment' (never cladded). Use only after the owner decides
#   which of them a panel must skip and a small manual check shows CMP labels them consistently.
PROFILES = {
    'conservative': {1: 0, 2: 1, 3: 2, 4: 3, 5: 6, 6: 6, 7: 6, 8: 6, 9: 6, 10: 6, 11: 6, 12: 6},
    'attachments-ignored': {1: 0, 2: 1, 3: 2, 4: 3, 5: IGNORE, 6: IGNORE, 7: IGNORE, 8: IGNORE,
                            9: IGNORE, 10: IGNORE, 11: IGNORE, 12: IGNORE},
}


def remap(index_map, profile='attachments-ignored'):
    """index_map: 2-D integer array of CMP palette indices -> uint8 project ids (255 = ignore)."""
    index_map = np.asarray(index_map)
    if index_map.ndim != 2 or not np.issubdtype(index_map.dtype, np.integer):
        raise ValueError('Expected a 2-D integer label map')
    if np.any(index_map < 0) or np.any(index_map > 255):
        raise ValueError('Label indices must be in 0..255; refusing integer wraparound')
    table = np.full(256, IGNORE, np.uint8)
    for cmp_id, target in PROFILES[profile].items():
        table[cmp_id] = target
    return table[np.asarray(index_map, dtype=np.uint8)]


def read_cmp_labels(path):
    with Image.open(path) as image:
        if image.mode not in {'P', 'L'}:
            raise ValueError(f'{path}: expected an indexed label map, got mode {image.mode}')
        return np.asarray(image)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--labels', type=Path, required=True, help='directory with CMP *.png label maps')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', choices=sorted(PROFILES), default='attachments-ignored')
    args = parser.parse_args(argv)
    paths = sorted(args.labels.glob('*.png'))
    if not paths:
        parser.error('No PNG label maps found')
    args.output.mkdir(parents=True, exist_ok=False)
    total = np.zeros(256, np.int64)
    for path in paths:
        mapped = remap(read_cmp_labels(path), args.profile)
        Image.fromarray(mapped, mode='L').save(args.output / path.name)
        total += np.bincount(mapped.ravel(), minlength=256)
    report = {'profile': args.profile, 'classes': CLASSES, 'ignoreIndex': IGNORE,
              'pixels': {(CLASSES[i] if i < len(CLASSES) else 'ignore'): int(total[i])
                         for i in list(range(len(CLASSES))) + [IGNORE]}}
    (args.output / 'class-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['pixels'], ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
