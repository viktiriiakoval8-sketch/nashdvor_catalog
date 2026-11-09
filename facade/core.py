"""Photo validation, automatic semantic mask, projection and catalog-only quotes."""
import io
import math
import hashlib
import logging
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from .structure import opening_mask, separate_plinth, baseline_plane

register_heif_opener()
DISCLAIMER = ('Це попереднє уявлення. Колір, розкладка та точна геометрія можуть '
              'відрізнятися від реального результату. Точний вигляд можна побачити '
              'на зразку, а кошторис уточнюється після замірів.')
RETAKE = ('Не вдалося впевнено виділити стіну. Будь ласка, зробіть фото прямо, '
          'цілком стіни, при денному світлі.')


def validate_photo(raw, config):
    if len(raw) > config['maxBytes']:
        raise ValueError('Фото має бути не більше 10 МБ.')
    try:
        with Image.open(io.BytesIO(raw)) as original:
            if original.format not in {'JPEG', 'PNG', 'HEIF', 'HEIC'}:
                raise ValueError('Оберіть JPG, PNG або HEIC.')
            if original.width * original.height > config['maxPixels']:
                raise ValueError('Зменшіть роздільність фото до 40 мегапікселів.')
            if max(original.size) < config['minLongSide']:
                raise ValueError('Потрібне фото від 1200 px по довгій стороні.')
            image = ImageOps.exif_transpose(original).convert('RGB')
            image.thumbnail((1600, 1600))
            image.info.clear()  # Pillow may otherwise carry EXIF/GPS into the saved PNG.
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Не вдалося відкрити фото. Збережіть його як JPG або PNG.') from exc
    rgb = np.asarray(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    check = cv2.resize(gray, (round(gray.shape[1] * 800 / max(gray.shape)),
                              round(gray.shape[0] * 800 / max(gray.shape))))
    if cv2.Laplacian(check, cv2.CV_64F).var() < config['blurThreshold']:
        raise ValueError('Фото розмите. Протріть камеру й зніміть без руху при денному світлі.')
    if not config['minimumLuminance'] <= float(gray.mean()) <= config['maximumLuminance']:
        raise ValueError('Фото надто темне або світле. Зніміть стіну при рівному денному світлі.')
    if float(np.mean((gray < 8) | (gray > 247))) > .65:
        raise ValueError('Забагато засвічених або темних ділянок. Змініть освітлення.')
    return image


class Segmenter:
    def __init__(self, config):
        import torch
        from transformers import SegformerImageProcessor, SegformerForSemanticSegmentation
        self.torch = torch
        torch.set_num_threads(min(4, torch.get_num_threads()))
        self.processor = SegformerImageProcessor.from_pretrained(config['model'])
        self.model = SegformerForSemanticSegmentation.from_pretrained(config['model']).eval()
        self.wall_ids = [int(k) for k, v in self.model.config.id2label.items() if v.strip() == 'wall']
        self.facade_ids = [int(k) for k, v in self.model.config.id2label.items()
                           if v.strip() in {'wall', 'building', 'house'}]
        self.config = config
        self.opening_ids = [int(k) for k, v in self.model.config.id2label.items()
                            if v.strip() in {'windowpane', 'window', 'door', 'screen door'}]
        if not self.wall_ids:
            raise RuntimeError('Model does not have a wall class')
        self.opening_detector = None
        if config.get('openingDetectorModel'):
            from .openings import OpeningDetector
            try:
                self.opening_detector = OpeningDetector(config)
            except (OSError, ImportError, RuntimeError, ValueError):
                logging.getLogger(__name__).warning('Local opening detector unavailable; manual review required', exc_info=True)

    def predict(self, image, diagnostics=None):
        torch = self.torch
        with torch.inference_mode():
            logits = self.model(**self.processor(images=image, return_tensors='pt')).logits
            probs = logits.softmax(dim=1)[0]
            labels = cv2.resize(probs.argmax(dim=0).numpy().astype('uint8'), image.size,
                                interpolation=cv2.INTER_NEAREST)
            wall = cv2.resize(probs[self.wall_ids].sum(dim=0).numpy(), image.size,
                              interpolation=cv2.INTER_LINEAR)
            building = cv2.resize(probs[self.facade_ids].sum(dim=0).numpy(), image.size,
                                  interpolation=cv2.INTER_LINEAR)
            opening = (cv2.resize(probs[self.opening_ids].sum(dim=0).numpy(), image.size,
                                 interpolation=cv2.INTER_LINEAR) if self.opening_ids else np.zeros_like(wall))
        excluded = opening_mask(labels, opening, self.opening_ids, self.config)
        if diagnostics is not None:
            diagnostics['semanticOpeningMask'] = excluded.copy()
        explicit_wall = np.isin(labels, self.wall_ids)
        candidate = np.isin(labels, self.facade_ids) & (building >= self.config['wallProbability'])
        if diagnostics is not None:
            diagnostics['buildingMask'] = candidate.copy()
            diagnostics['dinoOpeningMask'] = np.zeros_like(candidate)
        opening_status = 'disabled' if not self.config.get('openingDetectorModel') else 'unavailable'
        opening_boxes = []
        opening_suggestions = []
        if self.opening_detector is not None:
            try:
                if diagnostics is None:
                    detected, opening_boxes, opening_suggestions = self.opening_detector.predict(image, candidate)
                else:
                    detected, opening_boxes, opening_suggestions = self.opening_detector.predict(image, candidate, diagnostics)
                    diagnostics['dinoOpeningMask'] = detected.copy()
                excluded |= detected
                opening_status = 'ready'
            except (RuntimeError, ValueError, OSError):
                logging.getLogger(__name__).warning('Opening detection failed; manual review required', exc_info=True)
                opening_status = 'failed'
        if (self.config.get('allowBuildingRefinement', True) and candidate.mean() >= .12
                and explicit_wall.mean() < max(.08, candidate.mean() * .3)):
            refined = refine_building(image, candidate, self.config)
            if refined is not None:
                explicit_wall, wall = refined, building
                method = 'appearance-refined-building'
            else:
                method = 'semantic-wall'
        else:
            method = 'semantic-wall'
        explicit_wall &= ~excluded
        plinth, baseline = separate_plinth(image, explicit_wall, candidate, self.config)
        return wall, explicit_wall & ~plinth, dict(method=method, openingMask=excluded,
                    plinthMask=plinth, plinthBoundary=baseline, wallMask=explicit_wall.copy(),
                    openingDetectorStatus=opening_status, openingBoxes=opening_boxes,
                    openingSuggestions=opening_suggestions)


def refine_building(image, candidate, config):
    """Seeded GrabCut separates the dominant wall surface from a building's roof.

    Building/house classes are never painted directly. Seeds are taken well inside
    the largest semantic component, away from thin roofs/chimneys and openings.
    The wide seed includes both sunny and shaded parts of the wall.
    """
    scale = min(1., config.get('refinementMaxSide', 900) / max(image.size))
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    rgb = np.array(image.resize(size))
    region = cv2.resize(candidate.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST)
    count, components, stats, _ = cv2.connectedComponentsWithStats(region)
    if count <= 1:
        return None
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    region = (components == largest).astype(np.uint8)
    distance = cv2.distanceTransform(region, cv2.DIST_L2, 5)
    if distance.max() < 20:
        return None
    core = distance > distance.max() * .25
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    median = np.median(lab[core], axis=0)
    light_range = max(50., 2 * (median[0] - np.percentile(lab[core, 0], 5)))
    delta = lab - median
    similar = (np.abs(delta[:, :, 0]) < light_range) & (np.linalg.norm(delta[:, :, 1:], axis=2) < 17)
    seeds = core & similar
    if seeds.sum() < region.sum() * .1:
        return None
    initial = np.where(region, cv2.GC_PR_BGD, cv2.GC_BGD).astype(np.uint8)
    initial[(region > 0) & similar] = cv2.GC_PR_FGD
    initial[seeds] = cv2.GC_FGD
    cv2.setRNGSeed(10)
    cv2.grabCut(rgb, initial, None, np.zeros((1, 65)), np.zeros((1, 65)),
                config.get('refinementIterations', 4), cv2.GC_INIT_WITH_MASK)
    refined = np.isin(initial, [cv2.GC_FGD, cv2.GC_PR_FGD]) & (region > 0)
    fraction = refined.sum() / max(1, region.sum())
    # No useful separation, or barely any wall left: do not paint the building.
    if not .2 <= fraction <= .97:
        return None
    return cv2.resize(refined.astype(np.uint8), image.size, interpolation=cv2.INTER_NEAREST).astype(bool)


def facade_geometry(probability, semantic_wall, config, detection=None):
    safe = (semantic_wall & (probability >= config['wallProbability'])).astype('uint8')
    for name in ('openingMask', 'plinthMask'):
        exclusion = (detection or {}).get(name)
        if exclusion is not None:
            safe[exclusion > 0] = 0
    # Erosion protects opening boundaries. Never close/fill holes over windows or doors.
    safe = cv2.erode(safe, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(safe, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, None, 0., {}
    contour = max(contours, key=cv2.contourArea)
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    corners = None
    for epsilon in (.015, .025, .04, .06):
        approx = cv2.approxPolyDP(hull, epsilon * perimeter, True)
        if len(approx) == 4:
            corners = approx[:, 0, :].astype(np.float32)
            break
    approximate_plane = corners is None or any(
        cv2.pointPolygonTest(corners.reshape(-1, 1, 2), (float(p[0]), float(p[1])), True) < -2
        for p in hull[:, 0, :])
    if approximate_plane:
        # Gables are often pentagons. A rectangle defines texture coordinates,
        # while the full semantic mask (not this rectangle) defines painted pixels.
        corners = cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float32)
    center = corners.mean(axis=0)
    corners = corners[np.argsort(np.arctan2(corners[:, 1]-center[1], corners[:, 0]-center[0]))]
    corners = np.roll(corners, -np.argmin(corners.sum(axis=1)), axis=0)
    polygon = np.zeros_like(safe)
    cv2.fillConvexPoly(polygon, cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.int32), 1)
    count, components, stats, _ = cv2.connectedComponentsWithStats(safe)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = (components == largest).astype(np.uint8)
    baseline = (detection or {}).get('plinthBoundary')
    if baseline is not None:
        corners = baseline_plane(mask, baseline)
    polygon_area = max(1, int(polygon.sum()))
    coverage = float(mask.mean())
    if coverage < .08:
        return None, None, 0., {'reason': 'wall_too_small'}
    edges = np.linalg.norm(corners - np.roll(corners, -1, axis=0), axis=1)
    perspective = float(min(edges[0], edges[2]) / max(edges[0], edges[2]) *
                        min(edges[1], edges[3]) / max(edges[1], edges[3]))
    if min(edges) < 40 or perspective < .15:
        return None, None, 0., {'reason': 'extreme_perspective'}
    certainty = float(probability[mask > 0].mean())
    fill = float(mask.sum() / polygon_area)
    fit = min(1., float(cv2.contourArea(contour)) / polygon_area)
    confidence = .35 * certainty + .2 * min(1., coverage / .45) + .2 * fit + .15 * fill + .1 * perspective
    # Cropped walls / multiple wall planes cannot be confidently projected.
    border = bool(mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any())
    if border:
        confidence = min(confidence, .65)
    # More than one large component / non-planar facade is intentionally rejected.
    large = [c for c in contours if cv2.contourArea(c) > .25 * cv2.contourArea(contour)]
    if len(large) > 1:
        confidence = min(confidence, .49)
    if approximate_plane:
        confidence = min(confidence, .74)
    method = (detection or {}).get('method', 'semantic-wall')
    if method == 'appearance-refined-building':
        confidence = min(confidence, config.get('refinementConfidenceCap', .74))
    return mask, corners, round(confidence, 4), dict(coverage=coverage, certainty=certainty,
                    cornerFit=fit, visibleFraction=fill, perspective=perspective, cropped=border,
                    approximatePlane=approximate_plane, method=method,
                    plinthDetected=baseline is not None, plinthBoundary=baseline,
                    openingPixels=int(np.count_nonzero((detection or {}).get('openingMask', []))),
                    openingDetectorStatus=(detection or {}).get('openingDetectorStatus', 'disabled'),
                    openingBoxes=(detection or {}).get('openingBoxes', []),
                    textureAnchor='bottom-left')


def plane_aspect(corners):
    """Width/height of the wall plane estimated from its quad (corners: TL, TR, BR, BL).

    Averages opposite edges, so it is exact for a frontal view and a reasonable
    estimate for a mild angle. It is NOT a physical measurement: a strongly
    oblique photo still yields only the on-screen proportion of the wall.
    """
    top_left, top_right, bottom_right, bottom_left = (np.asarray(c, dtype=np.float64) for c in corners)
    width = (np.linalg.norm(top_right - top_left) + np.linalg.norm(bottom_right - bottom_left)) / 2
    height = (np.linalg.norm(bottom_left - top_left) + np.linalg.norm(bottom_right - top_right)) / 2
    return float(np.clip(width / max(height, 1.), .25, 6.))


def brick_fragments(texture):
    result = _brick_fragments(texture)
    if result is None:
        result = _brick_fragments(texture, 1) or _brick_fragments(texture, -1)
    return result


def _brick_fragments(texture, forced_polarity=None):
    """Extract complete bricks only when a regular mortar grid is clearly visible."""
    sample = texture.copy()
    sample.thumbnail((1024,1024))
    rgb = np.asarray(sample)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    def joints(profile, polarity=None):
        center = float(np.median(profile))
        if polarity is None:
            polarity = 1 if profile.max()-center >= center-profile.min() else -1
        contrast = polarity*(profile-center)
        if contrast.max() < 15:
            return [], polarity
        indices = np.flatnonzero(contrast > .6*contrast.max())
        bands = np.split(indices,np.flatnonzero(np.diff(indices)>1)+1)
        return [float(group.mean()) for group in bands if len(group)], polarity
    ys, polarity = joints(gray.mean(axis=1), forced_polarity)
    if len(ys) < 3:
        return None
    gaps = np.diff(ys)
    brick_h = float(np.median(gaps))
    if brick_h < 8 or np.max(np.abs(gaps-brick_h)) > .15*brick_h:
        return None
    boxes = []
    for top,bottom in zip(ys,ys[1:]):
        margin = max(2,round((bottom-top)*.15))
        xs,_ = joints(gray[round(top)+margin:round(bottom)-margin].mean(axis=0),polarity)
        for left,right in zip(xs,xs[1:]):
            if 1.2 <= (right-left)/brick_h <= 6:
                boxes.append((left,top,right,bottom))
    if len(boxes) < 2:
        return None
    brick_w = float(np.median([right-left for left,top,right,bottom in boxes]))
    pieces = [sample.crop(tuple(round(v) for v in box)) for box in boxes
              if abs((box[2]-box[0])-brick_w) <= .15*brick_w]
    return (pieces, sample.width/brick_w, brick_w/brick_h) if len(pieces)>=2 else None


def texture_canvas(tex, width, height, panel, config):
    """Keep the original layout; transfer sampled brick colors within brick bodies."""
    cell_h, cell_w = tex.shape[:2]
    offset = (-height) % cell_h
    canvas = np.tile(tex, (math.ceil((height+offset)/cell_h), math.ceil(width/cell_w), 1))[offset:offset+height, :width].copy()
    if not config.get('randomizeBrickColors', True) or brick_fragments(Image.fromarray(tex)) is None:
        return canvas
    profile = cv2.cvtColor(tex, cv2.COLOR_RGB2GRAY).mean(axis=1)
    center = float(np.median(profile))
    polarity = 1 if profile.max()-center >= center-profile.min() else -1
    threshold = center + .6*((profile.max() if polarity==1 else profile.min())-center)
    def bodies(rgb):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        body = gray < threshold if polarity==1 else gray > threshold
        return cv2.connectedComponentsWithStats(body.astype(np.uint8))
    def regions(rgb):
        count, labels, stats, _ = bodies(rgb)
        for index in range(1,count):
            x,y,w,h,area = stats[index]
            if area >= max(5,cell_w*cell_h*.002):
                yield x,y,w,h,labels[y:y+h,x:x+w]==index
    palette = []
    for x,y,w,h,region in regions(tex):
        palette.append(np.median(tex[y:y+h,x:x+w][region],axis=0))
    if len(palette)<2:
        return canvas
    digest = hashlib.sha256(str(config.get('brickColorSeed', 1)).encode()+b'\0'+
                            str(panel.get('id', '')).encode()+b'\0'+tex.tobytes()).digest()
    seed = int.from_bytes(digest[:8],'big')
    # Region selection is anchored to the bottom, independent of component numbering.
    for x,y,w,h,region in regions(canvas):
        rng = np.random.default_rng(np.random.SeedSequence([seed,int(x),int(height-y-h)]))
        donor = palette[int(rng.integers(len(palette)))]
        patch = canvas[y:y+h,x:x+w]
        original = patch[region].astype(np.float32)
        median = np.maximum(1.,np.median(original,axis=0))
        patch[region] = np.clip(np.rint(original*(donor/median)),0,255).astype(np.uint8)
    return canvas


def tile_dimensions(canvas_width, panel, config):
    """One shared relative scale across materials; millimetres set face proportions."""
    tile = panel['tileSize']
    unit = canvas_width/(config.get('templateTileColumns',16)*250.)
    return (max(1,round(tile['width']*unit)),max(1,round(tile['height']*unit)),
            max(1,round(canvas_width/config.get('templateTileColumns',16)*config.get('templateJointFraction',.035))))


def sized_tile_canvas(texture, width, height, panel, config):
    """A fixed grid of equal faces. Randomness controls only their color."""
    detected = brick_fragments(texture)
    if detected is None:
        if np.asarray(texture).std(axis=(0,1)).max() < 2:
            pieces = [texture]
        else:
            raise ValueError('Для точних пропорцій плитки потрібна підготовлена фронтальна фактура.')
    else:
        pieces = detected[0]
    faces = []
    borders = []
    for piece in pieces:
        rgb = np.asarray(piece)
        borders.extend((rgb[0],rgb[-1]))
        # Remove the sampled mortar frame before resizing one complete tile face.
        dx,dy = max(1,round(piece.width*.05)),max(1,round(piece.height*.08))
        faces.append(piece.crop((dx,dy,piece.width-dx,piece.height-dy)))
    grout = np.median(np.concatenate(borders),axis=0).astype(np.uint8)
    tile_w,tile_h,joint = tile_dimensions(width,panel,config)
    canonical = np.asarray(faces[0].resize((tile_w,tile_h))).astype(np.float32)
    base = np.maximum(1.,np.median(canonical,axis=(0,1)))
    palette = [np.median(np.asarray(face),axis=(0,1)) for face in faces]
    colored = [np.clip(np.rint(canonical*(color/base)),0,255).astype(np.uint8) for color in palette]
    digest = hashlib.sha256(str(config.get('brickColorSeed',1)).encode()+b'\0'+
                            str(panel.get('id','')).encode()+b'\0'+canonical.tobytes()).digest()
    seed = int.from_bytes(digest[:8],'big')
    canvas = np.empty((height,width,3),np.uint8)
    canvas[:] = grout
    pitch_x,pitch_y = tile_w+joint,tile_h+joint
    for row in range(math.ceil(height/pitch_y)):
        bottom = height-row*pitch_y
        top = bottom-tile_h
        phase = pitch_x//2 if row%2 else 0
        for col,left in enumerate(range(-phase,width,pitch_x)):
            right = left+tile_w
            x0,x1,y0,y1 = max(0,left),min(width,right),max(0,top),min(height,bottom)
            if x0>=x1 or y0>=y1:
                continue
            if config.get('randomizeBrickColors',True):
                rng = np.random.default_rng(np.random.SeedSequence([seed,row,col]))
                color = int(rng.integers(len(colored)))
            else:
                color = (row+col)%len(colored)
            canvas[y0:y1,x0:x1] = colored[color][y0-top:y1-top,x0-left:x1-left]
    return canvas


def overlay(image, texture, mask, corners, panel, config):
    texture = texture.convert('RGB')
    # Known tile sizes use one uniform grid and shared relative scale. Unknown sizes
    # retain the legacy swatch template. No wall dimensions or area are inferred.
    repeat = config['templateRepeats']
    tile = panel.get('tileSize')
    sized = isinstance(tile,dict) and tile.get('width',0)>0 and tile.get('height',0)>0
    w = 2048 if sized else 1024
    h = max(64, min(8192 if sized else 4096, round(w / plane_aspect(corners))))
    if sized:
        canvas = sized_tile_canvas(texture,w,h,panel,config)
    else:
        cell_w = max(32,round(w/repeat))
        cell_h = max(16,min(512,round(cell_w/(texture.width/texture.height))))
        tex = np.asarray(texture.resize((cell_w,cell_h)))
        canvas = texture_canvas(tex,w,h,panel,config)
    matrix = cv2.getPerspectiveTransform(np.float32([[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]]), corners)
    projected = cv2.warpPerspective(canvas, matrix, image.size, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    original = np.asarray(image).astype(np.float32)
    luminance = cv2.cvtColor(original / 255, cv2.COLOR_RGB2GRAY)
    light = cv2.GaussianBlur(luminance, (0, 0), 9)
    reference = max(.05, float(np.median(light[mask > 0])))
    projected *= np.clip(light / reference, .45, 1.5)[:, :, None]
    # Mask remains binary: excluded source pixels are byte-for-byte unchanged in PNG.
    result = np.where(mask[:, :, None] > 0, np.clip(projected, 0, 255), original).astype('uint8')
    return Image.fromarray(result)


def quote(panel, base, mm, area, config, now=None):
    now = now or datetime.now(ZoneInfo('Europe/Kyiv'))
    output = dict(date=now.date().isoformat(), validUntil=(now+timedelta(days=config['quoteDays'])).date().isoformat(),
                  area=area, currency='UAH', accessories=None, delivery=None, installation=None,
                  panels=None, unitPrice=None, panelCount=None, reason=None)
    if area is None:
        output['reason'] = 'Введіть площу або оберіть «Не знаю». За фото площу не визначаємо.'
        return output
    if not math.isfinite(area) or not 0 < area <= 100000:
        raise ValueError('Площа має бути більшою за 0 і не перевищувати 100 000 м².')
    key = f'{base}_{mm}'
    price = panel.get('price', {}).get(key)
    if not panel.get('available') or price is None:
        output['reason'] = 'Основа, товщина або ціна уточнюється.'
        return output
    price = Decimal(str(price))
    size = Decimal(str(area))
    if panel['currency'] == 'грн/панель':
        panel_area = panel.get('panelArea')
        if not panel_area or panel_area <= 0:
            output['reason'] = 'Площа однієї панелі уточнюється.'
            return output
        count = math.ceil(size / Decimal(str(panel_area)))
        total = count * price
        unit = price / Decimal(str(panel_area))
        output.update(panelCount=count, panelArea=panel_area, pricePerPanel=float(price),
                      formula='ceil(площа / площа панелі) × ціна панелі; без запасу на підрізку')
    elif panel['currency'] == 'грн/м²':
        total, unit = size * price, price
        output['formula'] = 'площа × ціна за м²; без запасу на підрізку'
    else:
        output['reason'] = 'Одиниця ціни уточнюється.'
        return output
    output.update(panels=float(total.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)),
                  unitPrice=float(unit.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)))
    return output
