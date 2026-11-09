"""Conservative structural exclusions; these rules do not train the model."""
import cv2
import numpy as np


def opening_mask(labels, probability, opening_ids, config):
    raw = np.isin(labels, opening_ids) | (probability >= config.get('openingProbability', .4))
    count, components, stats, _ = cv2.connectedComponentsWithStats(raw.astype(np.uint8))
    result = np.zeros(labels.shape, np.uint8)
    margin = max(2, round(max(labels.shape) * config.get('openingMarginFraction', .004)))
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if area < max(9, labels.size * .00005):
            continue
        # A conservative enclosing box protects frames and sills as well as glass.
        result[max(0, y-margin):y+h+margin, max(0, x-margin):x+w+margin] = 1
    return result.astype(bool)


def separate_plinth(image, wall, building, config):
    empty = np.zeros(wall.shape, bool)
    count, components, stats, _ = cv2.connectedComponentsWithStats(wall.astype(np.uint8))
    if count < 2:
        return empty, None
    main = components == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    ys, xs = np.nonzero(main)
    x0, x1 = np.quantile(xs, [.01, .99]).astype(int)
    y0, y1 = int(ys.min()), int(ys.max())
    width, height = x1-x0, y1-y0
    if width < 80 or height < 80:
        return empty, None
    # Reference the building component overlapping this wall, not the refined
    # surface: GrabCut can discard a dark ground floor before this step.
    n_buildings, building_components = cv2.connectedComponents(building.astype(np.uint8))
    overlap = np.bincount(building_components[main], minlength=n_buildings)
    overlap[0] = 0
    if not overlap.any():
        return empty, None
    subject = building_components == int(overlap.argmax())
    by, bx = np.nonzero(subject)
    building_top, building_bottom = np.quantile(by, [.01, .99])
    max_height = float(config.get('plinthMaxHeightFraction', .25))
    minimum_seam = building_bottom - max_height * (building_bottom-building_top)
    rgb = np.asarray(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 50, 120)
    edges[:round(y0 + .55*height)] = 0
    edges[min(len(edges), round(y1 + .08*height)):] = 0
    edges[:, :x0] = 0
    edges[:, x1:] = 0
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=max(20, round(width*.12)),
                            minLineLength=round(width*.5), maxLineGap=round(width*.04))
    if lines is None:
        return empty, None
    candidates = []
    band, gap = max(5, round(height*.025)), max(2, round(height*.005))
    lo, hi = x0+round(width*.08), x1-round(width*.08)
    for x, y, xx, yy in np.asarray(lines).reshape(-1, 4):
        if abs(xx-x) < width*.5 or abs(yy-y) > max(2, abs(xx-x)*.08):
            continue
        slope = (yy-y) / (xx-x)
        line_y = y + (np.arange(lo, hi)-x)*slope
        # A floor separator is not a plinth. Ambiguous tall bases are left for
        # the manual line tool instead of automatically hiding a whole storey.
        if line_y.min() < minimum_seam:
            continue
        offsets = np.arange(gap, band+1)[:, None]
        above_y = np.rint(line_y-offsets).astype(int)
        below_y = np.rint(line_y+offsets).astype(int)
        if above_y.min() < 0 or below_y.max() >= wall.shape[0]:
            continue
        above = np.median(lab[above_y, np.arange(lo, hi)], axis=(0, 1))
        below = np.median(lab[below_y, np.arange(lo, hi)], axis=(0, 1))
        delta = float(np.linalg.norm(above-below))
        # Repeated mortar joints have similar material on both sides.
        if delta < config.get('plinthMaterialDelta', 18):
            continue
        if building[below_y, np.arange(lo, hi)].mean() < .65:
            continue
        candidates.append((float(line_y.mean()), float(slope), float(y-slope*x), delta))
    if not candidates:
        return empty, None
    # Choose the upper edge of the supported transition, retaining the trim too.
    _, slope, intercept, delta = min(candidates)
    grid_y, grid_x = np.indices(wall.shape)
    plinth = subject & (grid_y >= slope*grid_x + intercept)
    return plinth, dict(slope=slope, intercept=intercept, materialDelta=delta)


def baseline_plane(mask, baseline):
    """An enclosing plane aligned to a supported wall/plinth seam, including gables."""
    ys, xs = np.nonzero(mask)
    tangent = np.array([1., baseline['slope']], np.float32)
    tangent /= np.linalg.norm(tangent)
    normal = np.array([-tangent[1], tangent[0]], np.float32)
    points = np.column_stack((xs, ys)).astype(np.float32)
    u, v = points @ tangent, points @ normal
    left, right, top, bottom = u.min(), u.max(), v.min(), v.max()
    return np.array([tangent*left+normal*top, tangent*right+normal*top,
                     tangent*right+normal*bottom, tangent*left+normal*bottom], np.float32)
