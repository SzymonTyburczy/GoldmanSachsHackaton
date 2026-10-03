import hashlib
import json
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from app import db, policy
from app.policy import Policy


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    db.init_db(db_path)
    with closing(db.connect(db_path)) as connection:
        yield connection


@pytest.fixture
def shipped() -> Policy:
    document = policy.read_config_file("policy", policy.DEFAULT_CONFIG_DIR / "policy.json")
    assert isinstance(document, Policy)
    return document


def with_threshold(document: Policy, threshold: float) -> Policy:
    semantic = document.semantic.model_copy(update={"block_threshold": threshold})
    return document.model_copy(update={"semantic": semantic})


def versions(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT version FROM config_versions WHERE kind = 'policy'")
    return [row["version"] for row in rows]


def test_each_activation_stores_the_next_version(conn: sqlite3.Connection, shipped: Policy) -> None:
    first = policy.activate(conn, "policy", shipped, expected_version=None, created_by="test")
    second = policy.activate(
        conn, "policy", with_threshold(shipped, 0.6), expected_version=1, created_by="admin"
    )

    assert (first.version, second.version) == (1, 2)
    active = policy.load_active(conn, "policy")
    assert active is not None
    assert (active.version, active.created_by) == (2, "admin")
    assert active.document.semantic.block_threshold == 0.6
    # Older versions stay stored and unchanged.
    assert policy.load(conn, "policy", 1).document == shipped


@pytest.mark.parametrize("expected", [None, 1, 3])
def test_stale_expected_version_changes_nothing(
    conn: sqlite3.Connection, shipped: Policy, expected: int | None
) -> None:
    policy.activate(conn, "policy", shipped, expected_version=None, created_by="test")
    policy.activate(conn, "policy", shipped, expected_version=1, created_by="test")

    with pytest.raises(policy.VersionConflictError):
        policy.activate(
            conn, "policy", with_threshold(shipped, 0.1), expected_version=expected, created_by="x"
        )

    assert versions(conn) == [1, 2]
    assert policy.active_versions(conn).policy_version == 2


def store_body(conn: sqlite3.Connection, body: dict, *, digest_of: dict | None = None) -> None:
    text = json.dumps(body)
    digest = hashlib.sha256(json.dumps(digest_of or body).encode()).hexdigest()
    conn.execute(
        "UPDATE config_versions SET body = ?, sha256 = ? WHERE kind = 'policy' AND version = 1",
        (text, digest),
    )


def test_edited_stored_body_is_refused(conn: sqlite3.Connection, shipped: Policy) -> None:
    policy.activate(conn, "policy", shipped, expected_version=None, created_by="test")
    original = json.loads(policy.canonical_json(shipped))
    edited = json.loads(policy.canonical_json(with_threshold(shipped, 0.99)))

    store_body(conn, edited, digest_of=original)  # valid policy, but not the stored one

    with pytest.raises(policy.StoredConfigError):
        policy.load(conn, "policy", 1)


def test_stored_body_is_validated_again_on_load(conn: sqlite3.Connection, shipped: Policy) -> None:
    policy.activate(conn, "policy", shipped, expected_version=None, created_by="test")
    body = json.loads(policy.canonical_json(shipped))
    body["controls"]["access"] = False

    store_body(conn, body)  # matching digest, but access switched off

    with pytest.raises(policy.StoredConfigError):
        policy.load(conn, "policy", 1)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    path = tmp_path / "config"
    shutil.copytree(policy.DEFAULT_CONFIG_DIR, path)
    return path


@pytest.fixture
def cli(db_path: Path, config_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONTROLPROOF_DB_PATH", str(db_path))

    def run(command: str) -> int:
        return policy.main([command, "--config-dir", str(config_dir)])

    return run


def active(db_path: Path) -> tuple[int | None, int | None]:
    with closing(db.connect(db_path)) as conn:
        current = policy.active_versions(conn)
    return current.policy_version, current.feed_version


def edit_policy(config_dir: Path, **semantic: object) -> None:
    path = config_dir / "policy.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["semantic"].update(semantic)
    path.write_text(json.dumps(body), encoding="utf-8")


def test_seed_activates_only_missing_kinds(
    cli, db_path: Path, config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli("seed") == 0
    assert active(db_path) == (1, 1)

    edit_policy(config_dir, block_threshold=0.5)
    assert cli("seed") == 0  # an existing configuration is never replaced by seed

    assert active(db_path) == (1, 1)
    assert "policy: version 1 stays active" in capsys.readouterr().out


def test_reload_activates_changed_files_only(cli, db_path: Path, config_dir: Path) -> None:
    cli("seed")
    assert cli("reload") == 0
    assert active(db_path) == (1, 1)  # unchanged files: no new versions

    edit_policy(config_dir, block_threshold=0.5)
    assert cli("reload") == 0

    assert active(db_path) == (2, 1)
    with closing(db.connect(db_path)) as conn:
        assert policy.load(conn, "policy", 2).document.semantic.block_threshold == 0.5


def test_invalid_file_leaves_the_active_configuration(
    cli, db_path: Path, config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli("seed")
    edit_policy(config_dir, block_threshold=0.5)  # valid change
    (config_dir / "threat-feed.json").write_text('{"schema_version": 1, "rules": [{}]}')

    assert cli("reload") == 1

    assert active(db_path) == (1, 1)  # neither file was activated
    error = capsys.readouterr().err
    assert "the active configuration is unchanged" in error
    assert "rules.0.rule_id: Field required" in error


def test_first_start_without_valid_files_activates_nothing(
    cli, db_path: Path, config_dir: Path
) -> None:
    edit_policy(config_dir, on_error="allow")

    assert cli("seed") == 1

    assert active(db_path) == (None, None)
