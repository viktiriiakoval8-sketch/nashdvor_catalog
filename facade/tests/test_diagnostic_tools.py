import numpy as np
from tools.diagnose_tiled_openings import tiles,shift_boxes
from tools.diagnose_semantic_inputs import measure,summarize
from tools.summarize_tiled_openings import crop_size_guard


def test_tiles_cover_photo_and_shift_preserves_dimensions():
    covered=np.zeros((201,303),bool)
    for x0,y0,x1,y1 in tiles(303,201):
        assert 0<=x0<x1<=303 and 0<=y0<y1<=201
        covered[y0:y1,x0:x1]=True
    assert covered.all()
    assert np.array_equal(shift_boxes([[1,2,11,22]],30,40),[[31,42,41,62]])
    assert shift_boxes([],30,40).shape==(0,4)


def test_metrics_separate_excluded_wall_from_frame_precision():
    labels=np.full((30,30),2,np.uint8)
    labels[5:15,5:15]=3
    labels[15:17,5:15]=6
    mask=np.zeros_like(labels,bool);mask[5:17,5:15]=True
    row=measure(labels,mask)
    summary=summarize([row])
    assert summary['pixelRecall']==1 and summary['instanceRecall']==1
    assert summary['bandPrecision']==1 and summary['strictPrecision']<1
    assert summary['excludedWallFraction']==0
    mask[20:25,20:25]=True
    assert summarize([measure(labels,mask)])['excludedWallFraction']>0


def test_crop_size_guard_rejects_fragment_sized_false_box():
    boxes,scores=crop_size_guard([[0,0,600,600],[100,100,150,180]],[.9,.7],1000,1000)
    assert boxes.tolist()==[[100,100,150,180]] and scores.tolist()==[.7]
