"""Validated, normalized user annotations and deterministic mask corrections."""
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .structure import baseline_plane

TRAINING_CONSENT = ('Дозволяю використовувати це фото та мої виділення для перевірки й навчання '
                    'моделі примірки NASH DVOR протягом строку зберігання фото (до 90 днів). '
                    'Це необов’язково; фото не публікується. Згоду можна відкликати тут.')


class Point(BaseModel):
    model_config = ConfigDict(extra='forbid')
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)


class Element(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['window', 'door', 'plinth', 'facade', 'exclude']
    points: list[Point] = Field(min_length=2, max_length=32)

    @model_validator(mode='after')
    def geometry(self):
        legacy_rect = self.kind in {'window', 'door'} and len(self.points) == 2
        if self.kind != 'plinth' and not legacy_rect:
            # Clicking the first point to close an outline is a normal gesture.
            # Strip redundant vertices before checking for intersections.
            cleaned = []
            for point in self.points:
                if not cleaned or np.hypot(point.x-cleaned[-1].x, point.y-cleaned[-1].y) > 1e-6:
                    cleaned.append(point)
            if len(cleaned) > 1 and np.hypot(cleaned[-1].x-cleaned[0].x,
                                             cleaned[-1].y-cleaned[0].y) < .003:
                cleaned.pop()
            self.points = cleaned
        points = np.array([(p.x, p.y) for p in self.points], np.float32)
        if legacy_rect:
            if np.any(np.abs(points[0]-points[1]) < .003):
                raise ValueError('Проєм має бути прямокутником ненульового розміру.')
        elif self.kind == 'plinth':
            if np.all(np.diff(points[:, 0]) < -1e-6):
                self.points.reverse()
                points = points[::-1]
            if len(points) > 16 or np.any(np.diff(points[:, 0]) <= 1e-6):
                raise ValueError('Лінія цоколя повертається назад або має точки одна над одною. Перемістіть ці точки по горизонталі.')
        else:
            if len(points) < 3:
                raise ValueError('Для контуру потрібно щонайменше три різні точки.')
            # Reject crossed outlines rather than silently filling ambiguous areas.
            def cross(a, b, c):
                d, e = b-a, c-a
                return float(d[0]*e[1]-d[1]*e[0])
            n = len(points)
            for i in range(n):
                a, b = points[i], points[(i+1) % n]
                if np.linalg.norm(b-a) <= 1e-6:
                    raise ValueError('Точки контуру збігаються.')
                for j in range(i+1, n):
                    if j == i+1 or (i == 0 and j == n-1):
                        continue
                    c, d = points[j], points[(j+1) % n]
                    if cross(a,b,c)*cross(a,b,d) <= 0 and cross(c,d,a)*cross(c,d,b) <= 0:
                        # Bounding boxes distinguish disjoint collinear segments.
                        if np.all(np.maximum(np.minimum(a,b),np.minimum(c,d)) <=
                                  np.minimum(np.maximum(a,b),np.maximum(c,d))):
                            raise ValueError('Контур не повинен перетинати сам себе.')
            if abs(cv2.contourArea(points)) < (.02 if self.kind == 'facade' else 1e-6):
                raise ValueError('Контур займає менше 2% фото. Обведіть усю стіну.' if self.kind == 'facade'
                                 else 'Область надто мала або її точки лежать на одній лінії.')
        return self


def correction_error_detail(errors, body):
    """Give an actionable element number without exposing input or contact data."""
    labels = {'window': 'Вікно', 'door': 'Двері', 'facade': 'Контур фасаду', 'plinth': 'Цоколь', 'exclude': 'Інша ділянка'}
    elements = body.get('elements', []) if isinstance(body, dict) else []
    messages, invalid = [], []
    for error in errors[:8]:
        loc = list(error.get('loc', ()))
        prefix = 'Виділення'
        if 'elements' in loc:
            offset = loc.index('elements')+1
            if offset < len(loc) and isinstance(loc[offset], int):
                index = loc[offset]
                invalid.append(index)
                item = elements[index] if isinstance(elements, list) and index < len(elements) else {}
                kind = item.get('kind') if isinstance(item, dict) else None
                prefix = f'Область №{index+1} «{labels.get(kind, "Виділення")}»'
        message = error.get('msg', '').removeprefix('Value error, ')
        if 'points' in loc and error.get('type') != 'value_error':
            message = 'Перевірте кількість точок і координати: точки мають залишатися в межах фото.'
        elif error.get('type') != 'value_error':
            message = 'Некоректні дані виділення. Перевірте область або створіть її заново.'
        messages.append(f'{prefix}: {message}')
    return dict(detail='\n'.join(messages), invalidElements=sorted(set(invalid)))


class Correction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: str | None = Field(default=None, max_length=36)
    elements: list[Element] = Field(default_factory=list, max_length=64)
    trainingConsent: bool = Field(default=False, strict=True)

    @model_validator(mode='after')
    def single_regions(self):
        for kind in ('facade', 'plinth'):
            if sum(e.kind == kind for e in self.elements) > 1:
                raise ValueError('Допустима лише одна область фасаду й одна лінія цоколя.')
        return self


def corrected_mask(size, automatic, automatic_openings, automatic_plinth, correction):
    width, height = size
    shape = (height, width)
    wall = automatic.astype(bool).copy()
    openings = automatic_openings.astype(bool).copy()
    plinth = automatic_plinth.astype(bool).copy()
    if any(e.kind == 'facade' for e in correction.elements):
        # An explicit wall outline supersedes a falsely detected floor/plinth.
        plinth[:] = False
    explicit = False
    baseline = None
    quad = None
    for element in correction.elements:
        points = np.array([(p.x*(width-1), p.y*(height-1)) for p in element.points], np.float32)
        if element.kind == 'facade':
            wall = np.zeros(shape, np.uint8)
            cv2.fillPoly(wall, [np.rint(points).astype(np.int32)], 1)
            wall = wall.astype(bool)
            explicit = True
            if len(points) == 4 and cv2.isContourConvex(points):
                center = points.mean(axis=0)
                quad = points[np.argsort(np.arctan2(points[:,1]-center[1],points[:,0]-center[0]))]
                quad = np.roll(quad, -np.argmin(quad.sum(axis=1)), axis=0)
        elif element.kind == 'plinth':
            yy, xx = np.indices(shape)
            boundary = np.interp(np.arange(width), points[:,0], points[:,1])
            plinth = yy >= boundary[None,:]
            slope = float((points[-1,1]-points[0,1])/(points[-1,0]-points[0,0]))
            baseline = dict(slope=slope, intercept=float(points[0,1]-slope*points[0,0]))
        else:
            if len(points) == 2:  # Previously saved rectangular openings.
                x0, y0 = np.floor(points.min(axis=0)).astype(int)
                x1, y1 = np.ceil(points.max(axis=0)).astype(int)
                openings[y0:y1+1, x0:x1+1] = True
            else:
                region = np.zeros(shape, np.uint8)
                cv2.fillPoly(region, [np.rint(points).astype(np.int32)], 1)
                openings |= region > 0
    mask = (wall & ~openings & ~plinth).astype(np.uint8)
    if mask.mean() < .02:
        raise ValueError('Залишилося замало фасаду. Перевірте контур і виділення.')
    # One plane spans all visible parts, including disconnected areas between windows.
    if quad is not None and baseline is None:
        corners = quad
    else:
        corners = baseline_plane(wall.astype(np.uint8) & ~plinth, baseline or dict(slope=0., intercept=0.))
    if min(np.linalg.norm(corners-np.roll(corners,-1,axis=0),axis=1)) < 20:
        raise ValueError('Контур фасаду надто вузький.')
    return mask, corners, openings, plinth & wall, explicit
