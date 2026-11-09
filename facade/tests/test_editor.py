import numpy as np
import pytest
from pydantic import ValidationError

from facade.editor import Correction, corrected_mask


def element(kind, coords):
    return dict(kind=kind, points=[dict(x=x,y=y) for x,y in coords])


def test_manual_facade_restores_false_plinth_but_keeps_openings():
    automatic = np.zeros((400,600), bool)
    automatic[50:360,40:560] = True
    wrong_plinth = automatic.copy()
    wrong_plinth[:210] = False
    body = Correction(elements=[
        element('facade',[(.1,.15),(.5,.05),(.9,.15),(.9,.9),(.1,.9)]),
        element('window',[(.2,.25),(.4,.5)]), element('door',[(.6,.65),(.7,.9)]),
        element('plinth',[(.1,.85),(.9,.87)])])
    mask,corners,openings,plinth,explicit = corrected_mask((600,400),automatic,
        np.zeros_like(automatic),wrong_plinth,body)
    assert explicit and mask[300,150] and not mask[140,180] and not mask[300,390]
    assert plinth[350,150] and not plinth[300,150]
    assert openings[140,180] and openings[300,390]
    assert not mask[openings | plinth].any()


@pytest.mark.parametrize('items',[
    [element('window',[(.2,.2),(.2,.5)])],
    [element('door',[(0,0),(2,1)])],
    [element('plinth',[(.2,.8),(.8,.8),(.4,.8)])],
    [element('facade',[(.1,.1),(.9,.9),(.1,.9),(.9,.1)])],
    [element('facade',[(.1,.1),(.9,.9)])],
    [element('plinth',[(.1,.8),(.9,.8)])]*2,
])
def test_invalid_annotations_are_rejected(items):
    with pytest.raises(ValidationError):
        Correction(elements=items)


def test_excessive_or_nonfinite_coordinates_are_rejected():
    with pytest.raises(ValidationError):
        Correction(elements=[element('window',[(.1,.1),(.2,.2)])]*65)
    with pytest.raises(ValidationError):
        Correction(elements=[element('window',[(float('nan'),.1),(.2,.2)])])


def test_empty_or_all_excluded_wall_is_rejected():
    empty = np.zeros((100,200),bool)
    with pytest.raises(ValueError):
        corrected_mask((200,100),empty,empty,empty,Correction())


def test_default_training_consent_is_false():
    assert not Correction().trainingConsent


def test_closed_outline_and_reverse_plinth_are_normalized():
    body = Correction(elements=[element('facade',[(.1,.1),(.9,.1),(.9,.9),(.1,.9),(.1,.1)]),
                                element('plinth',[(.9,.8),(.5,.81),(.1,.8)])])
    assert len(body.elements[0].points) == 4
    assert body.elements[1].points[0].x == .1


@pytest.mark.parametrize('kind',['window','door','exclude'])
def test_polygon_exclusions_preserve_shape_instead_of_bounding_box(kind):
    wall = np.ones((400,600),bool)
    empty = np.zeros_like(wall)
    body = Correction(elements=[element(kind,[(.2,.2),(.6,.2),(.2,.6),(.2,.2)])])
    mask,_,excluded,_,_ = corrected_mask((600,400),wall,empty,empty,body)
    assert excluded[100,150] and not mask[100,150]
    assert not excluded[220,330] and mask[220,330]


def test_manual_outline_overrides_false_automatic_plinth_and_keeps_perspective():
    automatic = np.ones((400,600),bool)
    wrong_plinth = automatic.copy()
    wrong_plinth[:200] = False
    body = Correction(elements=[element('facade',[(.2,.1),(.8,.2),(.9,.9),(.1,.9)])])
    mask,corners,_,plinth,_ = corrected_mask((600,400),automatic,
        np.zeros_like(automatic),wrong_plinth,body)
    assert mask[300,300] and not plinth.any()
    assert corners[1,1] > corners[0,1]+30
