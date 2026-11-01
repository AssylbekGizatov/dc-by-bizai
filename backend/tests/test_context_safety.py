import asyncio
from dataclasses import replace
from app.config import Settings
from app.schemas import TriageRequest, Category
from app.service import CopilotService
from app.nlp import analyze

def test_unknown_and_sensitive_reports_require_human():
    async def run():
        svc=CopilotService(Settings(mode='test',database_path=':memory:'))
        svc.index.synthetic=False
        for text in ['Произошло непонятное происшествие вчера','Снимите бан','Оплатил донат, не пришёл','Аккаунт взломали']:
            ticket=await svc.process(TriageRequest(kind='report',messages=[{'role':'player','text':text}]),persist=False)
            assert ticket.result.needs_human
        await svc.close()
    asyncio.run(run())

def test_accused_context_cannot_reuse_cached_draft():
    async def run():
        svc=CopilotService(Settings(mode='test',database_path=':memory:'))
        for accused in ['Я был дома','Я был на улице']:
            ticket=await svc.process(TriageRequest(kind='complaint',messages=[{'role':'player','text':'Игрок оскорбил меня'},{'role':'reported_player','text':accused}]),persist=False)
            assert not ticket.diagnostics.cache_hit
        await svc.close()
    asyncio.run(run())
