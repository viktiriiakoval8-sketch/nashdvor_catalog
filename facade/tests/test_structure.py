import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from facade.core import facade_geometry, overlay
from facade.structure import opening_mask, separate_plinth, baseline_plane

CONFIG = json.loads((Path(__file__).parents[1] / 'config.json').read_text(encoding='utf-8'))


def test_openings_protect_frame_and_survive_building_fallback():
    labels = np.zeros((400, 600), np.uint8)
    labels[100:180, 160:240] = 8  # window glass
    labels[240:360, 350:400] = 14  # door
    exclusions = opening_mask(labels, np.zeros(labels.shape), [8, 14], CONFIG)
    assert exclusions[99, 159] and exclusions[360, 401]
    wall = np.zeros(labels.shape, bool)
    wall[30:380, 30:570] = True  # coarse building mask includes both openings
    mask, corners, confidence, _ = facade_geometry(np.ones(labels.shape), wall, CONFIG,
        dict(method='appearance-refined-building', openingMask=exclusions))
    assert confidence >= .5
    assert not mask[exclusions].any()
    source = Image.fromarray(np.random.default_rng(2).integers(20, 220, (400, 600, 3), dtype=np.uint8))
    result = np.asarray(overlay(source, Image.new('RGB', (80, 40), 'red'), mask, corners, {}, CONFIG))
    assert np.array_equal(result[exclusions], np.asarray(source)[exclusions])


def scene(plinth=False, courses=False):
    rgb = np.full((500, 800, 3), 210, np.uint8)
    wall = np.zeros((500, 800), bool)
    wall[40:460, 50:750] = True
    rgb[wall] = (180, 165, 140)
    if plinth:
        rgb[380:460, 50:750] = (105, 105, 100)
        rgb[378:381, 50:750] = 40
    if courses:
        for y in range(80, 450, 40):
            rgb[y:y+2, 50:750] = 40
    return Image.fromarray(rgb), wall


def test_plinth_requires_material_transition_and_preserves_source():
    image, wall = scene(plinth=True)
    plinth, boundary = separate_plinth(image, wall, wall, CONFIG)
    assert boundary is not None and abs(boundary['intercept']-380) < 5
    assert plinth[400, 400] and not plinth[350, 400] and not plinth[470, 400]
    mask, corners, confidence, _ = facade_geometry(np.ones(wall.shape), wall, CONFIG,
        dict(plinthMask=plinth, plinthBoundary=boundary))
    result = np.asarray(overlay(image, Image.new('RGB', (80, 40), 'red'), mask, corners, {}, CONFIG))
    assert np.array_equal(result[plinth], np.asarray(image)[plinth])


def test_plain_wall_and_repeated_joints_are_not_plinth():
    for courses in (False, True):
        image, wall = scene(courses=courses)
        mask, boundary = separate_plinth(image, wall, wall, CONFIG)
        assert boundary is None and not mask.any()


def test_ground_floor_transition_is_not_a_plinth_even_with_refined_wall():
    image, building = scene()
    rgb = np.array(image)
    rgb[280:460, 50:750] = (70, 75, 80)
    for wall in (building, building & (np.indices(building.shape)[0] < 285)):
        mask, boundary = separate_plinth(Image.fromarray(rgb), wall, building, CONFIG)
        assert boundary is None and not mask.any()


def test_plinth_does_not_exclude_neighbor_building():
    image, wall = scene(plinth=True)
    building = wall.copy()
    building[390:480, 760:790] = True
    mask, boundary = separate_plinth(image, wall, building, CONFIG)
    assert boundary is not None
    assert mask[400, 400] and not mask[:, 760:].any()


def test_gable_plane_uses_supported_baseline_direction():
    mask = np.zeros((500, 800), np.uint8)
    cv2.fillPoly(mask, [np.int32([[80, 180], [400, 40], [720, 210], [720, 420], [80, 388]])], 1)
    corners = baseline_plane(mask, dict(slope=.05, intercept=384))
    edge = corners[2]-corners[3]
    assert abs(edge[1]/edge[0]-.05) < 1e-5
    assert np.allclose(corners[0], corners[3]-(corners[2]-corners[1]))


def test_bottom_texture_phase_does_not_follow_gable_height():
    # Same lower wall, a taller gable changes the top of the enclosing plane.
    image = Image.new('RGB', (700, 550), (128, 128, 128))
    texture = np.full((64, 128, 3), 200, np.uint8)
    texture[:12] = 40
    outputs = []
    for top in (40, 100):
        mask = np.zeros((550, 700), np.uint8)
        mask[top:500, 50:650] = 1
        corners = np.float32([[50, top], [649, top], [649, 499], [50, 499]])
        outputs.append(np.asarray(overlay(image, Image.fromarray(texture), mask, corners, {}, CONFIG)))
    # Raster canvas rounding allows a subpixel phase difference.
    assert np.abs(outputs[0][400:495, 100:600].astype(float)-outputs[1][400:495, 100:600]).mean() < 3
