"""Leak-resistant train/val/test split for facade images (grouping, not per-image shuffling).

Groups are unions of (a) perceptually near-identical images and (b) neighbouring file numbers
(`--block`, ASSUMPTION: consecutive CMP ids may show the same street/building; verify on the full set).
Any group that contains an image already used to tune rules/thresholds goes to 'dev': dev is a
tuning/validation pool and must never be reported as an independent test.
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SPLITS = ('train', 'val', 'test')


def dhash(path, size=8):
    with Image.open(path) as image:
        gray = np.asarray(image.convert('L').resize((size + 1, size), Image.Resampling.LANCZOS), dtype=np.int16)
    return int(''.join('1' if bit else '0' for bit in (gray[:, 1:] > gray[:, :-1]).ravel()), 2)


def hamming(a, b):
    return bin(a ^ b).count('1')


def number_of(stem):
    match = re.search(r'(\d+)$', stem)
    return int(match.group(1)) if match else None


def build_groups(items, block=10, max_hamming=6):
    """items: {stem: dhash or None}. Returns list of sorted stem lists (union-find components)."""
    if block < 0 or not 0 <= max_hamming <= 64:
        raise ValueError('Invalid block size or hash distance')
    stems = sorted(items)
    parent = {s: s for s in stems}

    def find(s):
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    def union(a, b):
        parent[find(a)] = find(b)

    first_in_block = {}
    for stem in stems:
        number = number_of(stem)
        if block and number is not None:
            union(stem, first_in_block.setdefault((number - 1) // block, stem))
    hashed = [s for s in stems if items[s] is not None]
    for i, a in enumerate(hashed):
        for b in hashed[i + 1:]:
            if hamming(items[a], items[b]) <= max_hamming:
                union(a, b)
    groups = {}
    for stem in stems:
        groups.setdefault(find(stem), []).append(stem)
    return sorted(sorted(g) for g in groups.values())


def assign(groups, tuned, fractions=(.70, .15, .15), seed=20261031):
    """Returns {stem: split}. Groups containing a tuned stem -> 'dev'. Others split by image count."""
    tuned = set(tuned)
    stems = [s for group in groups for s in group]
    if len(stems) != len(set(stems)):
        raise ValueError('An image occurs in multiple groups')
    if tuned - set(stems):
        raise ValueError('Tuned images are missing from the groups')
    if len(fractions) != 3 or any(f < 0 for f in fractions) or abs(sum(fractions) - 1) > 1e-9:
        raise ValueError('Three nonnegative split fractions must sum to one')
    result, rest = {}, []
    for group in groups:
        if tuned & set(group):
            result.update({s: 'dev' for s in group})
        else:
            rest.append(group)
    random.Random(seed).shuffle(rest)
    total = sum(len(g) for g in rest)
    targets = dict(zip(SPLITS, (round(total * f) for f in fractions)))
    counts = dict.fromkeys(SPLITS, 0)
    for group in rest:
        # fill the split that is furthest below its target (test/val first on ties: they are the scarce ones)
        name = max(('test', 'val', 'train'), key=lambda n: targets[n] - counts[n])
        result.update({s: name for s in group})
        counts[name] += len(group)
    return result


def assert_no_group_leak(groups, assignment):
    for group in groups:
        splits = {assignment[s] for s in group}
        if len(splits) != 1:
            raise AssertionError(f'group spans several splits {sorted(splits)}: {group}')


def parse_numbers(tokens):
    numbers = []
    for token in tokens:
        low, _, high = token.partition('-')
        numbers.extend(range(int(low), int(high or low) + 1))
    return numbers


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--images', type=Path, required=True, help='directory of *.jpg')
    parser.add_argument('--tuned', nargs='*', default=[], help='numbers/ranges already used for tuning, e.g. 1-25 31 61')
    parser.add_argument('--block', type=int, default=10)
    parser.add_argument('--max-hamming', type=int, default=6)
    parser.add_argument('--seed', type=int, default=20261031)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    files = sorted(args.images.glob('*.jpg'))
    if not files:
        parser.error('No JPG images found')
    if args.output.exists():
        parser.error('Output exists; refusing to overwrite an existing split')
    items = {p.stem: dhash(p) for p in files}
    groups = build_groups(items, args.block, args.max_hamming)
    tuned_numbers = set(parse_numbers(args.tuned))
    missing = tuned_numbers - {number_of(s) for s in items}
    if missing:
        parser.error(f'Tuned image numbers not found: {sorted(missing)}')
    tuned = [s for s in items if number_of(s) in tuned_numbers]
    assignment = assign(groups, tuned, seed=args.seed)
    assert_no_group_leak(groups, assignment)
    summary = {name: sum(v == name for v in assignment.values()) for name in ('train', 'val', 'test', 'dev')}
    args.output.write_text(json.dumps(dict(
        note='dev = tuning pool (never an independent test). Groups are assumptions: verify before trusting.',
        status='draft-needs-building-review', groups=groups,
        block=args.block, maxHamming=args.max_hamming, seed=args.seed, tuned=sorted(tuned),
        summary=summary, assignment=assignment), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary))
    return 0


if __name__ == '__main__':
    sys.exit(main())
