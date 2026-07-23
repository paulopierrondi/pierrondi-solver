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
    )
