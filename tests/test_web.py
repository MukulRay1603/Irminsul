"""Web app routes: the page under the strict CSP, released-only data, and the art proxy."""

from fastapi.testclient import TestClient
from PIL import Image
from test_engine import FakeIndex, FakeLLM, store

from irminsul.api.app import create_app
from irminsul.api.web import WEB_DIR, Art, add_web
from irminsul.engine.engine import Engine


def client(tmp_path, library=None):
    engine = Engine(store(), FakeIndex(), FakeLLM())
    app = create_app(engine)
    add_web(app, engine.store, {}, Art(library, tmp_path / "cache"))
    return TestClient(app)


def test_page_and_assets_are_served_under_the_strict_csp(tmp_path):
    c = client(tmp_path)
    page = c.get("/")
    assert page.status_code == 200 and "/static/app.js" in page.text
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    # The page must not need the inline code the CSP blocks
    assert (
        "<script>" not in page.text and " style=" not in page.text and "onclick=" not in page.text
    )
    assert c.get("/static/app.css").status_code == 200
    js = (WEB_DIR / "static" / "app.js").read_text(encoding="utf-8")
    assert ' style="' not in js and "onerror=" not in js


def test_gallery_lists_released_characters_only(tmp_path):
    names = {c["name"] for c in client(tmp_path).get("/api/characters").json()}
    assert "Raiden Shogun" in names and "Mitya" not in names  # Mitya is announced, not released


def test_entity_card_and_unknown_ids(tmp_path):
    c = client(tmp_path)
    raiden = c.get("/api/entity", params={"id": "character/raiden-shogun"}).json()
    assert raiden["kind"] == "character" and raiden["splash"] is None  # no art library here
    mitya = c.get("/api/entity", params={"id": "character/mitya"}).json()
    assert mitya["splash"] is None and mitya["banner"] is None
    assert c.get("/api/entity", params={"id": "character/nobody"}).status_code == 404


def test_art_is_resized_and_cannot_escape_the_library(tmp_path):
    lib = tmp_path / "lib"
    (lib / "Characters" / "Raiden Shogun").mkdir(parents=True)
    Image.new("RGBA", (512, 256), (120, 80, 200, 255)).save(
        lib / "Characters/Raiden Shogun/splash.png"
    )
    (tmp_path / "secret.png").write_bytes(b"not for you")
    c = client(tmp_path, library=lib)
    r = c.get("/art/Characters/Raiden%20Shogun/splash.png", params={"w": 256})
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert c.get("/art/../secret.png", params={"w": 256}).status_code == 404
    assert c.get("/art/Characters/Raiden%20Shogun/splash.png", params={"w": 999}).status_code == 404
    assert client(tmp_path).get("/art/Characters/x.png").status_code == 404  # no library: no art
    raiden = c.get("/api/entity", params={"id": "character/raiden-shogun"}).json()
    assert raiden["splash"] == "/art/Characters/Raiden%20Shogun/splash.png?w=900"
