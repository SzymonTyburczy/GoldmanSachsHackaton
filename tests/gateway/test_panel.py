import re
from pathlib import Path

from fastapi.testclient import TestClient

STATIC_DIR = Path(__file__).resolve().parents[2] / "app" / "static"
TEXT_ASSETS = ("index.html", "app.js", "styles.css", "favicon.svg")


def test_panel_is_served_with_a_restrictive_csp(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "<title>Contral</title>" in response.text
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_panel_assets_are_served(client: TestClient) -> None:
    for asset in TEXT_ASSETS[1:]:
        assert client.get(f"/static/{asset}").status_code == 200
    for font in ("inter-latin-wght-normal.woff2", "syne-latin-700-normal.woff2"):
        assert client.get(f"/static/fonts/{font}").status_code == 200


def test_panel_loads_nothing_from_other_origins() -> None:
    for asset in TEXT_ASSETS:
        content = (STATIC_DIR / asset).read_text(encoding="utf-8")
        assert not re.search(r"""(src|href|url)\s*[=(]\s*["']?(https?:)?//""", content), asset


def test_panel_script_never_renders_server_values_as_html() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in script


def test_panel_does_not_persist_tokens_in_browser_storage() -> None:
    for asset in TEXT_ASSETS:
        content = (STATIC_DIR / asset).read_text(encoding="utf-8")
        assert "localStorage" not in content
        assert "sessionStorage" not in content
        assert "document.cookie" not in content


def test_typed_requests_and_demo_buttons_share_one_execute_call() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert script.count('"/v1/execute"') == 1
    # One definition, called by the typed form and by the demo buttons.
    assert script.count("async function submitRequest(") == 1
    assert script.count("submitRequest({") == 3  # the definition and two callers
