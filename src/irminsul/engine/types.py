"""Answer and citation records returned by the engine (also the API response shape)."""

from dataclasses import dataclass, field


@dataclass
class Citation:
    n: int
    title: str
    url: str
    tier: str
    doc_id: str | None = None
    version: str | None = None  # the game version this source was written for
    quote: str | None = None  # the source's line behind the claim, kept short


@dataclass
class Answer:
    text: str
    route: str  # exact | announced | refuse_leak | refuse_injection | refuse_offtopic | rag | ...
    citations: list[Citation] = field(default_factory=list)
    trace: dict = field(default_factory=dict)  # explainability: what happened and why
    follow_ups: list[dict] = field(default_factory=list)  # [{"question", "free"}], see followups
    card: dict | None = None  # structured view of an exact answer, see cards
