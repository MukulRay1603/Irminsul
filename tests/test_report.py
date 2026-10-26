"""The public test-results file, its checker, the /results page and the trust UI's hygiene."""

import copy
import json

import pytest
from test_web import client

from irminsul.api.web import WEB_DIR
from irminsul.report import OUT, cost, eval_set, problems


@pytest.fixture
def results() -> dict:
    return json.loads(OUT.read_text(encoding="utf-8"))


def test_committed_results_are_valid_and_current(results):
    assert problems(results) == []
    a = results["answers"]
    assert a["leak_probes"]["passed"] <= a["leak_probes"]["total"]
    assert results["eval_set"]["items"] == a["scored"] + a["needs_llm"]


def test_checker_catches_stale_or_broken_files(results):
    stale = copy.deepcopy(results)
    stale["eval_set"]["items"] += 1
    assert "eval set changed since the results were generated" in problems(stale)
    priced = copy.deepcopy(results)
    priced["cost"]["paid_reference"]["per_ai_answer_usd"] = 1.0
    assert any("cost" in p for p in problems(priced))
    broken = copy.deepcopy(results)
    del broken["answers"]
    assert problems(broken) == ["answers: missing or wrong type"]
    off = copy.deepcopy(results)
    off["retrieval"] = {"hit_at_3": 1.4, "hit_at_8": 0.9, "mrr_at_3": 0.8, "mrr_at_8": 0.8}
    assert problems(off) == ["retrieval.hit_at_3: missing or out of range"]


def test_cost_math():
    c = cost(0.2)
    # 3.5K input at $0.15/M + 0.5K output at $0.60/M
    assert c["paid_reference"]["per_ai_answer_usd"] == pytest.approx(0.000825)
    assert c["paid_reference"]["per_1000_ai_answers_usd"] == pytest.approx(0.825)
    assert c["per_answer_blended_usd"] == pytest.approx(0.000165)
    assert c["per_ai_answer_usd"] == 0.0


def test_eval_set_counts_come_from_the_files():
    counts = eval_set()
    assert counts["items"] == sum(counts["by_category"].values())
    assert counts["by_category"]["leak_probe"] >= 1


def test_results_page_is_served_under_the_csp(tmp_path):
    c = client(tmp_path)
    page = c.get("/results")
    assert page.status_code == 200 and "/static/results.js" in page.text
    assert "unsafe-inline" not in page.headers["content-security-policy"]
    assert c.get("/static/results.json").json()["schema"] == 1
    assert c.get("/static/results.css").status_code == 200
    assert 'href="/results"' in c.get("/").text


def test_trust_and_results_code_has_no_inline_styles_or_handlers():
    for name in ("results.html", "index.html"):
        html = (WEB_DIR / name).read_text(encoding="utf-8")
        assert "<script>" not in html and " style=" not in html and "onclick=" not in html
    for name in ("trust.js", "results.js"):
        js = (WEB_DIR / "static" / name).read_text(encoding="utf-8")
        assert "style=" not in js and "onerror=" not in js and "onclick=" not in js
        assert "innerHTML" not in js  # built with DOM calls, so nothing from an answer is parsed
    index = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    order = [index.index(f"/static/{n}") for n in ("answers.js", "trust.js", "app.js")]
    assert order == sorted(order)
