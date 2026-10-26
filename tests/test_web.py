"""Web app routes: the page under the strict CSP, released-only data, and the art proxy."""

from fastapi.testclient import TestClient
from PIL import Image
from test_engine import FakeIndex, FakeLLM, store

from irminsul.api.app import create_app
from irminsul.api.art import LocalArt
from irminsul.api.web import WEB_DIR, add_web
from irminsul.engine.engine import Engine


def client(tmp_path, library=None):
    engine = Engine(store(), FakeIndex(), FakeLLM())
    app = create_app(engine)
    add_web(app, engine.store, {}, LocalArt(library, tmp_path / "cache"))
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
    for name in ("app.js", "planner.js", "answers.js", "patches.js", "story.js"):
        js = (WEB_DIR / "static" / name).read_text(encoding="utf-8")
        assert ' style="' not in js and "onerror=" not in js and "onclick=" not in js
    assert "/static/planner.js" in page.text and c.get("/static/planner.css").status_code == 200
    assert "/static/patches.js" in page.text and c.get("/static/patches.css").status_code == 200
    assert "/static/story.js" in page.text and "data-story-slot" in page.text
    assert c.get("/static/story.css").status_code == 200


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


def test_manifest_makes_an_installable_app(tmp_path):
    c = client(tmp_path)
    r = c.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert m["name"] == "Irminsul" and m["display"] == "standalone" and m["start_url"] == "/"
    sizes = {(i["sizes"], i.get("purpose", "any")) for i in m["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
    for icon in m["icons"]:  # every icon it names is really there
        assert c.get(icon["src"]).headers["content-type"] == "image/png"
    page = c.get("/").text
    assert 'rel="manifest"' in page and "/static/pwa.js" in page
    assert 'property="og:image"' in page and 'rel="apple-touch-icon"' in page
    assert "viewport-fit=cover" in page


def test_service_worker_is_served_from_the_root_with_a_versioned_cache(tmp_path):
    c = client(tmp_path)
    r = c.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["service-worker-allowed"] == "/"
    assert r.headers["cache-control"] == "no-cache"
    assert "__VERSION__" not in r.text and "irminsul-" in r.text
    assert "You're offline. Answers need a connection." in r.text
    assert c.get("/favicon.ico").headers["content-type"] == "image/png"


def test_the_pwa_still_runs_under_the_strict_csp(tmp_path):
    c = client(tmp_path)
    for path in ("/", "/sw.js", "/manifest.webmanifest"):
        csp = c.get(path).headers["content-security-policy"]
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        # manifest-src and worker-src fall back to default-src 'self', which allows our own files
        assert "default-src 'self'" in csp and "script-src 'self'" in csp
    js = (WEB_DIR / "static" / "pwa.js").read_text(encoding="utf-8")
    assert ' style="' not in js and ".style" not in js and "onclick=" not in js


def test_og_image_becomes_absolute_when_the_public_url_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("IRMINSUL_PUBLIC_URL", "https://irminsul.example/")
    page = client(tmp_path).get("/").text
    assert 'content="https://irminsul.example/static/icons/og.png"' in page
