"""Shared test setup.

Tests are offline by default: provider keys are removed from the environment and every
outbound socket connection except loopback raises ``NetworkBlockedError``. Only tests
marked ``live`` (``make test-live``, B5) skip this guard.
"""

import ipaddress
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

PROVIDER_ENV_VARS = ("OPENAI_API_KEY", "TYPESAFE_API_KEY")


class NetworkBlockedError(RuntimeError):
    pass


def _is_loopback(address: object) -> bool:
    if isinstance(address, str | bytes):  # AF_UNIX path
        return True
    host = address[0] if isinstance(address, tuple) else address
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def offline_guard(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live"):
        return
    for name in PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(sock: socket.socket, address: object) -> None:
        if not _is_loopback(address):
            raise NetworkBlockedError(f"offline test tried to connect to {address!r}")
        return real_connect(sock, address)

    def guarded_connect_ex(sock: socket.socket, address: object) -> int:
        if not _is_loopback(address):
            raise NetworkBlockedError(f"offline test tried to connect to {address!r}")
        return real_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "controlproof.sqlite3"


@pytest.fixture
def settings(db_path: Path) -> Settings:
    return Settings(db_path=db_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
