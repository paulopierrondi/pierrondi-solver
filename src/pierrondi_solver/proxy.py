"""Proxy / identity layer.

Cloudflare clearance is bound to (IP, User-Agent). Without proxy control,
clearance is single-use and tied to the host IP — useless for multi-account or
geo-diverse flows. This layer introduces:

- ``ProxyConfig``: a parsed proxy descriptor (scheme, host, port, auth, type).
- ``ProxyBackend``: a pluggable resolver that produces a usable proxy string for
  a given lane/session. Built-ins: static (env) and rotating (provider-backed).
- ``IdentityContext``: the (proxy, user_agent, cookies) bundle a clearance
  harvest reuses so the resulting cf_clearance is consistent across requests.

All proxy backends resolve to a ``connect string`` (e.g.
``http://user:pass@host:port``) that the browser backends pass to their launch
options. No proxy values are stored in telemetry — only a non-reversible hash of
the connect string for correlation.

Secrets (proxy credentials) come from env only, never from repo files.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass(frozen=True)
class ProxyConfig:
    """A parsed proxy descriptor.

    ``connect_string`` is the value passed to a browser's proxy option
    (``http://user:pass@host:port`` or ``socks5://host:port``). ``kind``
    describes the acquisition model for telemetry/correlation only.
    """

    connect_string: str
    kind: str = "static"  # "static" | "rotating" | "sticky"
    sticky_key: str = ""

    @property
    def fingerprint(self) -> str:
        """8-char non-reversible hash of the connect string for telemetry."""
        return hashlib.sha256(self.connect_string.encode()).hexdigest()[:8]


@dataclass
class IdentityContext:
    """The identity bundle a clearance harvest must keep consistent.

    Cloudflare binds ``cf_clearance`` to the IP that solved the challenge AND
    the User-Agent presented. Reusing the cookie with a different UA or IP
    invalidates it. This dataclass makes that invariant explicit and lets
    strategies pass the same identity through harvest + replay.
    """

    user_agent: str = ""
    proxy: Optional[ProxyConfig] = None
    cookies: dict = field(default_factory=dict)

    @property
    def consistent(self) -> bool:
        """True when every binding axis is present (UA + proxy + clearance)."""
        return bool(
            self.user_agent
            and self.proxy is not None
            and self.cookies.get("cf_clearance")
        )


class ProxyBackend(Protocol):
    """Resolves a proxy for a given lane/session.

    Implementations:
    - ``StaticProxyBackend``: a single env-configured proxy (``SOLVER_PROXY``).
    - ``RotatingProxyBackend``: rotates through a provider endpoint each call.
    - ``StickyProxyBackend``: returns the same proxy for a session key within a
      TTL window (so clearance harvest + replay share an IP).
    """

    def resolve(self, lane: str = "default") -> Optional[ProxyConfig]: ...


class StaticProxyBackend:
    """Single proxy from env (``SOLVER_PROXY``). Returns None when unset."""

    def __init__(self, connect_string: str = "") -> None:
        self._connect_string = connect_string

    def resolve(self, lane: str = "default") -> Optional[ProxyConfig]:
        if not self._connect_string:
            return None
        return ProxyConfig(connect_string=self._connect_string, kind="static")


class RotatingProxyBackend:
    """Rotates the proxy each call by re-fetching a connect string from a
    provider endpoint (``SOLVER_PROXY_ENDPOINT``). Used when each solve should
    come from a fresh residential IP."""

    def __init__(self, endpoint_url: str = "", client=None) -> None:
        self._endpoint = endpoint_url
        self._client = client

    def resolve(self, lane: str = "default") -> Optional[ProxyConfig]:
        if not self._endpoint:
            return None
        try:
            import httpx

            client = self._client or httpx.Client(timeout=10)
            connect_string = client.get(self._endpoint).text.strip()
        except Exception:
            return None
        if not connect_string:
            return None
        return ProxyConfig(connect_string=connect_string, kind="rotating")


class StickyProxyBackend:
    """Returns the same proxy for the same (lane, session_key) within ``ttl_s``.

    Backed by a rotating endpoint, but caches the result per key so the harvest
    and the subsequent replay requests share an IP. This is the backend that
    makes ``cf_clearance`` reusable across multiple HTTP calls."""

    def __init__(self, endpoint_url: str = "", ttl_s: int = 600, client=None) -> None:
        self._endpoint = endpoint_url
        self._ttl = ttl_s
        self._client = client
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def resolve(self, lane: str = "default", session_key: str = "default") -> Optional[ProxyConfig]:
        if not self._endpoint:
            return None
        cache_key = f"{lane}:{session_key}"
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached[1] < self._ttl:
                connect_string = cached[0]
            else:
                try:
                    import httpx

                    client = self._client or httpx.Client(timeout=10)
                    connect_string = client.get(self._endpoint).text.strip()
                except Exception:
                    return None
                if not connect_string:
                    return None
                self._cache[cache_key] = (connect_string, now)
        return ProxyConfig(
            connect_string=connect_string, kind="sticky", sticky_key=session_key
        )


def playwright_proxy(connect_string: str) -> dict:
    """Convert a proxy connect string to a Playwright proxy option dict.

    ``http://user:pass@host:port`` ->
    ``{"server": "http://host:port", "username": "user", "password": "pass"}``.
    Empty input -> ``{}`` (no proxy). Credentials stay inside the launch
    call and are never logged or returned in metadata.
    """
    if not connect_string:
        return {}
    from urllib.parse import urlsplit

    u = urlsplit(connect_string)
    if not u.hostname:
        return {}
    server = f"{u.scheme}://{u.hostname}"
    if u.port:
        server += f":{u.port}"
    out = {"server": server}
    if u.username:
        out["username"] = u.username
    if u.password:
        out["password"] = u.password
    return out


def build_proxy_backend(env: dict | None = None) -> ProxyBackend:
    """Build the proxy backend from env. Defaults to static (may be a no-op).

    Priority:
    1. ``SOLVER_PROXY_ENDPOINT`` + ``SOLVER_PROXY_STICKY=1`` -> StickyProxyBackend
    2. ``SOLVER_PROXY_ENDPOINT``                        -> RotatingProxyBackend
    3. ``SOLVER_PROXY``                                  -> StaticProxyBackend
    4. unset                                             -> StaticProxyBackend (None)
    """
    env = env if env is not None else os.environ
    endpoint = env.get("SOLVER_PROXY_ENDPOINT", "")
    sticky = env.get("SOLVER_PROXY_STICKY", "").strip().lower() in ("1", "true", "yes")
    ttl = int(env.get("SOLVER_PROXY_STICKY_TTL", "600"))

    if endpoint and sticky:
        return StickyProxyBackend(endpoint_url=endpoint, ttl_s=ttl)
    if endpoint:
        return RotatingProxyBackend(endpoint_url=endpoint)
    return StaticProxyBackend(connect_string=env.get("SOLVER_PROXY", ""))
