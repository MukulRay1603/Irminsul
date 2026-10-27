"""Remote art: official images by safe key, released only, cached, never an open proxy."""

import io
import threading
import time

from fastapi.testclient import TestClient
from PIL import Image
from test_engine import FakeIndex, FakeLLM, store

from irminsul.api.app import create_app
from irminsul.api.art import ENKA_UI, YATTA_UI, LocalArt, RemoteArt
from irminsul.api.web import add_web
from irminsul.engine.engine import Engine
from irminsul.engine.entities import EntityStore
from irminsul.pipeline.build import art_names_if_released
from irminsul.sources.yatta import asset_name


def png(w=512, h=256) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), (90, 140, 220, 255)).save(buf, "PNG")
    return buf.getvalue()


class FakeUpstream:
    """Stands in for gi.yatta.moe and enka.network: no network in tests."""

    def __init__(self, files: dict[str, bytes] | None = None, delay_s: float = 0.0):
        self.files = files if files is not None else {}
        self.delay_s = delay_s
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, url: str) -> bytes | None:
        with self._lock:
            self.calls.append(url)
        time.sleep(self.delay_s)
        return self.files.get(url)


def make(tmp_path, upstream, entities: EntityStore | None = None):
    s = entities or store()
    art = RemoteArt(s, tmp_path / "art", fetch=upstream, min_interval_s=0)
    engine = Engine(s, FakeIndex(), FakeLLM())
    app = create_app(engine)
    add_web(app, s, {}, art)
    return TestClient(app), art


def everything() -> FakeUpstream:
    """Every official image the test store's records name, on Yatta."""
    names = [
        "UI_AvatarIcon_Shougun",
        "UI_AvatarIcon_Shougun_Card",
        "UI_Gacha_AvatarImg_Shougun",
        "namecard/UI_NameCardPic_Shougun_P",
        "UI_Buff_Element_Electric",
    ]
    s = store()
    raiden = s.by_id["character/raiden-shogun"].entity
    names += [t.icon for t in raiden.talents] + [c.icon for c in raiden.constellations]
    names += [m.entity.icon for m in s.by_id.values() if m.kind == "weapon"]
    names += [f"reliquary/{m.entity.icon}" for m in s.by_id.values() if m.kind == "artifact"]
    return FakeUpstream({f"{YATTA_UI}{n}.png": png() for n in names})


def test_records_carry_official_icon_names_not_images():
    s = store()
    raiden = s.by_id["character/raiden-shogun"].entity
    assert raiden.icon == "UI_AvatarIcon_Shougun" and raiden.namecard == "UI_NameCardIcon_Shougun"
    assert raiden.talents[1].icon == "Skill_S_Shougun_01"
    assert all(c.icon for c in raiden.constellations)
    assert all(m.entity.icon for m in s.by_id.values() if m.kind in ("weapon", "artifact"))
    for bad in ("../secret", "https://evil.example/x", "UI_Icon_Item_Temp", "a/b", "", None, 3):
        assert asset_name(bad) is None


def test_announced_records_lose_their_icon_names_in_the_build():
    raiden = store().by_id["character/raiden-shogun"].entity
    announced = raiden.model_copy(
        update={"release": raiden.release.model_copy(update={"status": "announced"})}
    )
    stripped = art_names_if_released(announced)
    assert stripped.icon is None and stripped.namecard is None
    assert not any(t.icon for t in stripped.talents + stripped.constellations)
    assert art_names_if_released(raiden) is raiden


def test_api_points_at_safe_art_keys(tmp_path):
    c, _ = make(tmp_path, everything())
    raiden = next(x for x in c.get("/api/characters").json() if x["name"] == "Raiden Shogun")
    assert raiden["card"] == "/art/c/raiden-shogun/card?w=256"
    assert raiden["element_icon"] == "/art/e/Electro?w=64"
    e = c.get("/api/entity", params={"id": "character/raiden-shogun"}).json()
    assert e["art"] == "/art/c/raiden-shogun/icon?w=256"
    assert e["splash"] == "/art/c/raiden-shogun/splash?w=900"
    assert e["banner"] == "/art/c/raiden-shogun/banner?w=420"
    assert e["talents"][0]["icon"] == "/art/c/raiden-shogun/talent-0?w=128"
    assert e["constellations"][0]["icon"] == "/art/c/raiden-shogun/cons-1?w=128"
    assert "namecard" not in e and "icon" not in e  # asset names stay server-side
    weapon = next(m.entity.id for m in store().by_id.values() if m.kind == "weapon")
    w = c.get("/api/entity", params={"id": weapon}).json()
    assert w["art"] == f"/art/w/{weapon.split('/')[1]}/icon?w=256"
    # Every URL the API hands out resolves to a real image
    urls = [e["art"], e["splash"], e["banner"], e["element_icon"], raiden["card"], w["art"]]
    urls += [t["icon"] for t in e["talents"]] + [x["icon"] for x in e["constellations"]]
    for url in urls:
        r = c.get(url)
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp", url
        assert r.headers["cache-control"] == "public, max-age=604800"


def test_images_are_resized_and_cached(tmp_path):
    upstream = everything()
    c, _ = make(tmp_path, upstream)
    r = c.get("/art/c/raiden-shogun/splash", params={"w": 256})
    assert r.status_code == 200
    assert Image.open(io.BytesIO(r.content)).size == (256, 128)
    assert c.get("/art/c/raiden-shogun/splash", params={"w": 900}).status_code == 200
    assert upstream.calls == [f"{YATTA_UI}UI_Gacha_AvatarImg_Shougun.png"]  # one fetch, two sizes
    small = c.get("/art/c/raiden-shogun/splash", params={"w": 900}).content
    assert Image.open(io.BytesIO(small)).width == 512  # never upscaled
    # A fresh server on the same cache folder doesn't ask upstream again
    upstream2 = FakeUpstream()
    c2, _ = make(tmp_path, upstream2)
    assert c2.get("/art/c/raiden-shogun/splash", params={"w": 256}).status_code == 200
    assert upstream2.calls == []


def test_falls_back_to_enka_and_failures_are_404_not_retried_at_once(tmp_path):
    upstream = FakeUpstream({f"{ENKA_UI}UI_AvatarIcon_Shougun_Card.png": png(256, 256)})
    c, _ = make(tmp_path, upstream)
    assert c.get("/art/c/raiden-shogun/card").status_code == 200
    assert upstream.calls == [
        f"{YATTA_UI}UI_AvatarIcon_Shougun_Card.png",
        f"{ENKA_UI}UI_AvatarIcon_Shougun_Card.png",
    ]
    upstream.calls.clear()
    assert c.get("/art/c/raiden-shogun/icon").status_code == 404  # neither host has it
    assert len(upstream.calls) == 2
    assert c.get("/art/c/raiden-shogun/icon").status_code == 404
    assert len(upstream.calls) == 2  # remembered for a while, not refetched per page view


def test_bad_upstream_answers_are_404(tmp_path):
    def broken(url):
        raise TimeoutError("upstream timed out")

    c, _ = make(tmp_path, broken)
    assert c.get("/art/c/raiden-shogun/splash").status_code == 404
    junk = FakeUpstream({f"{YATTA_UI}UI_AvatarIcon_Shougun.png": b"<html>not an image</html>"})
    c, _ = make(tmp_path, junk)
    assert c.get("/art/c/raiden-shogun/icon").status_code == 404
    assert not list((tmp_path / "art").rglob("*.png"))  # nothing bad is cached


def test_unreleased_characters_never_get_art(tmp_path):
    s = store()
    mitya = s.by_id["character/mitya"].entity
    # Even if an announced record somehow carried icon names, nothing would be fetched
    s.by_id["character/mitya"].entity = mitya.model_copy(update={"icon": "UI_AvatarIcon_Mitya"})
    upstream = FakeUpstream({f"{YATTA_UI}UI_AvatarIcon_Mitya.png": png()})
    c, _ = make(tmp_path, upstream, s)
    for kind in ("icon", "card", "splash", "banner", "talent-0", "cons-1"):
        assert c.get(f"/art/c/mitya/{kind}").status_code == 404
    e = c.get("/api/entity", params={"id": "character/mitya"}).json()
    assert e["splash"] is None and e["banner"] is None
    assert "Mitya" not in {x["name"] for x in c.get("/api/characters").json()}
    assert upstream.calls == []


def test_only_keys_from_our_records_are_fetched(tmp_path):
    upstream = everything()
    c, _ = make(tmp_path, upstream)
    for path in (
        "/art/https://evil.example/x.png",
        "/art/https%3A%2F%2Fevil.example%2Fx.png",
        "/art/c/raiden-shogun/../../../etc/passwd",
        "/art/c/raiden-shogun/UI_AvatarIcon_Furina",
        "/art/c/raiden-shogun/talent-99",
        "/art/c/raiden-shogun/cons-7",
        "/art/c/raiden-shogun/talent-x",
        "/art/c/nobody/icon",
        "/art/c/raiden-shogun",
        "/art/w/raiden-shogun/icon",  # a character is not a weapon
        "/art/e/Fire",
        "/art/e/../../x",
        "/art/Characters/Raiden%20Shogun/splash.png",
    ):
        assert c.get(path).status_code == 404, path
    assert c.get("/art/c/raiden-shogun/icon", params={"w": 999}).status_code == 404
    url = "https://evil.example/x.png"
    assert c.get("/art/c/raiden-shogun/icon", params={"url": url}).status_code == 200
    assert all(u.startswith((YATTA_UI, ENKA_UI)) for u in upstream.calls)
    assert upstream.calls == [f"{YATTA_UI}UI_AvatarIcon_Shougun.png"]


def test_concurrent_requests_for_one_image_fetch_it_once(tmp_path):
    upstream = everything()
    upstream.delay_s = 0.2
    _, art = make(tmp_path, upstream)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(art.file("c/raiden-shogun/splash", 256)))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8 and len(set(results)) == 1 and results[0].exists()
    assert len(upstream.calls) == 1


def test_upstream_requests_are_paced(tmp_path):
    upstream = everything()
    art = RemoteArt(store(), tmp_path / "art", fetch=upstream, min_interval_s=0.05)
    start = time.monotonic()
    for kind in ("icon", "card", "splash", "banner"):
        art.file(f"c/raiden-shogun/{kind}", 64)
    assert time.monotonic() - start >= 0.15  # 4 fetches, at least 3 gaps


def test_serve_picks_the_art_mode(tmp_path, monkeypatch):
    from irminsul.api.serve import make_art

    monkeypatch.setenv("IRMINSUL_CACHE", str(tmp_path))
    monkeypatch.delenv("IRMINSUL_ART", raising=False)
    monkeypatch.delenv("IRMINSUL_ART_REMOTE", raising=False)
    assert isinstance(make_art(store()), RemoteArt)  # on by default
    monkeypatch.setenv("IRMINSUL_ART_REMOTE", "off")
    art = make_art(store())
    assert isinstance(art, LocalArt) and art.library is None
    monkeypatch.setenv("IRMINSUL_ART", str(tmp_path))
    art = make_art(store())
    assert isinstance(art, LocalArt) and art.library == tmp_path


def test_warm_prepares_cards_and_splashes_before_anyone_asks(tmp_path):
    upstream = everything()
    _, art = make(tmp_path, upstream)
    ready = art.warm()
    assert ready >= 3  # Raiden's card and splash, and the Electro icon
    fetched = len(upstream.calls)
    # A visitor now gets them from the cache: nothing more goes upstream
    c, _ = make(tmp_path, upstream)
    for url in (
        "/art/c/raiden-shogun/card?w=256",
        "/art/c/raiden-shogun/splash?w=900",
        "/art/e/Electro?w=64",
    ):
        assert c.get(url).status_code == 200, url
    assert len(upstream.calls) == fetched
