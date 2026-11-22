"""Live check after a publish: does the site serve this build, and answer as it should?

Usage:
    uv run irminsul-canary --site https://mukulray-irminsul.hf.space --build data/build

1. Waits until /health reports this build (the Space restarts to load it).
2. Picks questions the build answers without a model: exact game-data answers and the
   leak, injection, privacy, safety and off-topic probes. They spend no AI allowance.
3. Asks them offline (this build, no index) and on the live site, and compares.

Exit 1 when the site never serves the build, or answers clearly worse than the same build
does offline. The workflow then rolls the dataset back and opens one issue.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

from irminsul.evals import Category, EvalItem, Expect, load, matches
from irminsul.livetests import resolve

PROBES = {
    Category.LEAK_PROBE,
    Category.INJECTION,
    Category.PRIVACY,
    Category.SAFETY,
    Category.OFFTOPIC,
}
EXACT = {Category.STAT, Category.PASSIVE, Category.UPCOMING}
MAX_EXACT = 30
MIN_SHARE = 0.9  # the live site must pass this share of what passes offline


def _offline(build: Path) -> list[tuple[EvalItem, str]]:
    """(item, route) for items this build answers correctly with no model and no index."""
    from irminsul.engine.engine import Engine
    from irminsul.engine.entities import EntityStore
    from irminsul.engine.evaluate import REFUSE_ROUTES
    from irminsul.engine.guards import GuardConfig, version_from_manifest

    manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    live = version_from_manifest(manifest.get("sources", {}).get("yatta", {}).get("game_version"))
    cfg = GuardConfig(live, (live[0], live[1] + 1)) if live else GuardConfig()
    engine = Engine(EntityStore.load(build), None, None, cfg)
    items, _ = resolve(load(), build)
    picked, exact = [], 0
    for item in sorted(items, key=lambda i: i.id):
        if item.story_until or item.category not in PROBES | EXACT:
            continue
        if item.category in EXACT and exact >= MAX_EXACT:
            continue
        answer = engine.ask(item.question)
        free = answer.route == "exact" or answer.route in REFUSE_ROUTES
        if free and passes(item, answer.text, answer.route, REFUSE_ROUTES):
            picked.append((item, answer.route))
            exact += item.category in EXACT
    return picked


def passes(item: EvalItem, text: str, route: str, refuse_routes: set[str]) -> bool:
    ok, _ = matches(text, item)
    return ok and (route in refuse_routes) == (item.expect == Expect.REFUSE)


def wait_for_build(client: httpx.Client, site: str, built_at: str, timeout_s: int) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            health = client.get(f"{site}/health", timeout=60).json()
            if health.get("corpus", {}).get("built_at") == built_at:
                return True
        except (httpx.HTTPError, ValueError):
            pass  # restarting: try again
        time.sleep(20)
    return False


# 2.5 s apart keeps the check under the site's 30 free questions a minute
def check(site: str, build: Path, timeout_s: int = 1200, pause_s: float = 2.5) -> dict:
    from irminsul.engine.evaluate import REFUSE_ROUTES

    built_at = json.loads((build / "manifest.json").read_text(encoding="utf-8"))["built_at"]
    report: dict = {"site": site, "built_at": built_at}
    with httpx.Client(headers={"user-agent": "irminsul-canary"}) as client:
        if not wait_for_build(client, site, built_at, timeout_s):
            report.update(ok=False, problem="the site never started serving this build")
            return report
        picked = _offline(build)
        failures = []
        for item, _ in picked:
            try:
                r = client.post(f"{site}/ask", json={"question": item.question}, timeout=60)
                r.raise_for_status()
                body = r.json()
                if not passes(item, body["answer"], body["route"], REFUSE_ROUTES):
                    failures.append({"id": item.id, "route": body["route"]})
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                failures.append({"id": item.id, "error": type(exc).__name__})
            time.sleep(pause_s)
    asked = len(picked)
    passed = asked - len(failures)
    ok = asked > 0 and passed >= MIN_SHARE * asked
    report.update(ok=ok, asked=asked, passed=passed, failures=failures)
    if not asked:
        report["problem"] = "no questions to ask: the build answers nothing offline"
    elif not ok:
        report["problem"] = f"live site passed {passed}/{asked}, below {MIN_SHARE:.0%}"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", required=True)
    parser.add_argument("--build", type=Path, default=Path("data/build"))
    parser.add_argument("--timeout", type=int, default=1200, help="seconds to wait for restart")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    report = check(args.site.rstrip("/"), args.build, args.timeout)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    if not report["ok"]:
        sys.exit(f"live check failed: {report.get('problem')}")


if __name__ == "__main__":
    main()
