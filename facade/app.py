"""Run: python -m uvicorn facade.app:app --host 127.0.0.1 --port 8000."""
import asyncio
import base64
import csv
import hashlib
import io
import json
import logging
import os
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import textures
from .core import DISCLAIMER, RETAKE, Segmenter, facade_geometry, overlay, quote, validate_photo
from .guards import (body_limit_error, csv_cell, ensure_lead_uniqueness, iso_kyiv, normalize_phone,
                     reap_stuck_jobs, register_lead, token_matches)
from .editor import Correction, TRAINING_CONSENT, corrected_mask, correction_error_detail
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'facade/config.json').read_text(encoding='utf-8'))
CATALOG = {i['id']: i for i in json.loads((ROOT / 'catalog-data.json').read_text(encoding='utf-8'))['items']}
DATA = Path(os.environ.get('FACADE_DATA_DIR', str(ROOT / '.facade-data'))).resolve()
DB = DATA / 'leads.sqlite3'
MODEL = None
MODEL_ERROR = False
LOCK = threading.Lock()
OUTBOX_LOCK = threading.Lock()
LIVE_JOBS_LOCK = threading.Lock()
LIVE_JOBS = set()
RATE_SALT = secrets.token_bytes(32)
LOG = logging.getLogger('facade')


def connect():
    from .guards import ClosingConnection
    connection = sqlite3.connect(DB, timeout=30, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    return connection


def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, created REAL, expires REAL,
            status TEXT, payload TEXT, result TEXT, source TEXT, ip_hash TEXT);
          CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, job TEXT, created REAL,
            type TEXT, value TEXT, source TEXT);
          CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY, job TEXT, created REAL,
            action TEXT, status TEXT, source TEXT);
          CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, job TEXT, payload TEXT,
            sent INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS annotations(job TEXT PRIMARY KEY, revision TEXT NOT NULL,
            data TEXT NOT NULL, training_consent INTEGER NOT NULL DEFAULT 0,
            consent_text TEXT NOT NULL, updated REAL NOT NULL, review_status TEXT NOT NULL);
        ''')
        db.execute("UPDATE jobs SET status='failed', result=? WHERE status IN ('queued','processing')",
                   (json.dumps({'message': 'Обробку перервано. Спробуйте ще раз.'}),))
        ensure_lead_uniqueness(db)


def cleanup():
    with connect() as db:
        rows = db.execute('SELECT id FROM jobs WHERE expires < ?', (time.time(),)).fetchall()
        for row in rows:
            job = row['id']
            shutil.rmtree(DATA / job, ignore_errors=True)
            for table in ('leads', 'outbox', 'lead_merge_archive', 'annotations'):
                db.execute(f'DELETE FROM {table} WHERE job=?', (job,))
            db.execute('DELETE FROM jobs WHERE id=?', (job,))
            # Only anonymous aggregate events survive retention.
            db.execute("UPDATE events SET job=? WHERE job=?", ('anonymous-'+secrets.token_hex(16), job))
        db.execute('DELETE FROM lead_merge_archive WHERE archived<?',
                   (time.time()-CONFIG['retentionDays']*86400,))


def deliver_outbox():
    url = os.environ.get('FACADE_CRM_WEBHOOK')
    if not url:
        return
    if urlparse(url).scheme != 'https':
        LOG.error('CRM webhook requires HTTPS')
        return
    # Single flight: a request-triggered run and the hourly run must not send the same row twice.
    if not OUTBOX_LOCK.acquire(blocking=False):
        return
    try:
        _deliver_pending(url)
    finally:
        OUTBOX_LOCK.release()


def _deliver_pending(url):
    with connect() as db:
        rows = db.execute('SELECT * FROM outbox WHERE sent=0 AND attempts < 20 LIMIT 25').fetchall()
    for row in rows:
        try:
            headers = {'Idempotency-Key': row['id']}
            token = os.environ.get('FACADE_CRM_TOKEN')
            if token:
                headers['Authorization'] = f'Bearer {token}'
            with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
                response = client.post(url, json=json.loads(row['payload']), headers=headers)
                response.raise_for_status()
            sent = 1
        except Exception:
            sent = 0  # Contacts and response bodies are deliberately never logged.
        with connect() as db:
            db.execute('UPDATE outbox SET sent=?, attempts=attempts+1 WHERE id=?', (sent, row['id']))


def load_model():
    global MODEL, MODEL_ERROR
    try:
        MODEL = Segmenter(CONFIG)
        MODEL_ERROR = False
    except Exception as exc:
        MODEL_ERROR = True
        LOG.error('Segmentation model unavailable (%s)', type(exc).__name__)


async def maintenance():
    while True:
        await asyncio.to_thread(cleanup)
        await asyncio.to_thread(deliver_outbox)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app):
    initialize()
    model_task = asyncio.create_task(asyncio.to_thread(load_model))
    upkeep = asyncio.create_task(maintenance())
    yield
    upkeep.cancel()
    model_task.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    if request.url.path.endswith('/correction'):
        return JSONResponse(correction_error_detail(exc.errors(), exc.body), status_code=422)
    return await request_validation_exception_handler(request, exc)


@app.middleware('http')
async def privacy_headers(request, call_next):
    rejected = body_limit_error(request.method, request.headers, CONFIG['maxBytes'] + 100000)
    if rejected:
        return JSONResponse({'detail': rejected[1]}, status_code=rejected[0])
    response = await call_next(request)
    if request.url.path.startswith(('/api/', '/result/', '/lab')):
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


class Variant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(max_length=100)
    base: str | None = Field(default=None, max_length=50)
    mm: int | None = Field(default=None, ge=0, le=300)


class Submission(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    panels: list[Variant] = Field(min_length=1, max_length=3)
    city: str = Field(min_length=2, max_length=120)
    area: float | None = Field(default=None, gt=0, le=100000, allow_inf_nan=False)
    name: str = Field(min_length=2, max_length=100)
    phone: str = Field(pattern=r'^\+?[0-9 ()-]{9,24}$')
    contact: Literal['phone', 'viber', 'telegram']
    consent: Literal[True]
    source: str = Field(default='catalog', max_length=200)

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, value):
        return normalize_phone(value)

    @field_validator('panels')
    @classmethod
    def validate_panels(cls, panels):
        if len({p.id for p in panels}) != len(panels):
            raise ValueError('Повтор панелі')
        for variant in panels:
            panel = CATALOG.get(variant.id)
            if not panel:
                raise ValueError('Невідома панель')
            if variant.base is not None or variant.mm is not None:
                if f'{variant.base}_{variant.mm}' not in panel.get('combinations', panel['price']):
                    raise ValueError('Недоступне поєднання основи та товщини')
        return panels


def job_row(job_id):
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, 'Результат не знайдено.')
    with connect() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=? AND expires>?', (job_id, time.time())).fetchone()
    if row is None:
        raise HTTPException(404, 'Результат не знайдено або строк зберігання минув.')
    return row


def event(db, job, kind, source, value=None):
    db.execute('INSERT INTO events(job,created,type,value,source) VALUES(?,?,?,?,?)',
               (job, time.time(), kind, value, source))


def load_texture(panel):
    return textures.load(panel['visualizationTexture'], ROOT, DATA / 'texture-cache')


def mark_failed(job_id, source):
    """Fail a job that is still queued/processing. Never raises: it runs inside an error handler."""
    try:
        with connect() as db:
            cursor = db.execute("UPDATE jobs SET status='failed', result=? WHERE id=? AND status IN ('queued','processing')",
                                (json.dumps({'message': 'Не вдалося обробити фото. Спробуйте пізніше або зв’яжіться з нами.'},
                                            ensure_ascii=False), job_id))
            if cursor.rowcount:
                event(db, job_id, 'failed', source or 'unknown')
    except Exception as exc:
        LOG.error('Could not mark job failed (%s)', type(exc).__name__)


def process_job(job_id):
    started = time.monotonic()
    source = None
    with LIVE_JOBS_LOCK:
        if job_id in LIVE_JOBS:
            return
        LIVE_JOBS.add(job_id)
    try:
        # Everything, including loading the row and validating the stored payload, is inside
        # the try: an exception here used to leave the job 'queued' and hold a pending slot.
        row = job_row(job_id)
        source = row['source']
        payload = Submission.model_validate_json(row['payload'])
        with LOCK:
            with connect() as db:
                db.execute("UPDATE jobs SET status='processing' WHERE id=?", (job_id,))
            if MODEL is None:
                raise RuntimeError('Model not ready')
            image = Image.open(DATA / job_id / 'before.png').convert('RGB')
            prediction = MODEL.predict(image)
            probability, labels = prediction[:2]
            detection = prediction[2] if len(prediction) > 2 else None
            mask, corners, confidence, factors = facade_geometry(probability, labels, CONFIG, detection)
            import numpy as np
            raw_wall = (detection or {}).get('wallMask', mask)
            if raw_wall is not None:
                Image.fromarray((raw_wall * 255).astype(np.uint8)).save(DATA / job_id / 'mask-wall.png')
            # Keep detected openings for manual recovery even if wall geometry fails.
            for key, name in (('openingMask', 'mask-openings.png'), ('plinthMask', 'mask-plinth.png')):
                structural_mask = (detection or {}).get(key)
                if structural_mask is not None:
                    Image.fromarray((structural_mask * 255).astype(np.uint8)).save(DATA / job_id / name)
            if confidence < CONFIG['minimumConfidence']:
                result = dict(message=RETAKE, confidence=confidence,
                              before=f'/api/facade/jobs/{job_id}/image/before.png')
                status = 'retake'
            else:
                import numpy as np
                Image.fromarray((mask * 255).astype(np.uint8)).save(DATA / job_id / 'mask.png')
                variants = []
                for index, variant in enumerate(payload.panels):
                    panel = CATALOG[variant.id]
                    texture = load_texture(panel)
                    after = overlay(image, texture, mask, corners, panel, CONFIG)
                    after.save(DATA / job_id / f'after-{index}.png')
                    base_name = next((b['name'] for b in panel['bases'] if b['id'] == variant.base), 'уточнюється')
                    variants.append(dict(id=panel['id'], name=panel['name'], base=base_name,
                        thickness=variant.mm, after=f'/api/facade/jobs/{job_id}/image/after-{index}.png',
                        quote=quote(panel, variant.base, variant.mm, payload.area, CONFIG)))
                result = dict(confidence=confidence, factors=factors, disclaimer=DISCLAIMER,
                    warning=(('Приблизна маска фасаду: автоматично відокремили поверхню стіни від будівлі. '
                              'Межі та геометрія можуть відрізнятися від реальних.'
                              if factors.get('method') == 'appearance-refined-building' else
                              'Низька впевненість: геометрія може суттєво відрізнятися. '
                              'Для точнішої примірки зніміть стіну з прямішого кута.')
                             if confidence < CONFIG['highConfidence'] else None),
                    textureNote=('Відтінки цеглин із вибраної фактури розподіляються випадково. Масштаб на будинку та ширина шва умовні. '
                                 + ('Цоколь залишено без змін; окремий матеріал можна буде обрати пізніше.'
                                    if factors.get('plinthDetected') else
                                    'Межу цоколя не визначено впевнено: перевірте нижній край фасаду.')),
                    before=f'/api/facade/jobs/{job_id}/image/before.png', variants=variants)
                if factors.get('openingDetectorStatus') in {'unavailable', 'failed'}:
                    result['warning'] = ((result['warning'] or '') +
                        ' Автоматична перевірка проємів недоступна. Позначте вікна та двері вручну.').strip()
                elif factors.get('openingDetectorStatus') == 'ready':
                    result['textureNote'] += ' Перевірте автоматичні межі вікон і дверей: частина проємів може бути пропущена.'
                status = 'ready'
            result['openingSuggestions'] = (detection or {}).get('openingSuggestions', [])
        with connect() as db:
            db.execute('UPDATE jobs SET status=?, result=? WHERE id=?',
                       (status, json.dumps(result, ensure_ascii=False), job_id))
            event(db, job_id, status, source, str(confidence))
            event(db, job_id, 'duration', source, str(round(time.monotonic()-started, 3)))
    except Exception as exc:
        LOG.error('Facade job failed (%s)', type(exc).__name__)
        mark_failed(job_id, source)
    finally:
        with LIVE_JOBS_LOCK:
            LIVE_JOBS.discard(job_id)


@app.get('/api/facade/health')
def health():
    return dict(ready=MODEL is not None, loading=MODEL is None and not MODEL_ERROR,
                available=not MODEL_ERROR)


@app.post('/api/facade/jobs', status_code=202)
async def create_job(request: Request, background: BackgroundTasks,
                     photo: UploadFile = File(...), metadata: str = Form(...)):
    if MODEL is None:
        raise HTTPException(503, 'Сервіс готується до роботи. Спробуйте трохи пізніше.')
    if len(metadata) > 10000:
        raise HTTPException(422, 'Забагато даних форми.')
    try:
        payload = Submission.model_validate_json(metadata)
    except ValidationError:
        raise HTTPException(422, 'Перевірте контактні дані, вибір панелей і згоду.')
    # Fail before accepting a photo when a remote catalog texture was not prepared.
    # No network access here or inside the processing lock.
    for variant in payload.panels:
        panel = CATALOG[variant.id]
        if panel['visualizationTexture'].startswith('https:'):
            try:
                texture = await asyncio.to_thread(load_texture, panel)
                texture.close()
            except (OSError, ValueError):
                raise HTTPException(503, 'Фактура цієї панелі тимчасово недоступна. Оберіть іншу панель або спробуйте пізніше.')
    hashed = hashlib.sha256(RATE_SALT + (request.client.host if request.client else '').encode()).hexdigest()
    raw = await photo.read(CONFIG['maxBytes']+1)
    await photo.close()
    try:
        image = await asyncio.to_thread(validate_photo, raw, CONFIG)
    except ValueError as exc:
        with connect() as db:
            event(db, None, 'photo_rejected', payload.source)
        raise HTTPException(422, str(exc))
    job_id = str(uuid.uuid4())
    now = time.time()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        with LIVE_JOBS_LOCK:
            live_jobs = set(LIVE_JOBS)
        reap_stuck_jobs(db, CONFIG.get('stuckJobSeconds', 1800),
                        'Обробку перервано. Спробуйте ще раз.', now, active_job_ids=live_jobs)
        count = db.execute('SELECT count(*) FROM jobs WHERE ip_hash=? AND created>?', (hashed, now-3600)).fetchone()[0]
        pending = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','processing')").fetchone()[0]
        if count >= 10 or pending >= CONFIG['maxPendingJobs']:
            raise HTTPException(429, 'Забагато запитів. Спробуйте через кілька хвилин.')
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)', (job_id, now,
            now+CONFIG['retentionDays']*86400, 'queued', payload.model_dump_json(), None, payload.source, hashed))
        event(db, job_id, 'accepted', payload.source)
    try:
        folder = DATA / job_id
        folder.mkdir()
        image.save(folder / 'before.png')  # Re-encoded, EXIF/GPS removed.
    except Exception:
        with connect() as db:
            db.execute('DELETE FROM jobs WHERE id=?', (job_id,))
        shutil.rmtree(DATA / job_id, ignore_errors=True)
        raise HTTPException(503, 'Тимчасово неможливо зберегти фото.')
    background.add_task(process_job, job_id)
    return dict(id=job_id, status='queued', resultUrl=f'/result/{job_id}')


@app.get('/api/facade/jobs/{job_id}')
def get_job(job_id: str):
    row = job_row(job_id)
    with connect() as db:
        annotation = db.execute('SELECT * FROM annotations WHERE job=?', (job_id,)).fetchone()
    editing = dict(revision=None, elements=[], trainingConsent=False)
    if annotation:
        editing.update(revision=annotation['revision'], elements=json.loads(annotation['data']),
                       trainingConsent=bool(annotation['training_consent']))
    editing['consentText'] = TRAINING_CONSENT
    result = json.loads(row['result'] or '{}')
    if row['status'] == 'retake' and (DATA / job_id / 'before.png').is_file():
        result.setdefault('before', f'/api/facade/jobs/{job_id}/image/before.png')
    return dict(id=job_id, status=row['status'], editing=editing, **result)


@app.get('/api/facade/jobs/{job_id}/image/{name}')
def job_image(job_id: str, name: str):
    row = job_row(job_id)
    allowed = {'before.png'} if row['status'] == 'retake' else {
        'before.png', 'after-0.png', 'after-1.png', 'after-2.png', 'mask.png', 'mask-openings.png', 'mask-plinth.png'}
    if row['status'] not in {'ready', 'retake'} or name not in allowed:
        raise HTTPException(404)
    path = DATA / job_id / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type='image/png')


@app.get('/api/facade/jobs/{job_id}/revision/{revision}/image/{name}')
def revised_image(job_id: str, revision: str, name: str):
    row = job_row(job_id)
    with connect() as db:
        annotation = db.execute('SELECT revision FROM annotations WHERE job=?', (job_id,)).fetchone()
    if (row['status'] != 'ready' or not annotation or revision != annotation['revision']
            or name not in {'after-0.png', 'after-1.png', 'after-2.png', 'mask.png',
                            'mask-openings.png', 'mask-plinth.png'}):
        raise HTTPException(404)
    path = DATA / job_id / 'revisions' / annotation['revision'] / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type='image/png')


@app.put('/api/facade/jobs/{job_id}/correction')
def correct_job(job_id: str, body: Correction):
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, 'Триває обробка фото. Спробуйте за хвилину.')
    folder = None
    committed = False
    try:
        row = job_row(job_id)
        if row['status'] not in {'ready', 'retake'}:
            raise HTTPException(409, 'Дочекайтеся завершення обробки.')
        if row['status'] == 'retake' and not any(e.kind == 'facade' for e in body.elements):
            raise HTTPException(422, 'Спочатку обведіть контур фасаду.')
        with connect() as db:
            old = db.execute('SELECT revision, updated FROM annotations WHERE job=?', (job_id,)).fetchone()
        if body.revision != (old['revision'] if old else None):
            raise HTTPException(409, 'Результат змінено в іншому вікні. Відкрийте його заново.')
        import numpy as np
        image = Image.open(DATA / job_id / 'before.png').convert('RGB')
        def read_mask(name):
            path = DATA / job_id / name
            return (np.asarray(Image.open(path).convert('L')) > 0 if path.is_file()
                    else np.zeros((image.height, image.width), bool))
        automatic = read_mask('mask-wall.png')
        if not automatic.any():
            automatic = read_mask('mask.png')
        try:
            mask, corners, openings, plinth, explicit = corrected_mask(image.size, automatic,
                read_mask('mask-openings.png'), read_mask('mask-plinth.png'), body)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        payload = Submission.model_validate_json(row['payload'])
        previous = json.loads(row['result'] or '{}')
        revision = str(uuid.uuid4())
        folder = DATA / job_id / 'revisions' / revision
        folder.mkdir(parents=True)
        variants = []
        for index, variant in enumerate(payload.panels):
            panel = CATALOG[variant.id]
            after = overlay(image, load_texture(panel), mask, corners, panel, CONFIG)
            after.save(folder / f'after-{index}.png')
            old_variants = previous.get('variants', [])
            estimate = (old_variants[index]['quote'] if index < len(old_variants)
                        else quote(panel, variant.base, variant.mm, payload.area, CONFIG))
            base_name = next((b['name'] for b in panel['bases'] if b['id'] == variant.base), 'уточнюється')
            variants.append(dict(id=panel['id'], name=panel['name'], base=base_name,
                thickness=variant.mm, quote=estimate,
                after=f'/api/facade/jobs/{job_id}/revision/{revision}/image/after-{index}.png'))
        for name, value in (('mask.png', mask), ('mask-openings.png', openings), ('mask-plinth.png', plinth)):
            Image.fromarray(value.astype(np.uint8)*255).save(folder / name)
        result = dict(before=f'/api/facade/jobs/{job_id}/image/before.png', variants=variants,
            openingSuggestions=previous.get('openingSuggestions', []),
            confidence=previous.get('confidence'), disclaimer=DISCLAIMER,
            warning='Маску уточнено вручну. Перевірте краї, проєми та цоколь. Геометрія й масштаб залишаються приблизними.',
            textureNote='Відтінки цеглин із вибраної фактури розподіляються випадково. Масштаб на будинку та ширина шва умовні. Виділені ділянки збережено. Матеріал цоколя можна буде обрати пізніше.',
            factors=dict(previous.get('factors') or {}, manuallyEdited=True, manualFacade=explicit))
        elements = json.dumps([e.model_dump() for e in body.elements], ensure_ascii=False)
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            fresh = db.execute('SELECT expires FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not fresh or fresh['expires'] <= time.time():
                raise HTTPException(404)
            latest = db.execute('SELECT revision, updated FROM annotations WHERE job=?', (job_id,)).fetchone()
            if ((latest is None) != (old is None) or
                    (latest is not None and (latest['revision'], latest['updated']) !=
                     (old['revision'], old['updated']))):
                raise HTTPException(409, 'Дані або згоду змінено. Відкрийте примірку заново.')
            db.execute('INSERT INTO annotations VALUES(?,?,?,?,?,?,?) ON CONFLICT(job) DO UPDATE SET '
                'revision=excluded.revision, data=excluded.data, training_consent=excluded.training_consent, '
                'consent_text=excluded.consent_text, updated=excluded.updated, review_status=excluded.review_status',
                (job_id, revision, elements, int(body.trainingConsent), TRAINING_CONSENT, time.time(), 'pending'))
            db.execute('UPDATE jobs SET status=?, result=? WHERE id=?',
                       ('ready', json.dumps(result, ensure_ascii=False), job_id))
            event(db, job_id, 'mask_corrected', row['source'])
        committed = True
        # Keep the immutable automatic masks; replace only the previous manual revision.
        if old:
            shutil.rmtree(DATA / job_id / 'revisions' / old['revision'], ignore_errors=True)
        return get_job(job_id)
    except HTTPException:
        raise
    except Exception as exc:
        LOG.error('Correction failed (%s)', type(exc).__name__)
        raise HTTPException(503, 'Не вдалося оновити примірку. Ваш попередній результат збережено.')
    finally:
        if folder is not None and not committed:
            shutil.rmtree(folder, ignore_errors=True)
        LOCK.release()


@app.delete('/api/facade/jobs/{job_id}/training-consent')
def revoke_training_consent(job_id: str):
    job_row(job_id)
    # Revocation needs no texture download, model, or rerender. An in-flight render
    # must recheck the annotation timestamp before committing a new consent value.
    with connect() as db:
        db.execute('UPDATE annotations SET training_consent=0, updated=? WHERE job=?',
                   (time.time(), job_id))
    return dict(trainingConsent=False)


class Action(BaseModel):
    action: Literal['sample', 'estimate', 'discuss', 'complaint']


@app.post('/api/facade/jobs/{job_id}/actions')
def request_action(job_id: str, body: Action, background: BackgroundTasks):
    row = job_row(job_id)
    if row['status'] != 'ready':
        raise HTTPException(409, 'Спочатку дочекайтеся результату.')
    with connect() as db:
        lead_id, _ = register_lead(db, job_id, body.action, row['source'],
                                   json.loads(row['payload']), json.loads(row['result']))
    background.add_task(deliver_outbox)
    return dict(id=lead_id, message='Заявку збережено. Менеджер підтвердить зразок і замір перед замовленням.')


def authorize(token):
    if not token_matches(token, os.environ.get('FACADE_ADMIN_TOKEN')):
        raise HTTPException(401)


@app.get('/api/facade/admin/leads.csv')
def export_leads(authorization: str | None = Header(default=None)):
    authorize(authorization)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'date', 'source', 'status', 'action', 'name', 'phone', 'city', 'contact', 'area', 'panels'])
    with connect() as db:
        rows = db.execute('SELECT leads.*, jobs.payload FROM leads JOIN jobs ON jobs.id=leads.job WHERE jobs.expires>?', (time.time(),)).fetchall()
    for row in rows:
        p = json.loads(row['payload'])
        try:
            phone = normalize_phone(p['phone'])
        except ValueError:
            phone = p['phone']  # Keep legacy invalid text guarded, never silently discard it.
        values = [row['id'], iso_kyiv(row['created']), row['source'], row['status'], row['action'],
                  p['name'], phone, p['city'], p['contact'], p['area'], json.dumps(p['panels'], ensure_ascii=False)]
        # Only the phone column (index 6) is exempt: it holds normalised digits, never free text.
        writer.writerow([csv_cell(x, phone=(i == 6)) for i, x in enumerate(values)])
    return Response('\ufeff'+output.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="facade-leads.csv"'})


class LeadStatus(BaseModel):
    status: Literal['contacted', 'measured', 'paid', 'closed']


@app.patch('/api/facade/admin/leads/{lead_id}')
def update_lead(lead_id: str, body: LeadStatus, authorization: str | None = Header(default=None)):
    authorize(authorization)
    with connect() as db:
        row = db.execute('SELECT leads.* FROM leads JOIN jobs ON jobs.id=leads.job WHERE leads.id=? AND jobs.expires>?', (lead_id,time.time())).fetchone()
        if not row:
            raise HTTPException(404)
        db.execute('UPDATE leads SET status=? WHERE id=?', (body.status, lead_id))
        if body.status == 'paid' and row['status'] != 'paid':
            event(db, row['job'], 'paid', row['source'], lead_id)
    return dict(status=body.status)


@app.get('/api/facade/admin/metrics')
def metrics(authorization: str | None = Header(default=None)):
    authorize(authorization)
    with connect() as db:
        rows = db.execute('SELECT type,value,source,job FROM events').fetchall()
    sources = {}
    for row in rows:
        sources.setdefault(row['source'], []).append(row)
    result = {}
    for source, events in sources.items():
        accepted = sum(e['type']=='accepted' for e in events)
        ready = [e for e in events if e['type']=='ready']
        duration = [float(e['value']) for e in events if e['type']=='duration']
        clicked = {e['job'] for e in events if e['type'] in {'sample','estimate'} and e['job']}
        result[source] = dict(accepted=accepted, ready=len(ready),
            highConfidenceRate=sum(float(e['value'])>=CONFIG['highConfidence'] for e in ready)/accepted if accepted else None,
            conversionRate=len(clicked)/len(ready) if ready else None,
            paid=len({e['value'] for e in events if e['type']=='paid'}),
            complaints=sum(e['type']=='complaint' for e in events),
            complaintRate=sum(e['type']=='complaint' for e in events)/len(ready) if ready else None,
            averageProcessingSeconds=sum(duration)/len(duration) if duration else None)
    return result


# Serve only explicit public assets; never mount ROOT or expose the database/photos.
@app.get('/')
def index():
    return FileResponse(ROOT / 'index.html', media_type='text/html')


@app.get('/lab')
@app.get('/result/{job_id}')
def laboratory(job_id: str | None = None):
    if job_id:
        job_row(job_id)
    return FileResponse(ROOT / 'facade/lab.html', media_type='text/html')


@app.get('/lab/catalog.js')
def lab_catalog():
    # Send only fields used by the editor. Thumbnails load separately on demand.
    fields = ('id', 'name', 'bases', 'thicknesses', 'price', 'combinations')
    sections = {}
    for panel in CATALOG.values():
        item = {key: panel[key] for key in fields if key in panel}
        item['image'] = f"/lab/images/{panel['id']}"
        sections.setdefault(panel['section'], []).append(item)
    data = {'sections': [{'id': key, 'items': items} for key, items in sections.items()]}
    return Response('const CATALOG = ' + json.dumps(data, ensure_ascii=True) + ';',
                    media_type='application/javascript')


@app.get('/lab/images/{panel_id}')
def lab_image(panel_id: str):
    panel = CATALOG.get(panel_id)
    if not panel:
        raise HTTPException(404)
    source = panel.get('image', '')
    if not source.startswith(('data:image/webp;base64,', 'data:image/png;base64,', 'data:image/jpeg;base64,')):
        raise HTTPException(404)
    header, encoded = source.split(',', 1)
    return Response(base64.b64decode(encoded), media_type=header[5:].split(';')[0])


@app.get('/facade/google-mail/transport.js')
def mail_transport():
    return FileResponse(ROOT / 'facade/google-mail/transport.js', media_type='application/javascript')


@app.get('/facade/{asset}')
def asset(asset: str):
    if asset not in {'facade.css', 'facade.js', 'facade-editor.js', 'lead.css', 'lead.js', 'lab.css', 'lab.js'}:
        raise HTTPException(404)
    return FileResponse(ROOT / 'facade' / asset)


@app.get('/print/{asset}')
def print_asset(asset: str):
    if asset not in {'nash-dvor-catalog.pdf', 'catalog-with-photos.html'}:
        raise HTTPException(404)
    return FileResponse(ROOT / 'print' / asset)


@app.get('/robots.txt')
def robots():
    return Response('User-agent: *\nDisallow: /result/\nDisallow: /api/\nDisallow: /lab\n', media_type='text/plain')
