import httpx

from pierrondi_solver.models import ChallengeType, SolveRequest
from pierrondi_solver.providers.commercial import _TaskApiProvider, build_commercial_providers


def test_capsolver_supports_cloudflare():
    provider = _TaskApiProvider("capsolver", "KEY")
    assert provider.supports(ChallengeType.cloudflare)


def test_capmonster_does_not_support_cloudflare():
    provider = _TaskApiProvider("capmonster", "KEY")
    assert not provider.supports(ChallengeType.cloudflare)


def test_cloudflare_requires_proxy():
    provider = _TaskApiProvider("capsolver", "KEY")  # no proxy
    outcome = provider.solve(SolveRequest(
        type=ChallengeType.cloudflare, sitekey="", page_url="https://example.com"))
    assert outcome.solved is False
    assert "proxy_required" in outcome.reason


def test_cloudflare_no_key_short_circuits():
    provider = _TaskApiProvider("capsolver", "")
    outcome = provider.solve(SolveRequest(
        type=ChallengeType.cloudflare, sitekey="", page_url="https://example.com"))
    assert outcome.reason == "no_api_key"


def test_anti_cloudflare_task_payload():
    captured = {}

    class FakeClient:
        timeout = 30

        def post(self, url, json=None, **kw):
            captured["payload"] = json
            class Resp:
                def json(self):
                    return {"errorId": 1, "errorCode": "TEST_STOP",
                            "errorDescription": "stop before polling"}
            return Resp()

    provider = _TaskApiProvider("capsolver", "KEY", client=FakeClient(),
                                proxy="http://user:pass@residential:8000")
    provider.solve(SolveRequest(type=ChallengeType.cloudflare, sitekey="",
                                page_url="https://example.com/protected"))
    task = captured["payload"]["task"]
    assert task["type"] == "AntiCloudflareTask"
    assert task["proxy"] == "http://user:pass@residential:8000"
    assert task["websiteURL"] == "https://example.com/protected"


def test_build_providers_passes_proxy():
    providers = build_commercial_providers(
        {"capsolver": "KEY"}, proxies={"capsolver": "http://p:1"})
    assert providers["capsolver"]._proxy == "http://p:1"
