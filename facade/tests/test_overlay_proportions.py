"""Tile proportions on the wall plane (facade/core.py: plane_aspect, overlay).

Runs with pytest or `python tests/test_overlay_proportions.py`. Needs numpy, OpenCV and Pillow only.
"""
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    import pillow_heif  # noqa: F401
except ImportError:  # lightweight environments without HEIC support
    sys.modules['pillow_heif'] = types.SimpleNamespace(register_heif_opener=lambda: None)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from facade.core import overlay, plane_aspect, texture_canvas, brick_fragments, sized_tile_canvas, tile_dimensions  # noqa: E402

CONFIG = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_text(encoding='utf-8'))
TILE_ASPECT = 2.0   # synthetic tile is 200x100: twice as wide as high


def wall(x0, y0, x1, y1):
    return np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def tile_texture():
    texture = np.full((100, 200, 3), 200, np.uint8)
    texture[:, :10] = 40      # dark vertical joint at the left edge of every tile
    texture[:5, :] = 40       # dark horizontal joint at the top edge of every tile
    return Image.fromarray(texture)


def rendered_period(profile):
    """Dominant spatial period (px) of a 1-D luminance profile, via a zero-padded FFT."""
    profile = (profile - profile.mean()) * np.hanning(len(profile))
    size = len(profile) * 16
    spectrum = np.abs(np.fft.rfft(profile, n=size))
    low, high = int(size / (len(profile) / 2)), int(size / 16)
    return size / (low + int(np.argmax(spectrum[low:high])))


def measured_tile_aspect(corners):
    image = Image.new('RGB', (1600, 1000), (128, 128, 128))   # uniform light: no shading influence
    (x0, y0), (x1, y1) = corners[0].astype(int), corners[2].astype(int)
    mask = np.zeros((1000, 1600), np.uint8)
    mask[y0:y1, x0:x1] = 1
    out = np.asarray(overlay(image, tile_texture(), mask, corners, {}, dict(CONFIG, randomizeBrickColors=False)).convert('L'), np.float64)
    inner = out[y0 + 25:y1 - 25, x0 + 25:x1 - 25]
    return rendered_period(inner.mean(axis=0)) / rendered_period(inner.mean(axis=1))


def test_plane_aspect_rectangle_and_trapezoid():
    assert abs(plane_aspect(wall(0, 0, 1200, 400)) - 3.0) < 1e-6
    assert abs(plane_aspect(wall(0, 0, 400, 900)) - 400 / 900) < 1e-6
    trapezoid = np.float32([[100, 0], [900, 0], [1000, 400], [0, 400]])   # wider at the bottom
    assert abs(plane_aspect(trapezoid) - 900 / 412.31) < 0.01
    assert plane_aspect(wall(0, 0, 5000, 100)) == 6.0 and plane_aspect(wall(0, 0, 10, 900)) == 0.25


def test_tiles_keep_their_proportions_on_wide_narrow_and_square_walls():
    for name, corners in {'wide': wall(200, 300, 1400, 700), 'narrow': wall(600, 50, 1000, 950),
                          'square': wall(300, 100, 1100, 900)}.items():
        ratio = measured_tile_aspect(corners)
        assert abs(ratio / TILE_ASPECT - 1) < .06, f'{name}: tile aspect {ratio:.2f}, expected {TILE_ASPECT}'


def test_columns_across_wall_stay_templateRepeats():
    corners = wall(200, 300, 1400, 700)
    image = Image.new('RGB', (1600, 1000), (128, 128, 128))
    mask = np.zeros((1000, 1600), np.uint8)
    mask[300:700, 200:1400] = 1
    out = np.asarray(overlay(image, tile_texture(), mask, corners, {}, dict(CONFIG, randomizeBrickColors=False)).convert('L'), np.float64)
    columns = 1200 / rendered_period(out[325:675, 225:1375].mean(axis=0))
    assert abs(columns - CONFIG['templateRepeats']) < .6


def test_pixels_outside_the_mask_are_unchanged():
    image = Image.fromarray(np.random.default_rng(1).integers(0, 255, (1000, 1600, 3), dtype=np.uint8))
    mask = np.zeros((1000, 1600), np.uint8)
    mask[300:700, 200:1400] = 1
    out = np.asarray(overlay(image, tile_texture(), mask, wall(200, 300, 1400, 700), {}, CONFIG))
    assert np.array_equal(out[mask == 0], np.asarray(image)[mask == 0])


def mixed_bricks():
    from PIL import ImageDraw
    source = Image.new('RGB',(420,240),(225,220,210))
    draw = ImageDraw.Draw(source)
    for row in range(6):
        offset = 60 if row%2 else 0
        for column in range(-1,5):
            x = column*120+offset
            draw.rectangle((x+3,row*40+3,x+116,row*40+36), fill=(100+row*12,60,40))
    return np.asarray(source)


def test_random_colors_are_reproducible_and_preserve_every_mortar_pixel():
    texture = mixed_bricks()
    first = texture_canvas(texture,1024,512,{'id':'brick'},CONFIG)
    second = texture_canvas(texture,1024,512,{'id':'brick'},CONFIG)
    assert np.array_equal(first,second)
    regular = texture_canvas(texture,1024,512,{'id':'brick'},dict(CONFIG,randomizeBrickColors=False))
    assert not np.array_equal(first,regular)
    assert not np.array_equal(first,texture_canvas(texture,1024,512,{'id':'brick'},dict(CONFIG,brickColorSeed=2)))
    mortar = np.all(regular==[225,220,210],axis=2)
    assert np.array_equal(first[mortar],regular[mortar])
    assert np.array_equal(np.all(first==[225,220,210],axis=2),mortar)
    assert set(map(tuple,first.reshape(-1,3))) <= set(map(tuple,texture.reshape(-1,3)))


def test_random_layout_lower_rows_do_not_change_when_wall_grows_upward():
    texture = mixed_bricks()
    short = texture_canvas(texture,1024,425,{'id':'brick'},CONFIG)
    tall = texture_canvas(texture,1024,785,{'id':'brick'},CONFIG)
    assert np.array_equal(short[40:],tall[-385:])


def test_complete_bricks_are_extracted_between_mortar_courses():
    from PIL import ImageDraw
    source = Image.new('RGB',(420,240),(225,220,210))
    draw = ImageDraw.Draw(source)
    for row in range(6):
        offset = 60 if row%2 else 0
        for column in range(-1,5):
            x = column*120+offset
            draw.rectangle((x+3,row*40+3,x+116,row*40+36), fill=(100+row*12,60,40))
    result = brick_fragments(source)
    assert result is not None
    pieces,columns,aspect = result
    assert len(pieces)>=2 and abs(aspect-3)<.15 and abs(columns-3.5)<.2
    for piece in pieces:
        pixels = np.asarray(piece)
        assert pixels[0].mean()>150 and pixels[-1].mean()>150


def test_unstructured_texture_is_not_mistaken_for_a_brick_grid():
    assert brick_fragments(Image.new('RGB',(200,200),(120,90,70))) is None


def test_fixed_tile_faces_are_identical_and_keep_mm_proportions_after_random_colors():
    import cv2
    source = Image.fromarray(mixed_bricks())
    for size in (dict(width=250,height=60),dict(width=245,height=65)):
        panel = dict(id='same-geometry',tileSize=size)
        regular = sized_tile_canvas(source,2048,700,panel,dict(CONFIG,randomizeBrickColors=False))
        random = sized_tile_canvas(source,2048,700,panel,CONFIG)
        assert not np.array_equal(regular,random)
        grout = np.all(regular==[225,220,210],axis=2)
        assert np.array_equal(random[grout],regular[grout])
        assert np.array_equal(np.all(random==[225,220,210],axis=2),grout)
        _,_,stats,_ = cv2.connectedComponentsWithStats((~grout).astype(np.uint8))
        full = [s for s in stats[1:] if s[0]>0 and s[1]>0 and s[0]+s[2]<2048 and s[1]+s[3]<700]
        expected_w,expected_h,_ = tile_dimensions(2048,panel,CONFIG)
        assert len(full)>50
        assert all(s[2]==expected_w and s[3]==expected_h for s in full)
        assert abs((expected_w/expected_h)/(size['width']/size['height'])-1)<.02


def test_fixed_grid_is_independent_of_source_photo_framing():
    source = Image.fromarray(mixed_bricks())
    panel = dict(id='same',tileSize=dict(width=250,height=60))
    first = sized_tile_canvas(source,2048,700,panel,CONFIG)
    second = sized_tile_canvas(source.resize((800,400)),2048,700,panel,CONFIG)
    assert np.array_equal(np.all(first==[225,220,210],axis=2),np.all(second==[225,220,210],axis=2))


if __name__ == '__main__':
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn(); print('PASS', name)
            except Exception as exc:
                failed += 1; print('FAIL', name, repr(exc))
    sys.exit(1 if failed else 0)
