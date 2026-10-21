"""The writing team: two different models draft, the brain judges and merges.

With one model at a time this runs as phases: all brain drafts, then all second-model
drafts (one swap), then the brain judges (one swap back).  ``compose`` is the simple
per-item form; ``compose_many`` batches items so the swaps happen once per batch."""
from __future__ import annotations

import json
from typing import Any, Callable

from agency.agents.writer import Writer


class Team:
    def __init__(self, brain_writer: Writer, second_writer: Writer | None, judge, mode: str = "team", candidates: int = 2):
        self.brain_writer, self.second_writer, self.judge = brain_writer, second_writer, judge
        self.mode = mode if (second_writer is not None or mode != "team") else "best_of_n"
        self.candidates = max(1, candidates)

    def drafts(self, make: Callable[[Writer], dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self.mode == "single":
            return [make(self.brain_writer)]
        if self.mode == "best_of_n":
            for _ in range(self.candidates):
                out.append(make(self.brain_writer))
            return out
        out.append(make(self.brain_writer))
        if self.second_writer is not None:
            out.append(make(self.second_writer))
        return out

    def pick(self, kind: str, platform: str, brief: str, drafts: list[dict[str, Any]]) -> dict[str, Any]:
        if len(drafts) == 1:
            return drafts[0]
        system = self.brain_writer.system("You are now the editor-in-chief choosing between drafts from the team.")
        user = (
            f"Brief for this {kind} on {platform}: {brief}\n\nDrafts:\n" + "\n\n".join(f"DRAFT {i}:\n{json.dumps(d, ensure_ascii=False)[:3500]}" for i, d in enumerate(drafts)) +
            "\n\nChoose the strongest draft for hook, specificity, honesty and fit to the platform rules; you may merge the best lines of several drafts into one. "
            "Keep exactly the same JSON keys as the drafts. Never add facts that are not in the drafts.\n"
            'Return JSON: {"chosen": 0, "final": {...same keys...}, "why": "one sentence"}'
        )
        data = self.judge.complete_json(system, user, temperature=0.2)
        final = data.get("final") if isinstance(data, dict) else None
        if isinstance(final, dict) and final:
            final["_team"] = {"chosen": data.get("chosen"), "why": data.get("why", ""), "drafts": len(drafts)}
            return final
        try:
            return drafts[int(data.get("chosen", 0))]
        except (TypeError, ValueError, IndexError):
            return drafts[0]

    def compose(self, kind: str, platform: str, brief: str, make: Callable[[Writer], dict[str, Any]]) -> dict[str, Any]:
        return self.pick(kind, platform, brief, self.drafts(make))

    def compose_many(self, items: list[tuple[str, str, str, Callable[[Writer], dict[str, Any]]]]) -> list[dict[str, Any]]:
        """items: (kind, platform, brief, make). Batched so the model swaps happen once per phase."""
        if self.mode != "team" or self.second_writer is None:
            return [self.compose(k, p, b, m) for k, p, b, m in items]
        first = [m(self.brain_writer) for _, _, _, m in items]
        second = [m(self.second_writer) for _, _, _, m in items]
        return [self.pick(k, p, b, [a, c]) for (k, p, b, _), a, c in zip(items, first, second)]
