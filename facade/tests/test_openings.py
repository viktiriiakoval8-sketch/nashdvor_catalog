import numpy as np
import json
from pathlib import Path
from PIL import Image

from facade.openings import boxes_to_mask, opening_suggestions
from facade.core import facade_geometry, overlay
CONFIG = json.loads((Path(__file__).parents[1] / 'config.json').read_text(encoding='utf-8'))


def test_ring_diagnostic_rescues_hole_without_changing_default():
    building = np.ones((200,300),bool)
    building[60:120,80:140] = False
    boxes, scores = [[80,60,140,120]], [.8]
    counts, ring_counts = {}, {}
    original, accepted = boxes_to_mask(boxes,scores,building,CONFIG,counts)
    ring, ring_boxes = boxes_to_mask(boxes,scores,building,CONFIG,ring_counts,'ring')
    assert not original.any() and not accepted and counts == {'context':1}
    assert ring[80,100] and ring_boxes == boxes and ring_counts == {'accepted':1}
    assert np.array_equal(original,boxes_to_mask(boxes,scores,building,CONFIG)[0])


def test_diagnostics_count_each_candidate_once():
    building = np.ones((200,300),bool)
    counts = {}
    boxes_to_mask([[20,20,60,60],[20,20,60,60],[0,0,2,2],[70,70,90,90],
                   [float('nan'),0,40,40]], [.9,.8,.9,.1,.9],building,CONFIG,counts)
    assert counts == {'accepted':1,'duplicate':1,'size':1,'score':1,'invalid':1}


def test_detector_filters_building_sized_false_positive_and_nested_duplicates():
    building = np.zeros((400,600), bool)
    building[30:370,50:550] = True
    mask, boxes = boxes_to_mask(
        [[50,30,550,370],[100,100,180,210],[110,110,170,200],
         [1,1,20,20],[200,100,210,150],[float('nan'),0,40,40]],
        [.8,.7,.6,.9,.1,.9], building, CONFIG)
    assert boxes == [[100,100,180,210]]
    assert mask[99,99] and not mask[50,300]


def test_detector_clips_coordinates_and_handles_empty_building():
    building = np.ones((400,600),bool)
    mask, boxes = boxes_to_mask([[-10,-5,70,80],[60,80,40,30]], [.8,.9], building, CONFIG)
    assert boxes == [[0,0,70,80]] and mask[0,0]
    assert not boxes_to_mask([[0,0,70,80]], [.8], ~building, CONFIG)[0].any()


def test_detected_opening_pixels_survive_projection_unchanged():
    building = np.zeros((400,600),bool)
    building[30:370,50:550] = True
    openings, _ = boxes_to_mask([[100,100,180,210]], [.8], building, CONFIG)
    mask, corners, _, _ = facade_geometry(np.ones(building.shape), building, CONFIG,
                                         {'openingMask':openings})
    image = Image.fromarray(np.random.default_rng(5).integers(40,220,(400,600,3),dtype=np.uint8))
    result = overlay(image, Image.new('RGB',(60,30),'red'), mask, corners, {}, CONFIG)
    assert np.array_equal(np.asarray(image)[openings], np.asarray(result)[openings])


def test_low_confidence_suggestions_never_change_automatic_mask():
    building=np.ones((400,600),bool)
    boxes=np.array([[100,100,180,210],[300,100,380,210],[305,105,375,205]])
    scores=np.array([.8,.24,.22])
    mask,accepted=boxes_to_mask(boxes,scores,building,CONFIG)
    suggestions=opening_suggestions(boxes,scores,['window','door','door'],building,CONFIG,accepted)
    assert len(suggestions)==1 and suggestions[0]['kind']=='door'
    assert len(suggestions[0]['points'])==4
    assert all(0<=p['x']<=1 and 0<=p['y']<=1 for p in suggestions[0]['points'])
    assert mask[150,150] and not mask[150,330]
    high_only,_=boxes_to_mask(boxes[:1],scores[:1],building,CONFIG)
    assert np.array_equal(mask,high_only)


def test_cmp_ground_truth_uses_palette_indices(tmp_path):
    from tools.evaluate_cmp_facades import reference_openings
    pixels=np.array([[2,3,4],[7,8,12]],np.uint8)
    image=Image.fromarray(pixels).convert('P')
    image.putpalette([0,0,0]*256)  # RGB appearance must not determine the class.
    path=tmp_path/'labels.png';image.save(path)
    actual=reference_openings(path,(3,2))
    assert np.array_equal(actual,[[False,True,True],[False,False,False]])
