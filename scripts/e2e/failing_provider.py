"""Test-only real API factory with a failing in-memory provider transport.

No real credentials, external requests or private rule corpus are used.
"""
from dataclasses import replace

import httpx

from app.config import Settings
from app.generation import DraftGenerator
from app.main import create_app
from app.service import CopilotService


def factory():
    settings = replace(Settings(), rules_path=None, taxonomy_path=None,
                       local_encoder_path=None, enable_groq=True,
                       groq_api_key='synthetic-fault-test-only', groq_max_retries=0)

    def unavailable(request):
        return httpx.Response(503, json={'error': 'synthetic provider unavailable'})

    client = httpx.AsyncClient(transport=httpx.MockTransport(unavailable))
    generator = DraftGenerator(settings, client)
    generator.owns_client = True
    return create_app(settings, CopilotService(settings, generator))
