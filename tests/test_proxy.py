"""Tests for the proxy / identity layer (vetor C).

CI-safe: no network. Rotating/Sticky backends use injected fake clients.
"""
from __future__ import annotations

from pierrondi_solver.proxy import (
    IdentityContext,
    ProxyConfig,
    RotatingProxyBackend,
    StaticProxyBackend,
    StickyProxyBackend,
    build_proxy_backend,
)


# --- ProxyConfig --------------------------------------------------------

def test_proxy_config_fingerprint_is_stable_and_short():
    p = ProxyConfig(connect_string="http://u:p@host:8080")
    assert len(p.fingerprint) == 8
    assert p.fingerprint == ProxyConfig(connect_string="http://u:p@host:8080").fingerprint
    assert p.fingerprint != ProxyConfig(connect_string="http://other@host:8080").fingerprint


def test_proxy_config_kind_defaults_static():
    assert ProxyConfig(connect_string="x").kind == "static"


# --- IdentityContext ----------------------------------------------------

def test_identity_context_consistent_requires_all_axes():
    assert IdentityContext().consistent is False
    assert IdentityContext(user_agent="UA").consistent is False
    ctx = IdentityContext(
        user_agent="UA",
        proxy=ProxyConfig(connect_string="http://host:8080"),
        cookies={"cf_clearance": "TOKEN"},
    )
    assert ctx.consistent is True


def test_identity_context_inconsistent_without_clearance():
    ctx = IdentityContext(
        user_agent="UA",
        proxy=ProxyConfig(connect_string="http://host:8080"),
        cookies={"other": "x"},
    )
    assert ctx.consistent is False


# --- StaticProxyBackend -------------------------------------------------

def test_static_proxy_returns_none_when_unset():
    assert StaticProxyBackend("").resolve() is None


def test_static_proxy_returns_config_when_set():
    cfg = StaticProxyBackend("http://u:p@host:8080").resolve()
    assert cfg is not None
    assert cfg.connect_string == "http://u:p@host:8080"
    assert cfg.kind == "static"


# --- RotatingProxyBackend -----------------------------------------------

class _FakeClient:
    def __init__(self, text="http://rot:pass@1.2.3.4:9000"):
        self._text = text
        self.calls = 0

    def get(self, url):
        self.calls += 1

        class _Resp:
            text = self._text

        return _Resp()


def test_rotating_proxy_fetches_from_endpoint():
    client = _FakeClient("socks5://5.6.7.8:1080")
    backend = RotatingProxyBackend(endpoint_url="http://provider/api", client=client)
    cfg = backend.resolve()
    assert cfg is not None
    assert cfg.connect_string == "socks5://5.6.7.8:1080"
    assert cfg.kind == "rotating"
    assert client.calls == 1


def test_rotating_proxy_none_when_endpoint_unset():
    assert RotatingProxyBackend("").resolve() is None


def test_rotating_proxy_none_on_exception():
    class _BoomClient:
        def get(self, url):
            raise ConnectionError("down")

    backend = RotatingProxyBackend(endpoint_url="http://x", client=_BoomClient())
    assert backend.resolve() is None


# --- StickyProxyBackend -------------------------------------------------

def test_sticky_proxy_caches_same_key_within_ttl():
    client = _FakeClient("http://sticky:8080")
    backend = StickyProxyBackend(endpoint_url="http://provider", ttl_s=600, client=client)
    first = backend.resolve(session_key="sess-1")
    second = backend.resolve(session_key="sess-1")
    assert first.connect_string == second.connect_string == "http://sticky:8080"
    assert client.calls == 1  # cached; only one fetch


def test_sticky_proxy_rotates_different_keys():
    client = _FakeClient("http://sticky:8080")
    backend = StickyProxyBackend(endpoint_url="http://provider", ttl_s=600, client=client)
    backend.resolve(session_key="sess-1")
    backend.resolve(session_key="sess-2")
    assert client.calls == 2  # different keys -> different fetches


def test_sticky_proxy_none_when_endpoint_unset():
    assert StickyProxyBackend("").resolve(session_key="x") is None


# --- build_proxy_backend ------------------------------------------------

def test_build_static_default():
    backend = build_proxy_backend({})
    assert isinstance(backend, StaticProxyBackend)
    assert backend.resolve() is None


def test_build_static_from_env():
    backend = build_proxy_backend({"SOLVER_PROXY": "http://static:8080"})
    cfg = backend.resolve()
    assert cfg is not None
    assert cfg.connect_string == "http://static:8080"


def test_build_rotating_when_endpoint():
    backend = build_proxy_backend({"SOLVER_PROXY_ENDPOINT": "http://provider"})
    assert isinstance(backend, RotatingProxyBackend)


def test_build_sticky_when_flagged():
    backend = build_proxy_backend(
        {"SOLVER_PROXY_ENDPOINT": "http://provider", "SOLVER_PROXY_STICKY": "1"}
    )
    assert isinstance(backend, StickyProxyBackend)


def test_build_sticky_honors_ttl():
    backend = build_proxy_backend(
        {
            "SOLVER_PROXY_ENDPOINT": "http://provider",
            "SOLVER_PROXY_STICKY": "1",
            "SOLVER_PROXY_STICKY_TTL": "42",
        }
    )
    assert isinstance(backend, StickyProxyBackend)
    assert backend._ttl == 42
