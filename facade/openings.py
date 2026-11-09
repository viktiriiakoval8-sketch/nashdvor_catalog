"""Local, text-guided opening detection; boxes are approximate exclusions, not training labels."""
import inspect
import numpy as np


def boxes_to_mask(boxes, scores, building, config, diagnostics=None, context_mode='interior'):
    if context_mode not in ('interior', 'ring'):
        raise ValueError('Unknown context mode')
    def record(reason):
        if diagnostics is not None:
            diagnostics[reason] = diagnostics.get(reason, 0) + 1
    height, width = building.shape
    mask = np.zeros(building.shape, bool)
    ys, xs = np.nonzero(building)
    if not len(xs):
        for _ in boxes:
            record('no_building')
        return mask, []
    building_area = (int(xs.max())-int(xs.min())+1)*(int(ys.max())-int(ys.min())+1)
    accepted = []
    for box, score in sorted(zip(boxes, scores), key=lambda item: float(item[1]), reverse=True):
        box = np.asarray(box, dtype=float)
        if box.shape != (4,) or not np.isfinite(box).all() or not np.isfinite(score):
            record('invalid')
            continue
        if score < config.get('openingDetectionThreshold', .3):
            record('score')
            continue
        x0, y0 = np.floor(box[:2]).astype(int)
        x1, y1 = np.ceil(box[2:]).astype(int)
        x0, x1 = np.clip([x0, x1], 0, width)
        y0, y1 = np.clip([y0, y1], 0, height)
        area = int(x1-x0)*int(y1-y0)
        if x1-x0 < 6 or y1-y0 < 6 or area > building_area*.45:
            record('size')
            continue
        context = float(building[y0:y1, x0:x1].mean())
        if context_mode == 'ring':
            margin = max(2, round(max(x1-x0, y1-y0)*.1))
            outer = building[max(0,y0-margin):min(height,y1+margin),
                             max(0,x0-margin):min(width,x1+margin)]
            ring_area = outer.size - area
            context = (int(outer.sum())-int(building[y0:y1,x0:x1].sum())) / max(1,ring_area)
        if context < .5:
            record('context')
            continue
        # Suppress nested duplicates (glass/door panel and complete frame).
        if any(max(0, min(x1,b[2])-max(x0,b[0])) * max(0,min(y1,b[3])-max(y0,b[1]))
               / min(area, (b[2]-b[0])*(b[3]-b[1])) > .85 for b in accepted):
            record('duplicate')
            continue
        record('accepted')
        accepted.append([int(x0), int(y0), int(x1), int(y1)])
    margin = max(2, round(max(width,height)*config.get('openingMarginFraction', .004)))
    for x0,y0,x1,y1 in accepted:
        mask[max(0,y0-margin):min(height,y1+margin), max(0,x0-margin):min(width,x1+margin)] = True
    return mask, accepted


class OpeningDetector:
    def __init__(self, config):
        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
        self.config = config
        name = config['openingDetectorModel']
        revision = config.get('openingDetectorRevision', 'main')
        # Startup uses prepared local weights; never downloads during a customer request.
        self.processor = AutoProcessor.from_pretrained(name, revision=revision, local_files_only=True)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(
            name, revision=revision, local_files_only=True, use_safetensors=True).eval()

    def predict(self, image, building, diagnostics=None):
        import torch
        inputs = self.processor(images=image, text='a window. a door. a garage door.', return_tensors='pt')
        with torch.inference_mode():
            output = self.model(**inputs)
        post = self.processor.post_process_grounded_object_detection
        # Transformers 4 uses box_threshold; Transformers 5 renamed it threshold.
        parameter = 'threshold' if 'threshold' in inspect.signature(post).parameters else 'box_threshold'
        result = post(output, inputs.input_ids, **{parameter:min(self.config.get('openingSuggestionThreshold', .2),self.config.get('openingDetectionThreshold', .3))},
                      text_threshold=.25, target_sizes=[image.size[::-1]])[0]
        boxes, scores = result['boxes'].cpu().numpy(), result['scores'].cpu().numpy()
        counts = {} if diagnostics is not None else None
        mask, accepted = boxes_to_mask(boxes, scores, building, self.config, counts)
        if diagnostics is not None:
            diagnostics.update(rawBoxes=boxes, rawScores=scores, rejections=counts)
        labels = result['text_labels'] if 'text_labels' in result else result.get('labels', [])
        suggestions = opening_suggestions(boxes, scores, labels,
                                          building, self.config, accepted)
        return mask, accepted, suggestions


def opening_suggestions(boxes, scores, labels, building, config, accepted):
    """Low-confidence proposals never affect the rendered mask without user confirmation."""
    low = dict(config,openingDetectionThreshold=config.get('openingSuggestionThreshold', .2))
    _, candidates = boxes_to_mask(boxes,scores,building,low)
    height,width = building.shape
    proposals=[]
    for box in candidates:
        if box in accepted:
            continue
        area=(box[2]-box[0])*(box[3]-box[1])
        if any(max(0,min(box[2],b[2])-max(box[0],b[0]))*max(0,min(box[3],b[3])-max(box[1],b[1]))
               / min(area,(b[2]-b[0])*(b[3]-b[1])) > .5 for b in accepted):
            continue
        index=int(np.argmin(np.abs(np.asarray(boxes)-np.asarray(box)).sum(axis=1)))
        label=str(labels[index]) if index<len(labels) else ''
        x0,y0,x1,y1=box
        proposals.append(dict(kind='door' if 'door' in label else 'window',
            points=[dict(x=min(1,x/(width-1)),y=min(1,y/(height-1)))
                    for x,y in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]],score=float(scores[index])))
    return proposals[:24]
