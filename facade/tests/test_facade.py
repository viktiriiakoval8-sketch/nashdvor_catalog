import io
import json
import math
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from facade import app as service
from facade.core import facade_geometry, overlay, quote, validate_photo, refine_building
import cv2

CONFIG = service.CONFIG
CATALOG = service.CATALOG


def test_exact_catalog_export():
    text = (service.ROOT / 'index.html').read_text(encoding='utf-8')
    original = json.JSONDecoder().raw_decode(text.split('const CATALOG = ',1)[1])[0]
    eligible = {p['id']:p for s in original['sections'] if s['id'] in {'porcelain', 'polish-clinker', 'clinker-imitation'} for p in s['items']}
    assert len(CATALOG) == len(eligible) == 46
    for id, panel in CATALOG.items():
        assert panel['price'] == eligible[id]['price']
        assert panel['currency'] == eligible[id]['currency']
        assert panel['image'] == eligible[id]['image']
        assert panel['tileSize'] == eligible[id].get('tileSize')


def test_user_confirmed_tile_dimensions_are_scoped_to_correct_categories():
    for panel in CATALOG.values():
        if panel['section']=='porcelain':
            assert panel['tileSize']==dict(width=250,height=60)
        elif panel['section']=='polish-clinker':
            assert panel['tileSize']==dict(width=245,height=65)
        else:
            assert panel['tileSize'] is None


def test_all_eligible_prices_exported():
    assert sum(len(p['price']) for p in CATALOG.values()) == 317


def test_quotes_units_and_missing_values():
    porcelain = CATALOG['tu-1112']
    now = datetime(2026,10,29,12,tzinfo=ZoneInfo('Europe/Kyiv'))
    q = quote(porcelain,'eps',50,1,CONFIG,now)
    assert q['panelCount']==2 and q['panels']==1354
    assert q['validUntil']=='2026-11-12' and q['date']=='2026-10-29'
    assert q['accessories'] is q['delivery'] is q['installation'] is None
    assert quote(porcelain,None,None,80,CONFIG)['panels'] is None
    assert quote(porcelain,'eps',50,None,CONFIG)['panels'] is None
    clinker=CATALOG['tp-10101']
    assert quote(clinker,'eps',50,3.333,CONFIG)['panels']==4999.5
    assert quote(clinker,'mesh',0,50,CONFIG)['panels'] is None
    for value in [0,-1,float('inf'),float('nan')]:
        with pytest.raises(ValueError):quote(clinker,'eps',50,value,CONFIG)


def test_homography_preserves_window_door_and_background():
    rgb=np.random.default_rng(1).integers(20,230,(500,700,3),dtype=np.uint8)
    wall=np.zeros((500,700),bool);wall[50:450,100:600]=True
    wall[150:260,180:280]=False  # Window
    wall[300:450,400:470]=False  # Door
    mask,corners,confidence,factors=facade_geometry(wall.astype(float)*.98,wall,CONFIG)
    assert confidence>=.75
    image=Image.fromarray(rgb)
    texture=Image.new('RGB',(100,50),'red')
    after=np.asarray(overlay(image,texture,mask,corners,{},CONFIG))
    assert np.array_equal(after[mask==0],rgb[mask==0])
    assert np.array_equal(after[160:250,190:270],rgb[160:250,190:270])
    assert not np.array_equal(after[80:100,120:160],rgb[80:100,120:160])


def test_bad_masks_fail_closed():
    wall=np.zeros((500,700),bool)
    assert facade_geometry(wall.astype(float),wall,CONFIG)[2]<.5
    wall[5:30,5:30]=True
    assert facade_geometry(wall.astype(float),wall,CONFIG)[2]<.5
    wall[:]=False;wall[50:450,20:260]=True;wall[50:450,400:680]=True
    assert facade_geometry(wall.astype(float),wall,CONFIG)[2]<.5


def test_gable_mask_keeps_peak_and_openings_with_approximate_projection():
    rgb=np.full((500,700,3),160,dtype=np.uint8)
    wall=np.zeros((500,700),np.uint8)
    cv2.fillPoly(wall,[np.array([[80,160],[350,60],[620,160],[620,440],[80,440]])],1)
    wall[220:300,200:280]=0
    mask,corners,confidence,factors=facade_geometry(wall*.99,wall.astype(bool),CONFIG)
    assert .5 <= confidence < .75
    assert factors['approximatePlane'] and mask[90,350] and not mask[240,230]
    after=np.asarray(overlay(Image.fromarray(rgb),Image.new('RGB',(20,20),'red'),mask,corners,{},CONFIG))
    assert after[90,350,0]>200  # Gable peak must be textured, not black or clipped.
    assert np.array_equal(after[mask==0],rgb[mask==0])


def test_building_refinement_separates_roof_and_keeps_shadowed_wall():
    image=np.full((500,700,3),(110,180,230),dtype=np.uint8)
    region=np.zeros((500,700),np.uint8)
    cv2.fillPoly(region,[np.array([[70,160],[350,50],[630,160],[620,440],[80,440]])],1)
    image[region>0]=(40,45,50)
    surface=np.zeros_like(region)
    cv2.fillPoly(surface,[np.array([[80,185],[350,85],[620,185],[620,440],[80,440]])],1)
    image[surface>0]=(205,185,160)
    image[185:230,120:580]=(130,115,100)
    image[280:350,220:290]=(25,30,35)
    region[280:350,220:290]=0  # Semantic window exclusion must survive refinement.
    refined=refine_building(Image.fromarray(image),region.astype(bool),CONFIG)
    assert refined is not None
    assert refined[205,350] and refined[350,400]
    assert not refined[70,350] and not refined[310,250] and not refined[20,20]
    _,_,confidence,_=facade_geometry(region*.99,refined,CONFIG,{'method':'appearance-refined-building'})
    assert .5 <= confidence <= .74


def test_photo_validation():
    def raw(image,format='PNG'):
        stream=io.BytesIO();image.save(stream,format=format);return stream.getvalue()
    with pytest.raises(ValueError,match='1200'):validate_photo(raw(Image.new('RGB',(800,600))),CONFIG)
    with pytest.raises(ValueError,match='розмите'):validate_photo(raw(Image.new('RGB',(1200,800),'gray')),CONFIG)
    with pytest.raises(ValueError):validate_photo(b'bad-file',CONFIG)
    image=Image.fromarray(np.random.default_rng(2).integers(0,255,(800,1200,3),dtype=np.uint8))
    assert validate_photo(raw(image),CONFIG).size==(1200,800)
    with pytest.raises(ValueError):validate_photo(raw(image,'GIF'),CONFIG)
    with pytest.raises(ValueError,match='10'):validate_photo(b'x'*(CONFIG['maxBytes']+1),CONFIG)


def test_exif_metadata_removed():
    image=Image.fromarray(np.random.default_rng(4).integers(0,255,(800,1200,3),dtype=np.uint8))
    exif=Image.Exif();exif[274]=6;exif[315]='Private photo owner'
    original=io.BytesIO();image.save(original,format='JPEG',exif=exif)
    clean=validate_photo(original.getvalue(),CONFIG)
    assert clean.size==(800,1200)
    stored=io.BytesIO();clean.save(stored,format='PNG')
    assert len(Image.open(io.BytesIO(stored.getvalue())).getexif())==0


@pytest.fixture
def api(tmp_path,monkeypatch):
    monkeypatch.setattr(service,'DATA',tmp_path)
    monkeypatch.setattr(service,'DB',tmp_path/'leads.sqlite3')
    monkeypatch.setattr(service,'load_model',lambda:None)
    monkeypatch.setenv('FACADE_ADMIN_TOKEN','testing-admin')
    monkeypatch.delenv('FACADE_CRM_WEBHOOK',raising=False)
    class FakeModel:
        def predict(self,image):
            wall=np.zeros((image.height,image.width),bool)
            wall[100:-100,100:-100]=True
            wall[250:350,250:350]=False
            return wall.astype(float)*.99,wall
    monkeypatch.setattr(service,'MODEL',FakeModel())
    with TestClient(service.app) as client:yield client


def submission():
    return dict(panels=[dict(id='tu-1112',base='eps',mm=50)],city='Одеса',area=80,
                name='Тест',phone='+380501234567',contact='phone',consent=True,source='test')


def test_catalog_and_laboratory_have_separate_working_assets(api):
    root = api.get('/')
    assert root.status_code == 200 and '/facade/lead.js' in root.text
    lab = api.get('/lab')
    assert lab.status_code == 200 and '/facade/facade.js' in lab.text
    assert '/facade/lead.js' not in lab.text
    assert lab.headers['X-Robots-Tag'].startswith('noindex')
    import re
    for page in (root, lab):
        paths = re.findall(r'(?:src|href)="(/facade/[^"?]+|/lab/catalog.js)(?:\?[^\"]*)?"', page.text)
        assert paths
        for path in paths:
            response = api.get(path)
            assert response.status_code == 200, path
            assert response.headers['content-type'].startswith(('text/css', 'application/javascript', 'text/javascript'))
    data = json.loads(api.get('/lab/catalog.js').text.removeprefix('const CATALOG = ').removesuffix(';'))
    panels = [p for s in data['sections'] for p in s['items']]
    assert {p['id'] for p in panels} == set(CATALOG)
    assert len(api.get('/lab/catalog.js').content) < 100_000
    assert api.get(panels[0]['image']).headers['content-type'] == 'image/webp'
    for path in ['/facade/config.json', '/facade/google-mail/Code.gs', '/facade/google-mail/deployment.json', '/lab/images/missing']:
        assert api.get(path).status_code == 404


def test_result_restores_editor_and_checks_job_access(api, monkeypatch):
    job_id = str(uuid.uuid4())
    assert api.get('/result/' + job_id).status_code == 404
    checked = []
    monkeypatch.setattr(service, 'job_row', lambda value: checked.append(value))
    response = api.get('/result/' + job_id)
    assert checked == [job_id]
    assert response.status_code == 200
    assert '/facade/facade-editor.js' in response.text
    assert '/facade/facade.js' in response.text
    assert '/facade/lead.js' not in response.text
    assert response.headers['Cache-Control'] == 'no-store'


def photo():
    image=Image.fromarray(np.random.default_rng(3).integers(20,220,(800,1200,3),dtype=np.uint8))
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


def test_missing_remote_texture_rejects_before_queueing(api):
    panel = next(p for p in CATALOG.values() if p['visualizationTexture'].startswith('https:'))
    payload = submission()
    payload['panels'] = [dict(id=panel['id'], base=None, mm=None)]
    response = upload(api, payload)
    assert response.status_code == 503
    with service.connect() as db:
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0


def upload(api,payload=None):
    return api.post('/api/facade/jobs',data={'metadata':json.dumps(payload or submission())},
                    files={'photo':('wall.png',photo(),'image/png')})


def test_structural_masks_are_saved_and_expire_with_result(api, monkeypatch):
    class StructuralModel:
        def predict(self, image):
            shape = (image.height, image.width)
            wall = np.zeros(shape, bool)
            wall[100:-100, 100:-100] = True
            openings = np.zeros(shape, bool)
            openings[240:360, 240:360] = True
            plinth = wall.copy()
            plinth[:620] = False
            return wall*.99, wall, dict(openingMask=openings, plinthMask=plinth,
                plinthBoundary=dict(slope=0., intercept=620., materialDelta=30.))
    monkeypatch.setattr(service, 'MODEL', StructuralModel())
    monkeypatch.setattr(service, 'load_texture', lambda panel: Image.new('RGB', (80, 40), 'red'))
    response = upload(api)
    assert response.status_code == 202
    job_id = response.json()['id']
    job = api.get('/api/facade/jobs/'+job_id).json()
    assert job['status'] == 'ready' and job['factors']['plinthDetected']
    before = np.asarray(Image.open(io.BytesIO(api.get(job['before']).content)))
    after = np.asarray(Image.open(io.BytesIO(api.get(job['variants'][0]['after']).content)))
    for name in ('mask-openings.png', 'mask-plinth.png'):
        url = f'/api/facade/jobs/{job_id}/image/{name}'
        mask_response = api.get(url)
        assert mask_response.status_code == 200
        exclusion = np.asarray(Image.open(io.BytesIO(mask_response.content))) > 0
        assert exclusion.any() and np.array_equal(before[exclusion], after[exclusion])
    with service.connect() as db:
        db.execute('UPDATE jobs SET expires=0 WHERE id=?', (job_id,))
    assert api.get(url).status_code == 404


def test_retake_preserves_detected_openings_for_manual_recovery(api, monkeypatch):
    class NoWallWithOpening:
        def predict(self, image):
            blank = np.zeros((image.height,image.width), bool)
            opening = blank.copy()
            opening[240:360,240:360] = True
            return blank.astype(float), blank, dict(openingMask=opening)
    monkeypatch.setattr(service, 'MODEL', NoWallWithOpening())
    job_id = upload(api).json()['id']
    assert api.get('/api/facade/jobs/'+job_id).json()['status'] == 'retake'
    saved = np.asarray(Image.open(service.DATA / job_id / 'mask-openings.png'))
    assert saved[240:360,240:360].all()


@pytest.mark.parametrize('detector_status', ['unavailable', 'failed', 'ready'])
def test_opening_detector_availability_is_reported_to_customer(api, monkeypatch, detector_status):
    class DetectorStatus:
        def predict(self, image):
            wall = np.zeros((image.height,image.width), bool)
            wall[100:-100,100:-100] = True
            return wall*.99, wall, dict(openingDetectorStatus=detector_status)
    monkeypatch.setattr(service, 'MODEL', DetectorStatus())
    job_id = upload(api).json()['id']
    result = api.get('/api/facade/jobs/'+job_id).json()
    assert result['status'] == 'ready'
    if detector_status == 'ready':
        assert 'частина проємів може бути пропущена' in result['textureNote']
    else:
        assert 'Позначте вікна та двері вручну' in result['warning']


def test_api_pipeline_actions_retention_and_privacy(api):
    response=upload(api)
    assert response.status_code==202,response.text
    id=response.json()['id'];job=api.get('/api/facade/jobs/'+id)
    assert job.status_code==200 and job.json()['status']=='ready',job.text
    assert 'phone' not in job.text and 'Тест' not in job.text
    assert job.headers['x-robots-tag'].startswith('noindex')
    assert job.headers['cache-control']=='no-store'
    assert api.get(job.json()['variants'][0]['after']).status_code==200
    assert api.get('/facade/app.py').status_code==404
    assert api.get('/api/facade/admin/leads.csv').status_code==401
    first=api.post(f'/api/facade/jobs/{id}/actions',json={'action':'sample'})
    second=api.post(f'/api/facade/jobs/{id}/actions',json={'action':'sample'})
    assert first.json()['id']==second.json()['id']
    headers={'Authorization':'Bearer testing-admin'}
    assert 'phone' in api.get('/api/facade/admin/leads.csv',headers=headers).text
    metrics=api.get('/api/facade/admin/metrics',headers=headers).json()['test']
    assert metrics['conversionRate']==1 and metrics['highConfidenceRate']==1
    with service.connect() as db:db.execute('UPDATE jobs SET expires=0 WHERE id=?',(id,))
    assert api.get('/api/facade/jobs/'+id).status_code==404
    service.cleanup()
    assert not (service.DATA/id).exists()
    with service.connect() as db:
        assert db.execute('SELECT count(*) FROM leads').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM outbox').fetchone()[0]==0
    assert api.get('/api/facade/admin/metrics',headers=headers).json()['test']['conversionRate']==1


def test_opening_suggestion_requires_confirmation_before_mask_changes(api, monkeypatch):
    proposal=dict(kind='window', points=[dict(x=.35,y=.3),dict(x=.55,y=.3),
                  dict(x=.55,y=.6),dict(x=.35,y=.6)],score=.24)
    class SuggestionsModel:
        def predict(self,image):
            wall=np.zeros((image.height,image.width),bool);wall[100:-100,100:-100]=True
            return wall*.99,wall,dict(openingSuggestions=[proposal],wallMask=wall)
    monkeypatch.setattr(service,'MODEL',SuggestionsModel())
    monkeypatch.setattr(service,'load_texture',lambda panel: Image.new('RGB',(80,40),'red'))
    job_id=upload(api).json()['id'];path=f'/api/facade/jobs/{job_id}'
    result=api.get(path).json()
    assert result['openingSuggestions']==[proposal]
    automatic=np.asarray(Image.open(service.DATA/job_id/'mask.png'))
    assert automatic[250:450,430:640].all()
    body=dict(elements=[{k:proposal[k] for k in ('kind','points')}])
    response=api.put(path+'/correction',json=body)
    assert response.status_code==200,response.text
    corrected=response.json()
    assert corrected['openingSuggestions']==[proposal]
    assert not corrected['editing']['trainingConsent']
    before=np.asarray(Image.open(io.BytesIO(api.get(corrected['before']).content)))
    after=np.asarray(Image.open(io.BytesIO(api.get(corrected['variants'][0]['after']).content)))
    assert np.array_equal(before[250:450,430:640],after[250:450,430:640])


def test_manual_correction_persists_exclusions_consent_and_revision(api, monkeypatch):
    monkeypatch.setattr(service, 'load_texture', lambda panel: Image.new('RGB', (80, 40), 'red'))
    job_id = upload(api).json()['id']
    path = f'/api/facade/jobs/{job_id}'
    original = api.get(path).json()
    assert not original['editing']['trainingConsent']
    body = dict(elements=[dict(kind='window',points=[dict(x=.35,y=.3),dict(x=.55,y=.6)]),
                          dict(kind='plinth',points=[dict(x=.1,y=.78),dict(x=.9,y=.8)])])
    corrected = api.put(path+'/correction',json=body)
    assert corrected.status_code == 200, corrected.text
    result = corrected.json()
    assert result['factors']['manuallyEdited'] and not result['editing']['trainingConsent']
    assert result['variants'][0]['quote'] == original['variants'][0]['quote']
    before = np.asarray(Image.open(io.BytesIO(api.get(result['before']).content)))
    after = np.asarray(Image.open(io.BytesIO(api.get(result['variants'][0]['after']).content)))
    assert np.array_equal(before[250:450,430:640],after[250:450,430:640])
    assert np.array_equal(before[650:690,120:1080],after[650:690,120:1080])
    with service.connect() as db:
        annotation = db.execute('SELECT * FROM annotations WHERE job=?',(job_id,)).fetchone()
        assert annotation['review_status']=='pending' and not annotation['training_consent']
    assert api.put(path+'/correction',json=body).status_code == 409  # stale tab
    old_url = result['variants'][0]['after']
    body.update(revision=result['editing']['revision'],trainingConsent=True)
    result = api.put(path+'/correction',json=body).json()
    assert result['editing']['trainingConsent']
    assert api.get(old_url).status_code == 404
    monkeypatch.setattr(service, 'load_texture', lambda panel: (_ for _ in ()).throw(OSError('offline')))
    assert api.delete(path+'/training-consent').status_code == 200
    assert not api.get(path).json()['editing']['trainingConsent']
    monkeypatch.setattr(service, 'load_texture', lambda panel: Image.new('RGB', (80,40), 'red'))
    body.update(revision=result['editing']['revision'],trainingConsent=False)
    result = api.put(path+'/correction',json=body).json()
    assert not result['editing']['trainingConsent']
    assert api.get(path).json()['editing']['elements'] == body['elements']
    assert 'phone' not in api.get(path).text
    with service.connect() as db:
        db.execute('UPDATE jobs SET expires=0 WHERE id=?',(job_id,))
    assert api.get(result['variants'][0]['after']).status_code == 404
    assert api.put(path+'/correction',json=body).status_code == 404
    service.cleanup()
    with service.connect() as db:
        assert db.execute('SELECT count(*) FROM annotations').fetchone()[0]==0
    assert not (service.DATA/job_id).exists()


def test_correction_error_identifies_element_and_accepts_polygon_openings(api, monkeypatch):
    monkeypatch.setattr(service,'load_texture',lambda panel: Image.new('RGB',(80,40),'red'))
    job_id = upload(api).json()['id']
    path = f'/api/facade/jobs/{job_id}/correction'
    def shape(coords):
        return dict(kind='window',points=[dict(x=x,y=y) for x,y in coords])
    valid = shape([(.2,.2),(.4,.2),(.4,.4),(.2,.4),(.2,.2)])
    invalid = shape([(.5,.2),(.8,.5),(.5,.5),(.8,.2)])
    response = api.put(path,json=dict(elements=[valid,invalid]))
    assert response.status_code == 422
    error = response.json()
    assert '№2' in error['detail'] and 'перетинати' in error['detail']
    assert error['invalidElements'] == [1]
    assert api.put(path,json=dict(elements=[valid])).status_code == 200


def test_retake_can_be_corrected_without_model_and_failed_save_keeps_previous(api, monkeypatch):
    monkeypatch.setattr(service, 'load_texture', lambda panel: Image.new('RGB', (80,40), 'red'))
    job_id = upload(api).json()['id']
    path = f'/api/facade/jobs/{job_id}'
    original = api.get(path).json()
    def broken_texture(panel):
        raise OSError('test')
    monkeypatch.setattr(service, 'load_texture', broken_texture)
    assert api.put(path+'/correction',json={}).status_code == 503
    assert api.get(path).json()['variants'] == original['variants']
    assert api.get(path).json()['editing']['revision'] is None
    with service.connect() as db:
        db.execute("UPDATE jobs SET status='retake',result=? WHERE id=?",(json.dumps(dict(
            message='retake',confidence=0.,before=original['before'])),job_id))
    assert api.get(original['before']).status_code == 200
    assert api.put(path+'/correction',json={}).status_code == 422
    monkeypatch.setattr(service,'MODEL',None)
    monkeypatch.setattr(service,'load_texture',lambda panel: Image.new('RGB',(80,40),'red'))
    body = dict(elements=[dict(kind='facade',points=[dict(x=.1,y=.1),dict(x=.9,y=.1),
        dict(x=.9,y=.85),dict(x=.1,y=.85)])])
    response = api.put(path+'/correction',json=body)
    assert response.status_code == 200, response.text
    assert response.json()['status']=='ready' and response.json()['confidence']==0.


def test_merge_archive_is_deleted_with_expired_job(api):
    job=upload(api).json()['id']
    with service.connect() as db:
        db.execute('INSERT INTO lead_merge_archive VALUES(?,?,?,?,?,?)',
                   ('old-lead',job,'canonical',time.time(),'{}','{}'))
        db.execute('UPDATE jobs SET expires=0 WHERE id=?',(job,))
    service.cleanup()
    with service.connect() as db:
        assert db.execute('SELECT count(*) FROM lead_merge_archive WHERE job=?',(job,)).fetchone()[0]==0


def test_api_rejects_invalid_input_and_low_confidence(api,monkeypatch):
    p=submission();p['consent']=False;assert upload(api,p).status_code==422
    p=submission();p['panels'][0]['id']='invented';assert upload(api,p).status_code==422
    p=submission();p['panels'][0]['mm']=999;assert upload(api,p).status_code==422
    class NoWall:
        def predict(self,image):
            blank=np.zeros((image.height,image.width),bool);return blank.astype(float),blank
    monkeypatch.setattr(service,'MODEL',NoWall())
    response=upload(api);id=response.json()['id']
    result=api.get('/api/facade/jobs/'+id).json()
    assert result['status']=='retake' and 'variants' not in result and 'before' in result
    assert api.get(f'/api/facade/jobs/{id}/image/before.png').status_code==200
    assert api.get(f'/api/facade/jobs/{id}/image/after-0.png').status_code==404
    assert api.post(f'/api/facade/jobs/{id}/actions',json={'action':'sample'}).status_code==409
    monkeypatch.setattr(service,'MODEL',None)
    assert upload(api).status_code==503


# ---- P0 regression tests (added by Claude; need the full web stack: run with pytest) ----

def test_chunked_upload_without_content_length_is_refused(api):
    # httpx sends an iterator body with Transfer-Encoding: chunked and no Content-Length.
    response = api.post('/api/facade/jobs', content=iter([b'x' * 1024] * 4))
    assert response.status_code == 411


def test_phone_is_normalised_and_junk_rejected(api):
    p = submission(); p['phone'] = '+38 (050) 123-45-67'
    response = upload(api, p)
    assert response.status_code == 202, response.text
    with service.connect() as db:
        stored = json.loads(db.execute('SELECT payload FROM jobs WHERE id=?', (response.json()['id'],)).fetchone()[0])
    assert stored['phone'] == '+380501234567'
    p = submission(); p['phone'] = '0000000000'
    assert upload(api, p).status_code == 422


def test_csv_export_keeps_plus_in_phone_and_readable_date(api):
    job = upload(api).json()['id']
    api.post(f'/api/facade/jobs/{job}/actions', json={'action': 'sample'})
    text = api.get('/api/facade/admin/leads.csv', headers={'Authorization': 'Bearer testing-admin'}).text
    assert '+380501234567' in text and "'+380501234567" not in text
    assert 'T' in text.splitlines()[1].split(',')[1]  # ISO date, not a raw epoch float


def test_csv_normalises_legacy_formatted_phone(api):
    job=upload(api).json()['id']
    api.post(f'/api/facade/jobs/{job}/actions',json={'action':'sample'})
    payload=submission();payload['phone']='+38 (050) 123-45-67'
    with service.connect() as db:
        db.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(payload),job))
    text=api.get('/api/facade/admin/leads.csv',headers={'Authorization':'Bearer testing-admin'}).text
    assert '+380501234567' in text and "'+380501234567" not in text


def test_heic_photo_upload(api):
    image=Image.fromarray(np.random.default_rng(5).integers(20,220,(800,1200,3),dtype=np.uint8))
    encoded=io.BytesIO();image.save(encoded,format='HEIF')
    response=api.post('/api/facade/jobs',data={'metadata':json.dumps(submission())},
                      files={'photo':('test.heic',encoded.getvalue(),'image/heic')})
    assert response.status_code==202,response.text
    assert api.get('/api/facade/jobs/'+response.json()['id']).json()['status']=='ready'


def test_stuck_jobs_do_not_block_new_uploads(api):
    old = time.time() - 7200
    with service.connect() as db:
        for number in range(CONFIG['maxPendingJobs']):
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',
                       (str(uuid.uuid4()), old, time.time() + 86400, 'queued', '{}', None, 'test', 'other-ip'))
    assert upload(api).status_code == 202   # would be 429 before the reaper existed
    with service.connect() as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE status='failed'").fetchone()[0] >= CONFIG['maxPendingJobs']


def test_process_job_with_unreadable_payload_fails_instead_of_staying_queued(api):
    job = str(uuid.uuid4())
    with service.connect() as db:
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',
                   (job, time.time(), time.time() + 86400, 'queued', '{"broken": true}', None, 'test', 'ip'))
    service.process_job(job)
    with service.connect() as db:
        assert db.execute('SELECT status FROM jobs WHERE id=?', (job,)).fetchone()[0] == 'failed'


def test_duplicate_action_keeps_one_lead_and_one_outbox_row(api):
    job = upload(api).json()['id']
    ids = {api.post(f'/api/facade/jobs/{job}/actions', json={'action': 'estimate'}).json()['id'] for _ in range(3)}
    assert len(ids) == 1
    with service.connect() as db:
        assert db.execute('SELECT count(*) FROM leads WHERE job=?', (job,)).fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM outbox WHERE job=?', (job,)).fetchone()[0] == 1


def test_admin_routes_answer_401_not_500_for_non_ascii_authorization(api):
    for header in ('Bearer тест', 'Bearer testing-admin-é'):
        # httpx rejects non-ASCII str headers before sending a request. Raw bytes
        # exercise Starlette's received-header path and the actual API guard.
        response = api.get('/api/facade/admin/metrics', headers=[(b'authorization', header.encode('utf-8'))])
        assert response.status_code == 401, response.text
