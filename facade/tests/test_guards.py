"""Tests for facade/guards.py. Stdlib only: runs with pytest or `python tests/test_guards.py`."""
import csv
import io
import json
import sqlite3
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from facade.guards import (body_limit_error, csv_cell, ensure_lead_uniqueness, iso_kyiv,  # noqa: E402
                           normalize_phone, reap_stuck_jobs, register_lead, ClosingConnection, token_matches)

LIMIT = 10 * 1024 * 1024 + 100000
SCHEMA = '''
  CREATE TABLE jobs(id TEXT PRIMARY KEY, created REAL, expires REAL, status TEXT, payload TEXT, result TEXT, source TEXT, ip_hash TEXT);
  CREATE TABLE events(id INTEGER PRIMARY KEY, job TEXT, created REAL, type TEXT, value TEXT, source TEXT);
  CREATE TABLE leads(id TEXT PRIMARY KEY, job TEXT, created REAL, action TEXT, status TEXT, source TEXT);
  CREATE TABLE outbox(id TEXT PRIMARY KEY, job TEXT, payload TEXT, sent INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0);
'''


def database(tmp):
    path = str(Path(tmp) / 'db.sqlite3')
    db = sqlite3.connect(path, timeout=30, factory=ClosingConnection)
    db.executescript(SCHEMA)
    db.commit()
    db.close()
    return path


def connect(path):
    db = sqlite3.connect(path, timeout=30, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    return db


# --- P0-1: body size limit cannot be bypassed without Content-Length -------------------

def test_chunked_or_missing_length_rejected_for_body_methods():
    assert body_limit_error('POST', {}, LIMIT)[0] == 411
    assert body_limit_error('POST', {'transfer-encoding': 'chunked'}, LIMIT)[0] == 411
    assert body_limit_error('POST', {'content-length': '10', 'transfer-encoding': 'chunked'}, LIMIT)[0] == 411
    assert body_limit_error('PATCH', {}, LIMIT)[0] == 411


def test_oversized_and_malformed_length_rejected():
    assert body_limit_error('POST', {'content-length': str(LIMIT + 1)}, LIMIT)[0] == 413
    assert body_limit_error('GET', {'content-length': str(LIMIT + 1)}, LIMIT)[0] == 413
    assert body_limit_error('POST', {'content-length': '-5'}, LIMIT)[0] == 400
    assert body_limit_error('POST', {'content-length': 'abc'}, LIMIT)[0] == 400


def test_normal_requests_pass():
    assert body_limit_error('POST', {'content-length': str(LIMIT)}, LIMIT) is None
    assert body_limit_error('POST', {'content-length': '0'}, LIMIT) is None
    assert body_limit_error('GET', {}, LIMIT) is None


# --- P0-3: phone numbers survive the CSV export ----------------------------------------

def test_phone_normalisation():
    assert normalize_phone('+38 (050) 123-45-67') == '+380501234567'
    assert normalize_phone('050 123 45 67') == '0501234567'
    for junk in ('0000000000', '1111111111', '12345678', '+1234567890123456'):
        try:
            normalize_phone(junk)
        except ValueError:
            continue
        raise AssertionError(f'{junk} should be rejected')


def test_csv_keeps_phone_but_still_neutralises_formulas():
    assert csv_cell('+380501234567', phone=True) == '+380501234567'
    assert csv_cell('0501234567', phone=True) == '0501234567'
    assert csv_cell('+380501234567') == "'+380501234567"      # free text stays guarded
    assert csv_cell('=HYPERLINK("http://x")', phone=True).startswith("'=")
    assert csv_cell('=1+1') == "'=1+1" and csv_cell('@SUM(A1)') == "'@SUM(A1)"
    assert csv_cell(None) == '' and csv_cell(80) == '80'
    out = io.StringIO()
    csv.writer(out).writerow([csv_cell('+380501234567', phone=True), csv_cell('Іван')])
    assert out.getvalue().startswith('+380501234567,')


def test_iso_kyiv_is_readable():
    assert iso_kyiv(0) == '1970-01-01T03:00:00+03:00'


# --- P0-4: one lead per (job, action), even under concurrent clicks --------------------

def test_register_lead_is_idempotent(tmp_path_factory=None):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = database(tmp)
        with connect(path) as db:
            first = register_lead(db, 'job-1', 'sample', 'test', {'name': 'Тест'}, {'confidence': .8})
        with connect(path) as db:
            second = register_lead(db, 'job-1', 'sample', 'test', {'name': 'Тест'}, {'confidence': .8})
            other = register_lead(db, 'job-1', 'estimate', 'test', {}, {})
        assert first[1] is True and second == (first[0], False) and other[1] is True
        with connect(path) as db:
            assert db.execute('SELECT count(*) FROM leads').fetchone()[0] == 2
            assert db.execute('SELECT count(*) FROM outbox').fetchone()[0] == 2
            assert db.execute("SELECT count(*) FROM events WHERE type='sample'").fetchone()[0] == 1
            payload = json.loads(db.execute('SELECT payload FROM outbox WHERE id=?', (first[0],)).fetchone()[0])
            assert payload['customer'] == {'name': 'Тест'} and payload['status'] == 'new'


def test_register_lead_concurrent_clicks_create_one_lead_per_job():
    """Stress version: without the write lock and the unique index this produced ~37% extra leads."""
    import tempfile
    jobs = 30
    with tempfile.TemporaryDirectory() as tmp:
        path = database(tmp)
        ensure = connect(path)
        with ensure:
            ensure_lead_uniqueness(ensure)
        ensure.close()
        errors = []
        for number in range(jobs):
            barrier = threading.Barrier(8)

            def click():
                try:
                    db = connect(path)
                    barrier.wait()
                    with db:
                        register_lead(db, f'job-{number}', 'sample', 'test', {}, {})
                    db.close()
                except Exception as exc:  # pragma: no cover - reported below
                    errors.append(repr(exc))

            threads = [threading.Thread(target=click) for _ in range(8)]
            [t.start() for t in threads]
            [t.join() for t in threads]
        assert not errors, errors
        with connect(path) as db:
            for table in ('leads', 'outbox'):
                assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == jobs
            assert db.execute("SELECT count(*) FROM events WHERE type='sample'").fetchone()[0] == jobs


def test_uniqueness_migration_removes_old_duplicates_and_blocks_new_ones():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = database(tmp)
        with connect(path) as db:
            for lead in ('a', 'b'):
                db.execute("INSERT INTO leads VALUES(?,?,?,?,?,?)", (lead, 'j', 1.0, 'sample', 'new', 's'))
                db.execute("INSERT INTO outbox(id,job,payload) VALUES(?,?,?)", (lead, 'j', '{}'))
            db.execute("INSERT INTO leads VALUES('c','j',1.0,'estimate','new','s')")
            ensure_lead_uniqueness(db)
        with connect(path) as db:
            assert sorted(r[0] for r in db.execute('SELECT id FROM leads')) == ['a', 'c']
            assert [r[0] for r in db.execute('SELECT id FROM outbox')] == ['a']
            try:
                db.execute("INSERT INTO leads VALUES('d','j',1.0,'sample','new','s')")
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError('unique index missing')


def test_uniqueness_migration_archives_history_and_preserves_paid_status():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = database(tmp)
        with connect(path) as db:
            db.execute("INSERT INTO leads VALUES('original','j',1,'sample','new','s')")
            db.execute("INSERT INTO leads VALUES('paid-duplicate','j',2,'sample','paid','s')")
            db.execute("INSERT INTO leads VALUES('sent-duplicate','j',3,'sample','contacted','s')")
            db.execute("INSERT INTO outbox(id,job,payload,sent,attempts) VALUES('paid-duplicate','j',?,0,2)",
                       (json.dumps({'customer':{'name':'Synthetic'},'status':'paid'}),))
            db.execute("INSERT INTO outbox(id,job,payload,sent,attempts) VALUES('sent-duplicate','j','{}',1,1)")
            ensure_lead_uniqueness(db)
        with connect(path) as db:
            lead=db.execute('SELECT id,status FROM leads').fetchone()
            assert tuple(lead)==('original','paid')
            archive=db.execute('SELECT canonical_id,lead_json,outbox_json FROM lead_merge_archive WHERE id=?',
                               ('paid-duplicate',)).fetchone()
            assert archive['canonical_id']=='original'
            assert json.loads(archive['lead_json'])['status']=='paid'
            assert json.loads(archive['outbox_json'])['attempts']==2
            assert db.execute('SELECT id FROM outbox').fetchone()[0]=='sent-duplicate'
            ensure_lead_uniqueness(db)
            assert db.execute('SELECT count(*) FROM lead_merge_archive').fetchone()[0]==2


def test_closing_connection_releases_after_commit_and_rollback():
    db=sqlite3.connect(':memory:',factory=ClosingConnection)
    with db:
        db.execute('CREATE TABLE test(value)')
    try:
        db.execute('SELECT 1')
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError('Connection should be closed')
    db=sqlite3.connect(':memory:',factory=ClosingConnection)
    try:
        with db:
            raise ValueError('test rollback')
    except ValueError:
        pass
    try:
        db.execute('SELECT 1')
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError('Connection should close after exception')


# --- P0-2: stuck jobs do not hold pending slots forever --------------------------------

def test_reap_stuck_jobs_frees_slots_and_leaves_fresh_ones():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = database(tmp)
        with connect(path) as db:
            rows = [('old-q', 100.0, 'queued'), ('old-p', 100.0, 'processing'),
                    ('fresh', 4000.0, 'queued'), ('done', 100.0, 'ready')]
            for job, created, status in rows:
                db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)", (job, created, 9e9, status, '{}', None, None, 'h'))
            assert reap_stuck_jobs(db, 1800, 'перервано', now=4000.0) == 2
        with connect(path) as db:
            status = {r['id']: r['status'] for r in db.execute('SELECT id,status FROM jobs')}
            assert status == {'old-q': 'failed', 'old-p': 'failed', 'fresh': 'queued', 'done': 'ready'}
            assert db.execute("SELECT count(*) FROM events WHERE type='failed'").fetchone()[0] == 2
            assert json.loads(db.execute("SELECT result FROM jobs WHERE id='old-q'").fetchone()[0])['message'] == 'перервано'


def test_reaper_does_not_fail_live_processing_job():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path=database(tmp)
        with connect(path) as db:
            for job in ('live','orphan'):
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',
                           (job,100,9e9,'processing','{}',None,'test','ip'))
            assert reap_stuck_jobs(db,1800,'timeout',now=4000,active_job_ids={'live'})==1
            states=dict(db.execute('SELECT id,status FROM jobs').fetchall())
            assert states=={'live':'processing','orphan':'failed'}


def test_admin_token_check_handles_non_ascii_without_raising():
    assert token_matches('Bearer secret', 'secret') is True
    assert token_matches('Bearer wrong', 'secret') is False
    assert token_matches(None, 'secret') is False and token_matches('', 'secret') is False
    assert token_matches('Bearer secret', None) is False and token_matches('Bearer secret', '') is False
    assert token_matches('Bearer тест', 'secret') is False        # used to raise TypeError -> HTTP 500
    assert token_matches('Bearer секрет', 'секрет') is True       # non-ASCII secrets still work


if __name__ == '__main__':
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('PASS', name)
            except Exception as exc:
                failed += 1
                print('FAIL', name, repr(exc))
    sys.exit(1 if failed else 0)
