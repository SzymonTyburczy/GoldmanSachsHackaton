from pathlib import Path

from fastapi.testclient import TestClient

STATIC_DIR = Path(__file__).resolve().parents[2] / "app" / "static"


def test_panel_is_served_with_a_restrictive_csp(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "<title>ControlProof</title>" in response.text
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_panel_assets_are_served(client: TestClient) -> None:
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


def test_panel_script_never_renders_server_values_as_html() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in script


def test_panel_does_not_persist_tokens_in_browser_storage() -> None:
    for asset in STATIC_DIR.iterdir():
        content = asset.read_text(encoding="utf-8")
        assert "localStorage" not in content
        assert "sessionStorage" not in content
