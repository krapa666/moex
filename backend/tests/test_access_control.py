from app.main import resolve_network_principal
from starlette.requests import Request


def make_request(scope_header: str | None = None, client_ip: str = "172.18.0.5") -> Request:
    headers = []
    if scope_header is not None:
        headers.append((b"x-moex-access-scope", scope_header.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/auth/me",
            "headers": headers,
            "client": (client_ip, 12345),
            "server": ("backend", 8000),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_missing_proxy_scope_is_guest_even_from_private_proxy_ip() -> None:
    assert resolve_network_principal(make_request()) is None


def test_explicit_internet_scope_is_guest() -> None:
    assert resolve_network_principal(make_request("internet")) is None


def test_explicit_local_scope_is_admin() -> None:
    principal = resolve_network_principal(make_request("local", client_ip="203.0.113.5"))

    assert principal is not None
    assert principal.username == "local-network"
    assert principal.is_admin is True
