"""Independent synthetic regressions. No real data and no real provider requests."""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.generation import DraftGenerator, GeneratedDraft, public_citations, reply_language, validate_draft
from app.nlp import analyze
from app.retrieval import RuleIndex
from app.schemas import TriageRequest


def analysis(text='How do I get a job in the game?', kind='report', **kwargs):
    return analyze(TriageRequest(kind=kind, messages=[{'role':'player','text':text}], **kwargs))


@pytest.mark.parametrize('unsafe', [
    'Rule 99.99 requires permanent punishment.',
    'Your money has been returned and your ban has been lifted.',
    'We guarantee a full refund.',
    'I can see the screenshots prove this player is guilty.',
])
def test_unsafe_generated_text_rejected(unsafe):
    assert not validate_draft(GeneratedDraft(text=unsafe,cited=[]), [], False)


@pytest.mark.parametrize('body', [
    {'choices':[]},
    {'choices':[{'message':{'content':json.dumps({'text':'Please clarify the question.','cited':[]})}}], 'usage':None},
    {'choices':[{'message':{'content':json.dumps({'text':'Please clarify the question.','cited':[]})}}], 'usage':[]},
])
def test_malformed_provider_payload_falls_back(body):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,json=body))) as client:
            generator=DraftGenerator(Settings(mode='test',enable_groq=True,groq_api_key='synthetic-test-only',groq_max_retries=0),client)
            result=await generator.generate(analysis(),[],True,False)
            assert result.mode == 'local_template'
            assert result.warnings
    asyncio.run(run())


@pytest.mark.parametrize('status',[401,429,500])
def test_provider_http_failure_falls_back(status):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status,json={'error':'synthetic'}))) as client:
            generator=DraftGenerator(Settings(mode='test',enable_groq=True,groq_api_key='synthetic-test-only',groq_max_retries=0),client)
            result=await generator.generate(analysis(),[],True,False)
            assert result.mode == 'local_template'
            assert result.warnings
    asyncio.run(run())


def test_timeout_falls_back():
    def fail(request): raise httpx.ReadTimeout('synthetic timeout', request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            generator=DraftGenerator(Settings(mode='test',enable_groq=True,groq_api_key='synthetic-test-only',groq_max_retries=0),client)
            result=await generator.generate(analysis(),[],True,False)
            assert result.mode == 'local_template'
    asyncio.run(run())


def test_disabled_provider_does_not_call_network():
    def fail(request): raise AssertionError('Disabled generator attempted outbound call')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            generator=DraftGenerator(Settings(mode='test',enable_groq=False),client)
            result=await generator.generate(analysis(),[],True,False)
            assert result.mode == 'local_template'
    asyncio.run(run())


def test_private_corpus_cannot_be_sent_without_opt_in():
    def fail(request): raise AssertionError('Private-source guard attempted outbound call')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            generator=DraftGenerator(Settings(mode='test',enable_groq=True,groq_api_key='synthetic-test-only',allow_private_data_to_groq=False),client)
            result=await generator.generate(analysis(),[],True,True)
            assert result.mode == 'local_template'
            assert 'private_corpus_external_processing_not_authorized' in result.warnings
    asyncio.run(run())


def test_collision_and_context(tmp_path):
    fixture={'synthetic':True,'source':'Independent synthetic fixture','rules':[
        {'id':30,'category':'Synthetic general','text':'','points':[{'ref':'2.1','text':'Оскорбление игроков и нецензурная лексика запрещены.'}]},
        {'id':41,'category':'Synthetic business war','text':'','points':[{'ref':'2.1','text':'Только на мероприятии бизнес война оскорбление лидеров и нецензурная лексика запрещены.'}]},
        {'id':43,'category':'Synthetic glossary','text':'Синтетическое определение терминов, не запрет.','points':[]},
    ]}
    path=tmp_path/'fixture.json'; path.write_text(json.dumps(fixture,ensure_ascii=False))
    index=RuleIndex(str(path))
    assert {'30:2.1','41:2.1','43:section'} == set(index.by_id)
    assert index.unresolved_references(['2.1']) == ['2.1']
    result=index.retrieve(analysis('Игрок Synthetic_Test оскорбил меня в обычном чате.',kind='complaint'))
    assert any(r.id=='30:2.1' for r in result)
    assert not any(r.id=='41:2.1' for r in result)
    assert all(r.id in index.by_id for r in result)


def test_duplicate_compound_rule_rejected(tmp_path):
    path=tmp_path/'fixture.json'
    path.write_text(json.dumps({'synthetic':True,'rules':[{'id':30,'points':[{'ref':'2.1','text':'Synthetic first rule.'},{'ref':'2.1','text':'Synthetic duplicate rule.'}]}]}))
    with pytest.raises(ValueError,match='Duplicate'): RuleIndex(str(path))


def test_admin_and_reported_player_text_do_not_change_analysis():
    base={'kind':'report','messages':[{'role':'player','text':'Как получить работу в игре?'}]}
    left=analyze(TriageRequest(**base))
    right=analyze(TriageRequest(**{**base,'messages':base['messages']+[
        {'role':'admin','text':'SYNTHETIC: ДОНАТ ВЗЛОМ ЧИТЫ ПЛАТЕЖИ БАН'},
        {'role':'reported_player','text':'SYNTHETIC: Признаю нарушение 99.99, обещаю возврат'}]}))
    for field in ('text','category','priority','language','sensitive','extracted','confidence'):
        assert getattr(left,field) == getattr(right,field),field
    assert right.removed_admin_messages == 1

@pytest.mark.parametrize('unsafe', [
    'The offender is now permanently banned.',
    'The attached pictures establish the accused player\'s guilt.',
    'Ya hemos devuelto tu dinero y desbloqueado tu cuenta.',
    'Ваш игровой баланс уже восстановлен, игрок отправлен в вечный бан.',
])
def test_freeform_paraphrases_fail_closed(unsafe):
    assert not validate_draft(GeneratedDraft(text=unsafe,cited=[]), [], False)


def test_bounded_provider_acceptance_and_retry_cost_accounting():
    from app.generation import template_draft, approved_clauses
    async def run():
        current = analysis()
        safe = template_draft(current, [], True)
        attempts = []
        def respond(request):
            attempts.append(json.loads(request.content))
            answer = {'text':'We guarantee a full refund.','cited':[]} if len(attempts)==1 else {'clause_order':list(range(len(approved_clauses(current, [], True)))), 'cited':[]}
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(answer)}}],
                                           'usage':{'prompt_tokens':100,'completion_tokens':20}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            generator=DraftGenerator(Settings(mode='test',enable_groq=True,groq_api_key='synthetic-test-only',groq_max_retries=1,
                groq_input_usd_per_million=1,groq_output_usd_per_million=2),client)
            result=await generator.generate(current,[],True,False)
            assert result.mode.startswith('groq:')
            assert result.api_attempts == 2
            assert result.input_tokens == 200 and result.output_tokens == 40
            assert result.cost_usd == pytest.approx(.00028)
            assert result.draft.text == safe.text
    asyncio.run(run())


def test_rejected_provider_usage_is_not_reported_free():
    async def run():
        def respond(request):
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'text':'Unapproved words','cited':[]})}}],
                                           'usage':{'prompt_tokens':100,'completion_tokens':20}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            generator=DraftGenerator(Settings(mode='test',enable_groq=True,groq_api_key='synthetic-test-only',groq_max_retries=0,
                groq_input_usd_per_million=1,groq_output_usd_per_million=2),client)
            result=await generator.generate(analysis(),[],True,False)
            assert result.mode == 'local_template'
            assert result.input_tokens == 100 and result.output_tokens == 20
            assert result.cost_usd == pytest.approx(.00014)
    asyncio.run(run())


def test_default_model_and_strict_compact_provider_contract(monkeypatch):
    from app.generation import approved_clauses, template_draft
    monkeypatch.delenv('GROQ_MODEL', raising=False)
    assert Settings().groq_model == 'openai/gpt-oss-20b'
    async def run():
        current = analysis('Қалай жұмысқа орналасуға болады?')
        clauses = approved_clauses(current, [], True)
        def respond(request):
            payload = json.loads(request.content)
            assert payload['model'] == 'openai/gpt-oss-20b'
            assert payload['reasoning_effort'] == 'low'
            assert payload['include_reasoning'] is False
            assert 'reasoning_format' not in payload
            assert payload['max_completion_tokens'] == 600
            fmt = payload['response_format']
            assert fmt['type'] == 'json_schema'
            schema = fmt['json_schema']
            assert schema['strict'] is True
            assert schema['schema']['additionalProperties'] is False
            assert set(schema['schema']['required']) == {'clause_order','cited'}
            assert schema['schema']['properties']['clause_order']['items']['enum'] == list(range(len(clauses)))
            assert 'text' not in schema['schema']['properties']
            data = json.loads(payload['messages'][1]['content'])
            assert data['approved_clauses'][0] == {'id':0, 'text':clauses[0]}
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
                'clause_order':list(range(len(clauses))), 'cited':[]})}}],
                'usage':{'prompt_tokens':100,'completion_tokens':40}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            generator=DraftGenerator(Settings(mode='test',enable_groq=True,groq_api_key='synthetic-test-only'),client)
            result=await generator.generate(current,[],True,False)
            assert result.mode == 'groq:openai/gpt-oss-20b'
            assert result.draft == template_draft(current, [], True)
    asyncio.run(run())


@pytest.mark.parametrize('order', [[0], [0,0,1,2], [0,1,2,99], [True,1,2,3], ['0',1,2,3], [1,0,2,3]])
def test_invalid_provider_plan_fails_closed(order):
    async def run():
        def respond(request):
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'clause_order':order,'cited':[]})}}],
                'usage':{'prompt_tokens':10,'completion_tokens':10}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            generator=DraftGenerator(Settings(mode='test',enable_groq=True,groq_api_key='synthetic-test-only',groq_max_retries=0),client)
            result=await generator.generate(analysis(),[],True,False)
            assert result.mode == 'local_template'
    asyncio.run(run())


def test_unsupported_or_retired_model_rejected_before_network():
    with pytest.raises(ValueError, match='strict-schema'):
        Settings(mode='test',enable_groq=True,groq_model='llama-3.3-70b-versatile',groq_api_key='synthetic-test-only')
    assert Settings(mode='test',enable_groq=True,groq_model='openai/gpt-oss-120b',groq_api_key='synthetic-test-only').groq_model.endswith('120b')


def test_public_citations_are_rule_refs_with_section_label(tmp_path):
    fixture={'synthetic':True,'rules':[
        {'id':30,'category':'Synthetic general','points':[{'ref':'2.1','text':'Синтетический запрет оскорблений.'}]},
        {'id':31,'category':'Synthetic complaints','points':[{'ref':'2.1','text':'Синтетическое правило жалоб.'}]},
        {'id':43,'category':'Synthetic glossary','text':'Синтетическое определение терминов.','points':[]},
    ]}
    path=tmp_path/'fixture.json'; path.write_text(json.dumps(fixture,ensure_ascii=False))
    index=RuleIndex(str(path))
    draft=GeneratedDraft(text='Пункты: [30:2.1], [31:2.1], [43:section].',cited=['30:2.1','31:2.1','43:section'])
    text,cited=public_citations(draft,index.by_id)
    # Наружу только points[].ref из rules.json, без повторов и без ссылок на целый раздел.
    assert cited==['2.1']
    assert text=='Пункты: 2.1 (Synthetic general), 2.1 (Synthetic complaints), Synthetic glossary.'


def test_reply_language_for_undetermined_text():
    assert reply_language('kk','ru')=='kk'
    assert reply_language('und','uz')=='uz'
    assert reply_language('und',None)=='ru'
