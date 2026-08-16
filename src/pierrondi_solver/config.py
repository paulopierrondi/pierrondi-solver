"""Runtime configuration from environment. Secrets come from env only — never from files in repo."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

PROVIDER_PIERRONDI = "pierrondi"
PROVIDER_CAPSOLVER = "capsolver"
PROVIDER_TWOCAPTCHA = "2captcha"
PROVIDER_CAPMONSTER = "capmonster"

AUTO_CHAIN = [PROVIDER_PIERRONDI, PROVIDER_CAPSOLVER, PROVIDER_TWOCAPTCHA, PROVIDER_CAPMONSTER]

_KEY_ENV = {
    PROVIDER_CAPSOLVER: "CAPSOLVER_API_KEY",
    PROVIDER_TWOCAPTCHA: "TWOCAPTCHA_API_KEY",
    PROVIDER_CAPMONSTER: "CAPMONSTER_API_KEY",
}


@dataclass
class Config:
    provider: str = "auto"
    api_keys: dict = field(default_factory=dict)
    proxies: dict = field(default_factory=dict)
    telemetry_db: str = ""
    breaker_failure_rate: float = 0.30
    breaker_min_samples: int = 5
    breaker_window_s: int = 3600
    # Browser engine used by local clearance strategies (e.g. Cloudflare).
    # Nodriver is the unattended default: it stays headless while avoiding
    # webdriver fingerprints that managed challenges commonly reject.
    browser_engine: str = "nodriver"
    # Proxy connect string for the clearance harvest. When set, the browser
    # backend routes through it so cf_clearance binds to a controlled IP.
    proxy: str = ""
    proxy_endpoint: str = ""
    proxy_sticky: bool = False
    proxy_sticky_ttl: int = 600
    # hCaptcha accessibility cookie enabling the local audio path. Optional;
    # when unset the hcaptcha local strategy reports deps_missing.
    hcaptcha_accessibility_cookie: str = ""

    def chain(self) -> list[str]:
        if self.provider == "auto":
            return list(AUTO_CHAIN)
        return [self.provider]


def load_config(env: dict | None = None) -> Config:
    env = env if env is not None else os.environ
    db = env.get(
        "PIERRONDI_SOLVER_DB",
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "telemetry.db"),
    )
    return Config(
        provider=env.get("CAPTCHA_PROVIDER", "auto").strip().lower(),
        api_keys={name: env.get(key_env, "") for name, key_env in _KEY_ENV.items()},
        proxies={"capsolver": env.get("CAPSOLVER_PROXY", "")},
        telemetry_db=os.path.abspath(db),
        breaker_failure_rate=float(env.get("SOLVER_BREAKER_FAILURE_RATE", "0.30")),
        breaker_min_samples=int(env.get("SOLVER_BREAKER_MIN_SAMPLES", "5")),
        breaker_window_s=int(env.get("SOLVER_BREAKER_WINDOW_S", "3600")),
        browser_engine=env.get("SOLVER_BROWSER_ENGINE", "nodriver").strip().lower(),
        proxy=env.get("SOLVER_PROXY", "").strip(),
        proxy_endpoint=env.get("SOLVER_PROXY_ENDPOINT", "").strip(),
        proxy_sticky=env.get("SOLVER_PROXY_STICKY", "").strip().lower()
        in ("1", "true", "yes"),
        proxy_sticky_ttl=int(env.get("SOLVER_PROXY_STICKY_TTL", "600")),
        hcaptcha_accessibility_cookie=env.get("HCAPTCHA_ACCESSIBILITY_COOKIE", "").strip(),
    )
