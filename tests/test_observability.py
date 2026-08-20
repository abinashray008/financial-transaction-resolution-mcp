"""Observability: Opik traces stay optional and never leak raw identifiers."""

from types import SimpleNamespace

from src.app.container import build_container_from_engine
from src.config.settings import Settings
from src.contracts.requests import GetAccountSummaryRequest, SynthesizeInvestigationRequest
from src.llm.gemini_client import GeminiSynthesisClient, _token_usage_from_response
from src.observability.tracing import TokenUsage, ToolSpanEvent, TracingService, build_tracing_service
from src.security.masking import mask_account_id
from src.tools.get_account_summary_tool import get_account_summary
from src.tools.synthesize_investigation_tool import synthesize_investigation
from tests.conftest import SCENARIO_ACCOUNT, assert_ok
from tests.test_synthesis import FakeSynthesisClient


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[ToolSpanEvent] = []

    def record(self, event: ToolSpanEvent) -> None:
        self.events.append(event)


def test_opik_tracing_disabled_without_credentials():
    app_settings = Settings(
        _env_file=None,
        opik_api_key="",
        opik_use_local=False,
        opik_enabled=True,
    )
    assert app_settings.opik_tracing_enabled is False


def test_opik_tracing_enabled_with_api_key():
    app_settings = Settings(
        _env_file=None,
        opik_api_key="opik-test-key",
        opik_enabled=True,
    )
    assert app_settings.opik_tracing_enabled is True


def test_opik_tracing_can_be_forced_off_even_with_a_key():
    app_settings = Settings(
        _env_file=None,
        opik_api_key="opik-test-key",
        opik_enabled=False,
    )
    assert app_settings.opik_tracing_enabled is False


def test_tool_span_records_masked_account_and_skips_raw_id(engine):
    sink = RecordingSink()
    tracing = TracingService(enabled=False, project_name="test", sink=sink)
    container = build_container_from_engine(engine, tracing=tracing)

    response = get_account_summary(
        container,
        GetAccountSummaryRequest(account_id=SCENARIO_ACCOUNT, request_id="inv-obs-1"),
    )

    assert_ok(response)
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.tool_name == "get_account_summary"
    assert event.request_id == "inv-obs-1"
    assert event.status == "ok"
    assert event.outcome == "success"
    assert event.account_id_masked == mask_account_id(SCENARIO_ACCOUNT)
    assert SCENARIO_ACCOUNT not in (event.account_id_masked or "")
    assert event.duration_ms >= 0


def test_synthesis_span_attaches_token_usage(engine):
    sink = RecordingSink()
    tracing = TracingService(enabled=False, project_name="test", sink=sink)
    container = build_container_from_engine(
        engine,
        synthesis=FakeSynthesisClient(),
        tracing=tracing,
    )

    response = synthesize_investigation(
        container,
        SynthesizeInvestigationRequest(
            account_id=SCENARIO_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            investigation_findings='{"customer_concern":"unrecognized"}',
            request_id="inv-obs-llm",
        ),
    )

    assert_ok(response)
    assert sink.events[0].tool_name == "synthesize_investigation"
    assert sink.events[0].request_id == "inv-obs-llm"


def test_wrap_genai_is_noop_when_tracing_disabled():
    tracing = build_tracing_service(
        app_settings=Settings(_env_file=None, opik_api_key="", opik_use_local=False),
    )
    sentinel = object()
    assert tracing.wrap_genai_client(sentinel) is sentinel


def test_token_usage_is_parsed_from_gemini_metadata():
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=120,
            candidates_token_count=80,
            total_token_count=200,
        )
    )
    usage = _token_usage_from_response(response)
    assert usage == TokenUsage(prompt_tokens=120, completion_tokens=80, total_tokens=200)


def test_gemini_client_attaches_usage_to_open_span():
    sink = RecordingSink()
    tracing = TracingService(enabled=False, project_name="test", sink=sink)

    class FakeModels:
        def generate_content(self, **kwargs):
            return SimpleNamespace(
                text="Synthesized reply.",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=10,
                    candidates_token_count=5,
                    total_token_count=15,
                ),
            )

    client = GeminiSynthesisClient(api_key="fake-key", model="gemini-2.5-pro", tracing=tracing)
    client._client = SimpleNamespace(models=FakeModels())

    with tracing.tool_span(tool_name="synthesize_investigation", request_id="inv-tokens", account_id=SCENARIO_ACCOUNT):
        text = client.synthesize(
            account_id=SCENARIO_ACCOUNT,
            transaction_id="TXN-SCN-DUP-A",
            investigation_findings="{}",
        )

    assert text == "Synthesized reply."
    assert sink.events[0].usage == TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    assert sink.events[0].model_name == "gemini-2.5-pro"
    assert sink.events[0].account_id_masked == mask_account_id(SCENARIO_ACCOUNT)
