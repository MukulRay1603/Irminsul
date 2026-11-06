"""Pull planner API: stateless sums for the wish tracker (engine/pulls.py).

The tracker keeps a player's history on their device. These endpoints receive only plain
numbers, keep nothing, and never touch the game or a player's account.
"""

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, Request

from irminsul.api.app import client_id
from irminsul.api.limits import Window
from irminsul.engine import pulls

PER_CLIENT_PER_HOUR = 600  # the page recalculates as a player types


def upcoming(today, count: int = 8) -> list[dict]:
    """The next version phases, with their estimated dates."""
    out = []
    index = pulls.ANCHOR_VERSION[0] * pulls.MINORS_PER_MAJOR + pulls.ANCHOR_VERSION[1]
    while len(out) < count:
        version = divmod(index, pulls.MINORS_PER_MAJOR)
        for phase in (1, 2):
            start = pulls.version_start(version, phase)
            if start > today and len(out) < count:
                label = f"{version[0]}.{version[1]} Phase {phase}"
                out.append({"label": label, "date": start.isoformat()})
        index += 1
    return out


def add_pulls(app: FastAPI, trusted_hops: int = 0) -> None:
    window = Window(limit=PER_CLIENT_PER_HOUR, seconds=3600)

    def check(request: Request) -> None:
        if not window.allow(client_id(request, trusted_hops)):
            raise HTTPException(429, "Too many requests. Try again later.")

    @app.get("/api/pulls/odds")
    def pull_odds(
        request: Request,
        wishes: int = Query(ge=0, le=pulls.MAX_WISHES),
        banner: str = Query("character", pattern="^(character|weapon)$"),
        pity: int = Query(0, ge=0, le=89),
        guaranteed: bool = False,
        copies: int = Query(1, ge=1, le=7),
    ) -> dict:
        check(request)
        o = pulls.odds(wishes, banner, pity, guaranteed, copies)
        return {"chance": round(o.chance, 4), "expected": round(o.expected, 1), "worst": o.worst}

    @app.get("/api/pulls/income")
    def pull_income(
        request: Request,
        until: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
        welkin: bool = False,
    ) -> dict:
        check(request)
        today = datetime.now(UTC).date()
        try:
            end = datetime.strptime(until, "%Y-%m-%d").date()
        except ValueError as e:
            raise HTTPException(422, "Bad date") from e
        if end > today + timedelta(days=pulls.CADENCE_DAYS * 12):
            raise HTTPException(422, "Too far ahead to estimate")
        est = pulls.income(today, end, welkin)
        return {
            "until": until,
            "days": est.days,
            "lines": [{"label": k, "primos": v} for k, v in est.lines if v],
            "primos": est.primos,
            "shop_fates": est.shop_fates,
            "wishes": est.wishes,
        }

    @app.get("/api/pulls/targets")
    def pull_targets() -> dict:
        return {"targets": upcoming(datetime.now(UTC).date())}
