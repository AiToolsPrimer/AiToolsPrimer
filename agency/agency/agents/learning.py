"""Learning: your corrections become style rules the writer reads; approved texts become
a training set; from a few hundred pairs the single model can be fine-tuned on your voice."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agency.agents.base import Agent


class Learning(Agent):
    role = "editor in charge of house style"
    desk = "analyst"
    temperature = 0.2

    def __init__(self, llm, store, brand, out_dir: Path):
        super().__init__(llm, store, brand)
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def style_rules(self, max_pairs: int = 60) -> list[str]:
        pairs = self.store.list_corrections(max_pairs)
        if len(pairs) < 3:
            return self.current_rules()
        with self.report(f"distilling style rules from {len(pairs)} corrections"):
            data = self.ask_json(
                "Here are drafts and the owner's corrected versions. Infer the house style rules the corrections reveal: wording to avoid, structures preferred, tone, length, how links and claims are handled. "
                "Only rules that at least two corrections support. Short imperative sentences.\n" + "\n\n".join(f"DRAFT: {p['original'][:600]}\nCORRECTED: {p['edited'][:600]}" for p in pairs) +
                '\n\nReturn JSON: {"rules": ["..."]}'
            )
        rules = [str(r).strip() for r in (data.get("rules", []) if isinstance(data, dict) else []) if str(r).strip()][:25]
        if rules:
            (self.out_dir / "style_rules.json").write_text(json.dumps({"rules": rules, "from_corrections": len(pairs)}, indent=2))
            self.store.add_note("style", "House style rules: " + " | ".join(rules))
        return rules

    def current_rules(self) -> list[str]:
        f = self.out_dir / "style_rules.json"
        if f.exists():
            try:
                return list(json.loads(f.read_text()).get("rules", []))
            except json.JSONDecodeError:
                return []
        return []

    def export_training_set(self) -> dict[str, Any]:
        """JSONL of (instruction → approved text) for mlx_lm.lora. Corrections count double: draft→edited."""
        rows = []
        for c in self.store.list_content(status="published", limit=5000):
            if c["kind"] in ("post", "article", "short", "reply", "comment") and c.get("body"):
                rows.append({"prompt": f"Write a {c['kind']} for {c['platform']} about: {c.get('topic') or c.get('title')}", "completion": c["body"]})
        for p in self.store.list_corrections(5000):
            rows.append({"prompt": f"Rewrite this {p['kind']} for {p['platform']} in the house style:\n{p['original']}", "completion": p["edited"]})
        path = self.out_dir / "train.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"messages": [{"role": "user", "content": r["prompt"]}, {"role": "assistant", "content": r["completion"]}]}, ensure_ascii=False) + "\n")
        ready = len(rows) >= 300
        return {"path": str(path), "examples": len(rows), "ready": ready, "needed": max(0, 300 - len(rows))}
