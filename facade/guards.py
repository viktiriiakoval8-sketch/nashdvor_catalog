"""Stdlib-only helpers for the facade API.

Kept free of FastAPI/pydantic imports so they can be unit-tested without the
web stack (see tests/test_guards.py). app.py is the only caller.
"""
import json
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

BODY_METHODS = frozenset({'POST', 'PUT', 'PATCH'})
_PHONE_CELL = re.compile(r'^\+?[0-9]{9,15}$')


class ClosingConnection(sqlite3.Connection):
    """Commit/rollback like sqlite3, then release the file handle on every platform."""
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def body_limit_error(method, headers, limit):
    """Decide before the body is read whether a request must be refused.

    Returns (status_code, message) or None. Requests that can carry a body must
    announce an honest Content-Length: without it (chunked transfer) the web
    framework would spool the whole upload to disk before any size check runs.
    `headers` is any mapping with lower-case keys (Starlette Headers qualifies).
    """
    length = headers.get('content-length')
    if method.upper() in BODY_METHODS and (length is None or headers.get('transfer-encoding') is not None):
        return 411, 'Потрібен заголовок Content-Length. Надішліть фото звичайним способом із форми.'
    if length is None:
        return None
    if not length.isdigit():
        return 400, 'Некоректний заголовок Content-Length.'
    if int(length) > limit:
        return 413, 'Фото має бути не більше 10 МБ.'
    return None


def normalize_phone(value):
    """'+38 (050) 123-45-67' -> '+380501234567'. Raises ValueError on junk."""
    text = value.strip()
    digits = re.sub(r'\D', '', text)
    if not 9 <= len(digits) <= 15 or len(set(digits)) == 1:
        raise ValueError('Невірний номер телефону')
    return ('+' if text.startswith('+') else '') + digits


def csv_cell(value, *, phone=False):
    """Neutralise spreadsheet formulas without corrupting normalised phone numbers."""
    text = '' if value is None else str(value)
    if phone and _PHONE_CELL.fullmatch(text):
        return text  # digits with an optional leading '+': cannot carry a formula payload
    return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else text


def iso_kyiv(timestamp):
    return datetime.fromtimestamp(float(timestamp), ZoneInfo('Europe/Kyiv')).isoformat(timespec='seconds')


def ensure_lead_uniqueness(db):
    """Archive merged records, retain advanced status, then enforce unique (job, action).

    The caller owns the transaction. Archive retention follows the original job.
    Sent outbox records remain as delivery history; unsent duplicates are archived.
    """
    if not db.in_transaction:
        db.execute('BEGIN IMMEDIATE')
    db.execute('''CREATE TABLE IF NOT EXISTS lead_merge_archive(
        id TEXT PRIMARY KEY, job TEXT, canonical_id TEXT, archived REAL,
        lead_json TEXT, outbox_json TEXT)''')
    groups = db.execute('SELECT job, action FROM leads GROUP BY job, action HAVING count(*)>1').fetchall()
    ranks = {'new': 0, 'closed': 1, 'contacted': 2, 'measured': 3, 'paid': 4}
    for job, action in groups:
        rows = db.execute('SELECT id,job,created,action,status,source FROM leads WHERE job=? AND action=? ORDER BY rowid',
                          (job, action)).fetchall()
        canonical = rows[0][0]
        best_status = max(rows, key=lambda row: ranks.get(row[4], 0))[4]
        for row in rows[1:]:
            outgoing = db.execute('SELECT id,job,payload,sent,attempts FROM outbox WHERE id=?', (row[0],)).fetchone()
            lead = dict(zip(('id','job','created','action','status','source'), row))
            outbox = dict(zip(('id','job','payload','sent','attempts'), outgoing)) if outgoing else None
            db.execute('INSERT OR IGNORE INTO lead_merge_archive VALUES(?,?,?,?,?,?)',
                       (row[0], job, canonical, time.time(), json.dumps(lead,ensure_ascii=False),
                        json.dumps(outbox,ensure_ascii=False)))
            db.execute('DELETE FROM outbox WHERE id=? AND sent=0', (row[0],))
            db.execute('DELETE FROM leads WHERE id=?', (row[0],))
        db.execute('UPDATE leads SET status=? WHERE id=?', (best_status, canonical))
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS leads_job_action ON leads(job, action)')


def register_lead(db, job_id, action, source, customer, result, now=None):
    """Create lead + event + outbox row at most once per (job, action).

    Returns (lead_id, created). The write lock is taken first, so a concurrent
    request waits and then sees the row instead of inserting a second one.
    The caller owns commit (use `with connect() as db`).
    """
    now = time.time() if now is None else now
    if not db.in_transaction:  # callers normally pass a fresh connection
        db.execute('BEGIN IMMEDIATE')
    existing = db.execute('SELECT id FROM leads WHERE job=? AND action=?', (job_id, action)).fetchone()
    if existing:
        return existing[0], False
    lead_id = str(uuid.uuid4())
    db.execute('INSERT INTO leads VALUES(?,?,?,?,?,?)', (lead_id, job_id, now, action, 'new', source))
    db.execute('INSERT INTO events(job,created,type,value,source) VALUES(?,?,?,?,?)',
               (job_id, now, action, None, source))
    data = dict(id=lead_id, job=job_id, action=action, status='new', source=source,
                customer=customer, result=result)
    db.execute('INSERT INTO outbox(id,job,payload) VALUES(?,?,?)',
               (lead_id, job_id, json.dumps(data, ensure_ascii=False)))
    return lead_id, True


def reap_stuck_jobs(db, seconds, message, now=None, active_job_ids=()):
    """Fail jobs stuck in queued/processing longer than `seconds`.

    Without this a few orphaned rows would hold every pending-job slot until the
    next process restart. Call inside the write transaction that counts pending
    jobs. Returns how many rows were failed.
    """
    now = time.time() if now is None else now
    rows = db.execute("SELECT id, source FROM jobs WHERE status IN ('queued','processing') AND created<?",
                      (now - seconds,)).fetchall()
    for row in rows:
        if row[0] in active_job_ids:
            continue
        db.execute("UPDATE jobs SET status='failed', result=? WHERE id=?",
                   (json.dumps({'message': message}, ensure_ascii=False), row[0]))
        db.execute('INSERT INTO events(job,created,type,value,source) VALUES(?,?,?,?,?)',
                   (row[0], now, 'failed', 'stuck', row[1] or 'unknown'))
    return sum(row[0] not in active_job_ids for row in rows)


def token_matches(provided, expected):
    """Constant-time check of an `Authorization: Bearer ...` header.

    Compares UTF-8 bytes: secrets.compare_digest on str raises TypeError for non-ASCII
    input, which used to turn a malformed header into a 500 instead of a 401.
    """
    if not expected:
        return False
    return secrets.compare_digest((provided or '').encode('utf-8'), f'Bearer {expected}'.encode('utf-8'))
