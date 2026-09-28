"""Exercise the provider boundary without an API key or network request."""
from time import monotonic
from types import SimpleNamespace
from unittest.mock import MagicMock
import json
import pytest
from backend.config import Settings
from backend.domain.contracts import TriageRequest
from backend.models.providers import OpenAIProvider, ProviderFailure, SynthesisContext, SYSTEM_PROMPT
from backend.policy.engine import PolicyEngine
from backend.rag.retriever import Retriever


def context():
    request = TriageRequest(sessionId='s',turnId='t',baseStateVersion=0,patientId='p',
        symptomDescription='I have a mild headache today.',
        patientDemographics={'ageInMonths':456,'isPregnant':False,'biologicalSex':'FEMALE'})
    engine = PolicyEngine(); extracted = engine.extract(request); manifest = Retriever().retrieve(request)
    plan = engine.plan(request,extracted,manifest)
    return SynthesisContext(request,extracted.facts,manifest,plan,'normal',monotonic()+2)


def test_provider_keeps_evidence_out_of_instructions_and_disables_sdk_retries():
    ctx = context(); provider = OpenAIProvider(Settings(provider_mode='openai'))
    output = {'recommendedDisposition':ctx.plan.disposition.value,'rationale':[c.model_dump() for c in ctx.plan.catalogue]}
    client = MagicMock(); client.with_options.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(refusal=None,content=json.dumps(output)))])
    provider.client = client
    assert provider.synthesize(ctx) == output
    client.with_options.assert_called_once()
    assert client.with_options.call_args.kwargs['max_retries'] == 0
    assert 0 < client.with_options.call_args.kwargs['timeout'] <= 2
    sent = client.chat.completions.create.call_args.kwargs
    assert sent['messages'][0] == {'role':'system','content':SYSTEM_PROMPT}
    data = json.loads(sent['messages'][1]['content'])
    assert sent['messages'][1]['role'] == 'user'
    assert data['evidence'] == ctx.manifest.model_dump(mode='json')
    assert data['facts'] == ctx.facts.model_dump(mode='json')
    assert sent['response_format']['json_schema']['strict'] is True
    client.chat.completions.create.assert_called_once()


def test_missing_provider_credentials_enters_failure_boundary_without_fallback():
    provider = OpenAIProvider(Settings(provider_mode='openai'))
    with pytest.raises(ProviderFailure,match='PROVIDER_CREDENTIALS_MISSING'):
        provider.synthesize(context())
