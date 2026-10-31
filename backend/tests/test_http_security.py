"""Synthetic HTTP/security/queue acceptance tests, no remote calls or private corpus."""
from __future__ import annotations
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app

TOKEN='audit-only-synthetic-token-not-a-credential'
AUTH={'Authorization':'Bearer '+TOKEN}
PAYLOAD={'text':'Синтетическое обращение: я застрял в текстурах.','kind':'report'}
TRIAGE={'kind':'report','messages':[{'role':'player','text':'Я застрял в текстурах.'}]}

@pytest.fixture
def client():
    settings=Settings(mode='test',database_path=':memory:',api_token=TOKEN,enable_groq=False,request_rate_per_minute=1000)
    with TestClient(create_app(settings),raise_server_exceptions=False) as value:
        yield value

@pytest.mark.parametrize('method,path,body',[
 ('GET','/api/tickets',None),('POST','/api/tickets',PAYLOAD),('POST','/triage',TRIAGE),
 ('GET','/api/tickets/nonexistent',None),('PATCH','/api/tickets/nonexistent/review',{'status':'reviewed'}),
 ('GET','/api/tickets/nonexistent/feedback',None),('GET','/api/rules',None),('GET','/api/metrics',None),
])
def test_private_routes_require_auth(client,method,path,body):
    kwargs={'json':body} if body is not None else {}
    assert client.request(method,path,**kwargs).status_code==401
    assert client.request(method,path,headers={'Authorization':'Bearer wrong'},**kwargs).status_code==401


def test_public_health_has_no_secret_and_states_baseline(client):
    health=client.get('/health'); assert health.status_code==200
    assert TOKEN not in health.text
    assert health.json()['classifier_mode']=='local_lexical_heuristics'
    assert health.json()['model_quality_validated'] is False
    ready=client.get('/ready').json()
    assert ready['capability']=='local_baseline'


def test_minimal_http_contract(client):
    response=client.post('/triage',headers=AUTH,json=TRIAGE)
    assert response.status_code==200,response.text
    body=response.json()
    assert set(body)=={'lang','category','priority','is_spam_or_duplicate','extracted','draft_reply','needs_human','confidence','reasons'}
    assert isinstance(body['needs_human'],bool)
    assert 0<=body['confidence']<=1


def test_malformed_json_and_invalid_type_do_not_500_or_echo_input(client):
    r=client.post('/triage',headers=AUTH|{'Content-Type':'application/json'},content='{broken')
    assert r.status_code==422
    sentinel='SYNTHETIC_PRIVATE_SENTINEL'
    r=client.post('/triage',headers=AUTH,json={'kind':'report','messages':sentinel})
    assert r.status_code==422
    assert sentinel not in r.text


@pytest.mark.parametrize('headers,body',[
 ({'Content-Length':'-1'},b'{}'),
 ({'Content-Length':'x'},b'{}'),
 ({},b'x'*131073),
 ({'Content-Length':'9'*5000},b'{}'),
])
def test_bad_or_oversize_content_length_is_rejected_cleanly(client,headers,body):
    response=client.post('/triage',headers=AUTH|headers,content=body)
    assert response.status_code in {400,413,422},response.status_code


def test_hostile_cross_origin_write_rejected(client):
    response=client.post('/api/tickets',headers=AUTH|{'Origin':'https://hostile.invalid'},json=PAYLOAD)
    assert response.status_code==403


def test_idempotency_replay_and_conflict(client):
    headers=AUTH|{'Idempotency-Key':'synthetic-replay'}
    a=client.post('/api/tickets',headers=headers,json=PAYLOAD)
    b=client.post('/api/tickets',headers=headers,json=PAYLOAD)
    assert a.status_code==b.status_code==201
    assert a.json()['id']==b.json()['id']
    assert client.get('/api/tickets',headers=AUTH).json()['total']==1
    conflict=client.post('/api/tickets',headers=headers,json=PAYLOAD|{'text':'Different synthetic question'})
    assert conflict.status_code==409


def test_concurrent_create_retries_produce_one_ticket(client):
    def create(_): return client.post('/api/tickets',headers=AUTH|{'Idempotency-Key':'synthetic-concurrent'},json=PAYLOAD)
    with ThreadPoolExecutor(max_workers=5) as pool: results=list(pool.map(create,range(5)))
    assert {r.status_code for r in results}=={201}
    assert len({r.json()['id'] for r in results})==1
    assert client.get('/api/tickets',headers=AUTH).json()['total']==1


def test_review_revision_blocks_duplicate_feedback(client):
    ticket=client.post('/api/tickets',headers=AUTH,json=PAYLOAD).json()
    body={'draft_reply':'Synthetic reviewed draft.','status':'reviewed','expected_revision':1}
    first=client.patch(f"/api/tickets/{ticket['id']}/review",headers=AUTH,json=body)
    duplicate=client.patch(f"/api/tickets/{ticket['id']}/review",headers=AUTH,json=body)
    assert first.status_code==200 and first.json()['revision']==2
    assert duplicate.status_code==409
    feedback=client.get(f"/api/tickets/{ticket['id']}/feedback",headers=AUTH).json()['items']
    assert len(feedback)==1 and feedback[0]['edited_draft']=='Synthetic reviewed draft.'
    assert client.get(f"/api/tickets/{ticket['id']}",headers=AUTH).json()['status']=='reviewed'


def test_parameterized_search_does_not_expand_results(client):
    client.post('/api/tickets',headers=AUTH,json=PAYLOAD)
    r=client.get('/api/tickets',headers=AUTH,params={'search':"' OR 1=1 --"})
    assert r.status_code==200 and r.json()['total']==0


def test_same_reporter_window_dedup_and_other_reporter_separation(client):
    def submit(reporter,when):
        return client.post('/triage',headers=AUTH,json=TRIAGE|{'reporter_hash':reporter,'created_at':when}).json()
    assert submit('synthetic-a','2026-01-01T10:00:00')['is_spam_or_duplicate'] is False
    assert submit('synthetic-a','2026-01-01T10:30:00')['is_spam_or_duplicate'] is True
    assert submit('synthetic-b','2026-01-01T10:30:00')['is_spam_or_duplicate'] is False
    assert submit('synthetic-a','2026-01-01T12:00:00')['is_spam_or_duplicate'] is False


FLOOD_TEXTS=['Синтетика: застрял в текстурах возле банка, не могу выйти.','Синтетика: как вступить в полицию на сервере?',
 'Синтетика: пропала машина из гаража после рестарта.','Синтетика: не работает голосовой чат в игре.',
 'Синтетика: где найти работу дальнобойщика новичку?','Синтетика: не открывается меню телефона персонажа.']


def test_flood_limit_flags_requests_after_five_per_hour(client):
    def submit(reporter,when,text):
        body={'kind':'report','reporter_hash':reporter,'created_at':when,'messages':[{'role':'player','text':text}]}
        return client.post('/triage',headers=AUTH,json=body).json()
    first=[submit('synthetic-flood',f'2026-01-01T10:{10*i:02d}:00',text) for i,text in enumerate(FLOOD_TEXTS[:5])]
    assert not any(any(r.startswith('Флуд') for r in item['reasons']) for item in first)
    sixth=submit('synthetic-flood','2026-01-01T10:50:00',FLOOD_TEXTS[5])
    assert sixth['is_spam_or_duplicate'] is True and sixth['needs_human'] is True
    assert any(r.startswith('Флуд: 6-е обращение') for r in sixth['reasons'])
    assert not any(r.startswith('Флуд') for r in submit('synthetic-other','2026-01-01T10:50:00',FLOOD_TEXTS[0])['reasons'])
    assert not any(r.startswith('Флуд') for r in submit('synthetic-flood','2026-01-01T12:00:00',FLOOD_TEXTS[1])['reasons'])


def test_flood_limit_setting_is_bounded():
    with pytest.raises(ValueError):
        Settings(mode='test',database_path=':memory:',flood_limit_per_hour=0)


def test_anonymous_same_text_is_not_personal_duplicate(client):
    for _ in range(2):
        assert client.post('/triage',headers=AUTH,json=TRIAGE).json()['is_spam_or_duplicate'] is False


def test_static_root_does_not_serve_parent_files(tmp_path):
    root=tmp_path/'public'; root.mkdir(); (root/'index.html').write_text('<h1>synthetic index</h1>')
    (tmp_path/'private.sqlite').write_text('SYNTHETIC_PRIVATE_SENTINEL')
    cfg=Settings(mode='test',database_path=':memory:',api_token=TOKEN,enable_groq=False,frontend_dist=str(root))
    with TestClient(create_app(cfg),raise_server_exceptions=False) as c:
        for path in ['/../private.sqlite','/%2e%2e/private.sqlite','/api/unknown']:
            response=c.get(path)
            assert 'SYNTHETIC_PRIVATE_SENTINEL' not in response.text


def test_static_root_does_not_serve_symlink_target(tmp_path):
    root=tmp_path/'public'; root.mkdir(); (root/'index.html').write_text('<h1>synthetic index</h1>')
    (tmp_path/'private.sqlite').write_text('SYNTHETIC_PRIVATE_SENTINEL')
    try:
        (root/'escape').symlink_to(tmp_path/'private.sqlite')
    except OSError as exc:
        if getattr(exc, 'winerror', None)==1314:
            pytest.skip('Windows account lacks the symbolic-link creation privilege; traversal checks run separately')
        raise
    cfg=Settings(mode='test',database_path=':memory:',api_token=TOKEN,enable_groq=False,frontend_dist=str(root))
    with TestClient(create_app(cfg),raise_server_exceptions=False) as c:
        response=c.get('/escape')
        assert response.status_code==404 and 'SYNTHETIC_PRIVATE_SENTINEL' not in response.text


def test_production_auth_required():
    with pytest.raises(ValueError,match='API_TOKEN'):
        Settings(mode='production',api_token=None,rules_path='/synthetic/unused')
