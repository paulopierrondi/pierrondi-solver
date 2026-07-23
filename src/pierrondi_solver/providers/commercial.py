"""Commercial CAPTCHA-solving providers (fallback chain).

API keys come from env via Config — values are never logged or persisted.
Each provider implements the same Strategy contract and only runs when its
key is configured; otherwise it reports ``no_api_key`` and the chain skips
to the next provider.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

from ..models import ChallengeType, SolveRequest, StrategyOutcome

POLL_INTERVAL_S = 3.0

_TYPE_MAP = {
    "capsolver": {
        ChallengeType.recaptcha_v2: "ReCaptchaV2TaskProxyless",
        ChallengeType.recaptcha_v3: "ReCaptchaV3TaskProxyless",
        ChallengeType.hcaptcha: "HCaptchaTaskProxyless",
        ChallengeType.turnstile: "AntiTurnstileTaskProxyless",
        ChallengeType.cloudflare: "AntiCloudflareTask",  # requires proxy
    },
    "capmonster": {
        ChallengeType.recaptcha_v2: "RecaptchaV2TaskProxyless",
        ChallengeType.recaptcha_v3: "RecaptchaV3TaskProxyless",
        ChallengeType.hcaptcha: "HCaptchaTaskProxyless",
        ChallengeType.turnstile: "TurnstileTaskProxyless",
    },
    "2captcha": {
        ChallengeType.recaptcha_v2: "userrecaptcha",
        ChallengeType.recaptcha_v3: "userrecaptcha_v3",
        ChallengeType.hcaptcha: "hcaptcha",
        ChallengeType.turnstile: "turnstile",
    },
}

_BASE_URL = {
    "capsolver": "https://api.capsolver.com",
    "capmonster": "https://api.capmonster.cloud",
    "2captcha": "https://2captcha.com",
}

# Approximate public pricing (USD per 1000 solves) for cost telemetry.
_COST_PER_SOLVE = {
    ChallengeType.recaptcha_v2: 0.0015,
    ChallengeType.recaptcha_v3: 0.0020,
    ChallengeType.hcaptcha: 0.0015,
    ChallengeType.turnstile: 0.0010,
    ChallengeType.cloudflare: 0.0020,
}


class _TaskApiProvider:
    """Shared createTask/getTaskResult flow (CapSolver, CapMonster)."""

    def __init__(self, name: str, api_key: str, client: Optional[httpx.Client] = None,
                 proxy: str = "") -> None:
        self.name = f"commercial_{name}"
        self.provider = name
        self._api_key = api_key
        self._proxy = proxy
        self._client = client or httpx.Client(timeout=30)

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type in _TYPE_MAP[self.provider]

    def solve(self, request: SolveRequest) -> StrategyOutcome:
        started = time.monotonic()
        if not self._api_key:
            return self._outcome(started, reason="no_api_key")
        try:
            task_id = self._create_task(request)
            token = self._poll(task_id, request.timeout_s)
        except Exception as exc:
            return self._outcome(started, reason=f"{type(exc).__name__}: {exc}"[:400])
        return self._outcome(
            started,
            token=token,
            reason="" if token else "empty_solution",
            cost=_COST_PER_SOLVE.get(request.type, 0.0015),
        )

    def _create_task(self, request: SolveRequest) -> str:
        task = {
            "type": _TYPE_MAP[self.provider][request.type],
            "websiteURL": request.page_url,
            "websiteKey": request.sitekey,
        }
        if request.type == ChallengeType.recaptcha_v3:
            task["minScore"] = 0.7
            task["pageAction"] = "submit"
        if request.type == ChallengeType.cloudflare:
            if not self._proxy:
                raise RuntimeError("proxy_required: set CAPSOLVER_PROXY for AntiCloudflareTask")
            task = {
                "type": task["type"],
                "websiteURL": request.page_url,
                "proxy": self._proxy,
                "metadata": {"type": "challenge"},
            }
        resp = self._client.post(
            f"{_BASE_URL[self.provider]}/createTask",
            json={"clientKey": self._api_key, "task": task},
        )
        body = resp.json()
        if body.get("errorId"):
            raise RuntimeError(f"createTask: {body.get('errorCode')} {body.get('errorDescription')}")
        return str(body["taskId"])

    def _poll(self, task_id: str, timeout_s: int) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_S)
            resp = self._client.post(
                f"{_BASE_URL[self.provider]}/getTaskResult",
                json={"clientKey": self._api_key, "taskId": task_id},
            )
            body = resp.json()
            if body.get("errorId"):
                raise RuntimeError(f"getTaskResult: {body.get('errorCode')}")
            if body.get("status") == "ready":
                solution = body.get("solution", {})
                return solution.get("gRecaptchaResponse") or solution.get("token", "")
        raise TimeoutError(f"task {task_id} not ready in {timeout_s}s")

    def _outcome(self, started: float, token: str = "", reason: str = "", cost: float = 0.0):
        return StrategyOutcome(
            token=token or None,
            strategy="task_api",
            provider=self.provider,
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_usd=cost,
            reason=reason,
        )


class TwoCaptchaProvider:
    """2Captcha classic in.php/res.php flow."""

    provider = "2captcha"
    name = "commercial_2captcha"

    def __init__(self, api_key: str, client: Optional[httpx.Client] = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=30)

    def supports(self, challenge_type: ChallengeType) -> bool:
        return challenge_type in _TYPE_MAP[self.provider]

    def solve(self, request: SolveRequest) -> StrategyOutcome:
        started = time.monotonic()
        if not self._api_key:
            return self._outcome(started, reason="no_api_key")
        try:
            params = {
                "key": self._api_key,
                "method": _TYPE_MAP[self.provider][request.type],
                "googlekey" if request.type.name.startswith("recaptcha") else "sitekey": request.sitekey,
                "pageurl": request.page_url,
                "json": 1,
            }
            body = self._client.post(f"{_BASE_URL['2captcha']}/in.php", data=params).json()
            if body.get("status") != 1:
                raise RuntimeError(f"in.php: {body.get('request')}")
            token = self._poll(str(body["request"]), request.timeout_s)
        except Exception as exc:
            return self._outcome(started, reason=f"{type(exc).__name__}: {exc}"[:400])
        return self._outcome(
            started,
            token=token,
            reason="" if token else "empty_solution",
            cost=_COST_PER_SOLVE.get(request.type, 0.0015),
        )

    def _poll(self, request_id: str, timeout_s: int) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_S)
            body = self._client.get(
                f"{_BASE_URL['2captcha']}/res.php",
                params={"key": self._api_key, "action": "get", "id": request_id, "json": 1},
            ).json()
            if body.get("status") == 1:
                return str(body.get("request", ""))
            if body.get("request") != "CAPCHA_NOT_READY":
                raise RuntimeError(f"res.php: {body.get('request')}")
        raise TimeoutError(f"request {request_id} not ready in {timeout_s}s")

    def _outcome(self, started: float, token: str = "", reason: str = "", cost: float = 0.0):
        return StrategyOutcome(
            token=token or None,
            strategy="in_out_api",
            provider=self.provider,
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_usd=cost,
            reason=reason,
        )


def build_commercial_providers(api_keys: dict, proxies: dict | None = None) -> dict:
    proxies = proxies or {}
    return {
        "capsolver": _TaskApiProvider("capsolver", api_keys.get("capsolver", ""),
                                      proxy=proxies.get("capsolver", "")),
        "capmonster": _TaskApiProvider("capmonster", api_keys.get("capmonster", "")),
        "2captcha": TwoCaptchaProvider(api_keys.get("2captcha", "")),
    }
