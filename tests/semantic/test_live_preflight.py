import asyncio

from scripts.check_live_credentials import main
from scripts.evaluate import _run


def test_live_preflight_fails_when_any_provider_key_is_missing(monkeypatch, capsys) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    assert main() == 2
    output = capsys.readouterr()
    assert "OPENAI_API_KEY" in output.err
    assert "TYPESAFE_API_KEY" in output.err
    assert "PASS" not in output.out


def test_live_evaluation_returns_failure_without_typesafe_key(monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    assert asyncio.run(_run(0.8)) == 2
