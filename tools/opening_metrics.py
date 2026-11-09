"""Opening metrics that cannot be gamed by 'photos processed' or by big windows alone.

All inputs are boolean masks on the same grid (nearest-neighbour resized if needed):
  gt_openings  - reference window+door pixels
  gt_attach    - reference non-paintable attachments (sills, blinds, balconies, ...) for tolerant precision
  excluded     - pixels the pipeline protects from cladding (opening mask)
  paint        - pixels that would actually be painted (final facade mask)
Report numbers WITH the split name; dev numbers are tuning numbers, not test numbers.
"""
import cv2
import numpy as np


def instance_recall(gt_openings, excluded, min_cover=.5, min_area=30):
    """Share of reference opening instances (connected components) protected by >= min_cover of their area."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(gt_openings.astype(np.uint8), connectivity=8)
    found = total = 0
    for index in range(1, count):
        if stats[index, cv2.CC_STAT_AREA] < min_area:
            continue
        total += 1
        region = labels == index
        found += int(excluded[region].mean() >= min_cover)
    return found, total


def leakage(gt_openings, paint):
    """Share of reference opening pixels that would be covered with cladding (lower is better)."""
    reference = int(gt_openings.sum())
    return (int((gt_openings & paint).sum()) / reference) if reference else 0.


def band_precision(gt_openings, gt_attach, excluded, band=6):
    """Excluded pixels are 'justified' if they lie within `band` px of an opening or attachment.

    Plain pixel precision punishes the deliberate safety margin around frames and sills.
    """
    if not excluded.any():
        return 1.
    near = cv2.dilate((gt_openings | gt_attach).astype(np.uint8), np.ones((2 * band + 1,) * 2, np.uint8)) > 0
    return int((excluded & near).sum()) / int(excluded.sum())


def image_metrics(gt_openings, gt_attach, excluded, paint, band=6):
    found, total = instance_recall(gt_openings, excluded)
    reference = int(gt_openings.sum())
    return dict(referencePixels=reference, protectedPixels=int((gt_openings & excluded).sum()),
                coveredPixels=int((gt_openings & paint).sum()), instancesFound=found, instancesTotal=total,
                bandPrecision=band_precision(gt_openings, gt_attach, excluded, band),
                excludedPixels=int(excluded.sum()))


def aggregate(rows):
    """Pixel-weighted and instance-weighted totals over per-image dicts from image_metrics()."""
    ref = sum(r['referencePixels'] for r in rows)
    inst = sum(r['instancesTotal'] for r in rows)
    exc = sum(r['excludedPixels'] for r in rows)
    return dict(pixelRecall=sum(r['protectedPixels'] for r in rows) / ref if ref else None,
                leakage=sum(r['coveredPixels'] for r in rows) / ref if ref else None,
                instanceRecall=sum(r['instancesFound'] for r in rows) / inst if inst else None,
                bandPrecision=(sum(r['bandPrecision'] * r['excludedPixels'] for r in rows) / exc) if exc else None)


def cluster_bootstrap(rows, groups, statistic, n=2000, seed=1):
    """95% interval resampling whole groups (houses/buildings), never single images."""
    if len(rows) != len(groups):
        raise ValueError('Each row must have a building group; refusing silent truncation')
    if n < 1:
        raise ValueError('Bootstrap sample count must be positive')
    if not rows:
        return (None, None)
    rng = np.random.default_rng(seed)
    names = sorted(set(groups))
    by_group = {g: [r for r, gg in zip(rows, groups) if gg == g] for g in names}
    values = []
    for _ in range(n):
        picked = rng.choice(len(names), size=len(names))
        sample = [r for i in picked for r in by_group[names[i]]]
        value = statistic(sample)
        if value is not None:
            values.append(value)
    return tuple(float(x) for x in np.percentile(values, [2.5, 97.5])) if values else (None, None)
