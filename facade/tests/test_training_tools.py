"""Tests for the data/label/metric tooling used to plan SegFormer fine-tuning (no model needed)."""
import json
import random
import pytest

import numpy as np
from PIL import Image

from tools.cmp_classes import CLASSES, IGNORE, PROFILES, read_cmp_labels, remap
from tools.make_splits import assert_no_group_leak, assign, build_groups, dhash, hamming
from tools.opening_metrics import (aggregate, band_precision, cluster_bootstrap, image_metrics,
                                   instance_recall, leakage)


@pytest.mark.parametrize('labels', [np.array([[258]]), np.array([[-254]]),
                                   np.array([[2.5]]), np.zeros((2, 2, 3), np.uint8)])
def test_remap_rejects_invalid_indices_instead_of_wrapping(labels):
    with pytest.raises(ValueError):
        remap(labels)


def test_split_rejects_missing_tuned_images_and_duplicate_membership():
    with pytest.raises(ValueError):
        assign([['a']], ['missing'])
    with pytest.raises(ValueError):
        assign([['a'], ['a']], [])


def test_split_cli_does_not_overwrite_or_ignore_missing_images(tmp_path):
    from tools.make_splits import main
    Image.new('RGB', (20, 20)).save(tmp_path / 'cmp_b0001.jpg')
    output = tmp_path / 'split.json'
    args = ['--images', str(tmp_path), '--output', str(output)]
    with pytest.raises(SystemExit):
        main(args + ['--tuned', '2'])
    assert not output.exists()
    main(args + ['--tuned', '1'])
    original = output.read_bytes()
    assert json.loads(original)['status'] == 'draft-needs-building-review'
    with pytest.raises(SystemExit):
        main(args)
    assert output.read_bytes() == original


def test_bootstrap_rejects_missing_building_ids():
    with pytest.raises(ValueError):
        cluster_bootstrap([{}, {}], ['one'], lambda rows: 0)
    assert cluster_bootstrap([], [], lambda rows: 0) == (None, None)


def test_remap_uses_palette_indices_and_profiles(tmp_path):
    pixels = np.array([[1, 2, 3, 4], [5, 6, 7, 12], [8, 9, 10, 11]], np.uint8)
    image = Image.fromarray(pixels).convert('P')
    image.putpalette([200, 10, 10] * 256)           # RGB appearance must not decide anything
    path = tmp_path / 'labels.png'
    image.save(path)
    conservative = remap(read_cmp_labels(path), 'conservative')
    assert conservative[0].tolist() == [CLASSES.index('background'), CLASSES.index('wall'),
                                        CLASSES.index('window'), CLASSES.index('door')]
    assert set(conservative[1:].ravel().tolist()) == {CLASSES.index('attachment')}
    ignored = remap(pixels)                                   # default profile
    assert set(ignored[1:].ravel().tolist()) == {IGNORE}
    assert 255 == int(remap(np.array([[0]], np.uint8))[0, 0])      # unlabelled stays ignored
    # roof/plinth ids are reserved: CMP must never produce them
    for profile in PROFILES.values():
        assert CLASSES.index('roof') not in profile.values() and CLASSES.index('plinth') not in profile.values()


def test_rgb_label_map_is_rejected(tmp_path):
    Image.new('RGB', (4, 4)).save(tmp_path / 'rgb.png')
    try:
        read_cmp_labels(tmp_path / 'rgb.png')
    except ValueError:
        return
    raise AssertionError('RGB labels must be refused')


def test_splits_never_leak_groups_and_keep_tuned_images_out_of_test():
    rng = random.Random(3)
    items = {f'cmp_b{n:04}': rng.getrandbits(64) for n in range(1, 379)}
    items['cmp_b0300'] = items['cmp_b0100']                              # near-duplicate from far away
    groups = build_groups(items, block=10)
    tuned = [f'cmp_b{n:04}' for n in list(range(1, 26)) + [31, 61, 91, 121, 151, 181, 211]]
    assignment = assign(groups, tuned)
    assert_no_group_leak(groups, assignment)
    assert all(assignment[s] == 'dev' for s in tuned)
    assert assignment['cmp_b0100'] == assignment['cmp_b0300']
    assert assignment['cmp_b0006'] == 'dev'                              # neighbour of a tuned image
    counts = {k: sum(v == k for v in assignment.values()) for k in ('train', 'val', 'test', 'dev')}
    assert counts['test'] > 20 and counts['val'] > 20 and counts['train'] > counts['val'] + counts['test']
    assert assign(groups, tuned) == assignment                           # deterministic


def test_dhash_groups_resized_copies_but_not_unrelated(tmp_path):
    rng = np.random.default_rng(0)
    base = Image.fromarray(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)).resize((160, 120))
    base.save(tmp_path / 'a.jpg')
    base.resize((320, 240)).save(tmp_path / 'b.jpg')
    Image.fromarray(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)).save(tmp_path / 'c.jpg')
    a, b, c = (dhash(tmp_path / f'{n}.jpg') for n in 'abc')
    assert hamming(a, b) <= 6 < hamming(a, c)


def _scene():
    gt = np.zeros((200, 300), bool)
    attach = np.zeros_like(gt)
    for x in (30, 130, 230):
        gt[40:90, x:x + 40] = True
    attach[90:96, 28:72] = True                                         # a sill under the first window
    return gt, attach


def test_metrics_on_perfect_empty_and_partial_predictions():
    gt, attach = _scene()
    paint = np.ones_like(gt)
    perfect = image_metrics(gt, attach, gt.copy(), paint & ~gt)
    assert perfect['instancesFound'] == perfect['instancesTotal'] == 3
    assert leakage(gt, paint & ~gt) == 0 and perfect['bandPrecision'] == 1
    none = image_metrics(gt, attach, np.zeros_like(gt), paint)
    assert none['instancesFound'] == 0 and leakage(gt, paint) == 1
    only_one = gt.copy(); only_one[:, 100:] = False                      # protects one of three windows
    part = image_metrics(gt, attach, only_one, paint & ~only_one)
    assert (part['instancesFound'], part['instancesTotal']) == (1, 3)
    assert abs(leakage(gt, paint & ~only_one) - 2 / 3) < 1e-9
    big = np.zeros_like(gt); big[:, :] = True
    assert band_precision(gt, attach, big) < .5                          # excluding everything is not precise


def test_safety_margin_is_not_punished_but_far_false_boxes_are():
    gt, attach = _scene()
    margin = np.zeros_like(gt); margin[36:94, 26:74] = True              # window + sill + a few px of margin
    assert band_precision(gt, attach, margin, band=6) > .98
    far = np.zeros_like(gt); far[150:190, 100:200] = True
    assert band_precision(gt, attach, far) == 0


def test_instance_recall_ignores_specks_and_aggregate_weights_by_pixels():
    gt, attach = _scene()
    gt[5:7, 5:7] = True                                                  # 4-pixel speck: not an instance
    assert instance_recall(gt, np.zeros_like(gt))[1] == 3
    a = image_metrics(gt, attach, gt.copy(), ~gt)
    b = image_metrics(gt, attach, np.zeros_like(gt), np.ones_like(gt))
    total = aggregate([a, b])
    assert abs(total['pixelRecall'] - .5) < 1e-9 and abs(total['instanceRecall'] - .5) < 1e-9


def test_cluster_bootstrap_resamples_groups():
    gt, attach = _scene()
    good = image_metrics(gt, attach, gt.copy(), ~gt)
    bad = image_metrics(gt, attach, np.zeros_like(gt), np.ones_like(gt))
    rows, groups = [good, good, bad, bad], ['h1', 'h1', 'h2', 'h2']
    low, high = cluster_bootstrap(rows, groups, lambda s: aggregate(s)['instanceRecall'], n=300)
    assert low == 0 and high == 1                                        # two houses: the interval is honestly wide
