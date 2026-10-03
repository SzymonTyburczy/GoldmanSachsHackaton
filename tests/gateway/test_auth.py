import logging
import os
import stat
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import (
    ADMIN,
    ANALYST_A,
    DEMO_TOKEN_VARIABLES,
    InvalidTokenConfigError,
    TokenDirectory,
    fill_missing_tokens,
)
from app.main import create_app
from app.settings import Settings
from tests.gateway.support import TOKENS

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
TASK_BODY = {"schema_version": 1, "client_id": "client-a"}

PROTECTED_ROUTES = [
    ("POST", "/v1/tasks"),
    ("GET", f"/v1/tasks/{uuid4()}"),
    ("POST", "/v1/execute"),
    ("GET", "/admin/policy"),
    ("PUT", "/admin/feed"),
    ("GET", "/admin/audit/export"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED_ROUTES)
def test_protected_routes_require_a_token(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path)

    assert response.status_code == 401
    assert response.json()["reason_code"] == "AUTH_REQUIRED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer wrong-token-0123456789abcdef0123456789",
        f"Basic {TOKENS['admin']}",
        f"Bearer {TOKENS['admin']}x",
        f"Bearer {TOKENS['admin'][:-1]}",
        "Bearer",
        TOKENS["admin"],
    ],
)
def test_invalid_credentials_are_rejected(client: TestClient, authorization: str) -> None:
    response = client.post("/v1/tasks", json=TASK_BODY, headers={"Authorization": authorization})

    assert response.status_code == 401
    assert TOKENS["admin"] not in response.text


@pytest.mark.parametrize("parameter", ["access_token", "token"])
def test_token_in_the_url_is_ignored(client: TestClient, parameter: str) -> None:
    response = client.post(f"/v1/tasks?{parameter}={TOKENS['admin']}", json=TASK_BODY)

    assert response.status_code == 401


def test_access_log_drops_query_strings(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    # Same call shape as uvicorn's access logger; TestClient itself bypasses uvicorn.
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:5000",
            "GET",
            f"/v1/tasks/x?access_token={TOKENS['admin']}",
            "1.1",
            401,
        )

    assert caplog.messages == ['127.0.0.1:5000 - "GET /v1/tasks/x HTTP/1.1" 401']


def test_each_token_maps_to_its_server_side_identity(
    client: TestClient, headers: dict[str, dict[str, str]]
) -> None:
    for identity in TOKENS:
        task = client.post("/v1/tasks", json=TASK_BODY, headers=headers[identity]).json()
        assert task["principal_id"] == identity
        assert task["agent_id"] == "demo-agent"


def test_role_in_the_body_is_rejected(
    client: TestClient, headers: dict[str, dict[str, str]]
) -> None:
    forged = {**TASK_BODY, "role": "admin", "principal_id": "admin"}

    response = client.post("/v1/tasks", json=forged, headers=headers["analyst-a"])

    assert response.status_code == 422
    assert {error["type"] for error in response.json()["errors"]} == {"extra_forbidden"}


def test_authentication_comes_before_the_schema(client: TestClient) -> None:
    forged = {**TASK_BODY, "role": "admin"}

    assert client.post("/v1/tasks", json=forged).status_code == 401


def test_role_header_does_not_grant_admin(
    client: TestClient, headers: dict[str, dict[str, str]]
) -> None:
    spoofed = headers["analyst-a"] | {"X-Role": "admin", "X-Principal-Id": "admin"}

    response = client.get("/admin/policy", headers=spoofed)

    assert response.status_code == 403
    assert response.json()["reason_code"] == "ADMIN_REQUIRED"


@pytest.mark.parametrize("identity", ["analyst-a", "reviewer-a"])
def test_admin_routes_require_the_admin_role(
    client: TestClient, headers: dict[str, dict[str, str]], identity: str
) -> None:
    response = client.get("/admin/events", headers=headers[identity])

    assert response.status_code == 403
    assert response.json()["reason_code"] == "ADMIN_REQUIRED"


def test_admin_passes_the_role_check(
    client: TestClient, headers: dict[str, dict[str, str]]
) -> None:
    response = client.get("/admin/events", headers=headers["admin"])

    assert response.status_code == 200


def test_missing_token_disables_only_that_identity(db_path: Path) -> None:
    directory = TokenDirectory.from_settings(Settings(db_path=db_path, token_admin=TOKENS["admin"]))

    assert directory.resolve(TOKENS["admin"]) is ADMIN
    assert directory.resolve(TOKENS["analyst-a"]) is None
    assert directory.resolve("") is None


@pytest.mark.parametrize(
    "tokens",
    [
        {"token_admin": "too-short"},
        {"token_admin": "x" * 257},
        {"token_admin": "spaces are not allowed in a bearer token!!"},
        {"token_admin": TOKENS["admin"], "token_analyst_a": TOKENS["admin"]},
    ],
)
def test_weak_or_ambiguous_tokens_stop_startup(db_path: Path, tokens: dict[str, str]) -> None:
    with pytest.raises(InvalidTokenConfigError) as error:
        create_app(Settings(db_path=db_path, **tokens))

    for value in tokens.values():
        assert value not in str(error.value)


def test_directory_resolves_each_identity(db_path: Path) -> None:
    directory = TokenDirectory.from_settings(
        Settings(db_path=db_path, token_analyst_a=TOKENS["analyst-a"], token_admin=TOKENS["admin"])
    )

    assert directory.resolve(TOKENS["analyst-a"]) is ANALYST_A
    assert directory.resolve(TOKENS["admin"]) is ADMIN


class TestFillMissingTokens:
    def env_file(self, tmp_path: Path) -> Path:
        path = tmp_path / ".env"
        path.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        return path

    def values(self, path: Path) -> dict[str, str]:
        pairs = (line.partition("=") for line in path.read_text(encoding="utf-8").splitlines())
        return {name: value for name, sep, value in pairs if sep and not name.startswith("#")}

    def test_fills_empty_tokens_with_distinct_random_values(self, tmp_path: Path) -> None:
        path = self.env_file(tmp_path)

        filled = fill_missing_tokens(path)

        values = self.values(path)
        tokens = [values[name] for name in DEMO_TOKEN_VARIABLES]
        assert filled == list(DEMO_TOKEN_VARIABLES)
        assert len(set(tokens)) == 3
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        # The generated file configures a working token directory.
        settings = Settings.from_env(values | {"CONTROLPROOF_DB_PATH": str(tmp_path / "db")})
        assert TokenDirectory.from_settings(settings).resolve(tokens[0]) is ANALYST_A

    def test_keeps_existing_values_and_other_lines(self, tmp_path: Path) -> None:
        path = self.env_file(tmp_path)
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "CONTROLPROOF_TOKEN_ADMIN=", f"CONTROLPROOF_TOKEN_ADMIN={TOKENS['admin']}"
            ).replace("OPENAI_API_KEY=", "OPENAI_API_KEY=kept-as-is"),
            encoding="utf-8",
        )

        assert fill_missing_tokens(path) == [
            "CONTROLPROOF_TOKEN_ANALYST_A",
            "CONTROLPROOF_TOKEN_REVIEWER_A",
        ]
        values = self.values(path)
        assert values["CONTROLPROOF_TOKEN_ADMIN"] == TOKENS["admin"]
        assert values["OPENAI_API_KEY"] == "kept-as-is"
        assert fill_missing_tokens(path) == []
        assert self.values(path) == values
