# Copyright (c) 2026 Eric Cooper.
"""Re-record the Claude answers that RAG at a glance shows in section 3.

The notebook runs without an API key, so instead of calling Claude it shows
answers saved in notebooks/data/rag_at_a_glance_answers.json from a real run.
Re-record them, with ANTHROPIC_API_KEY set, after changing the sample rules,
the prompt or the model (a few cents):

    uv run python scripts/record_glance_answers.py

Each saved question is asked again the way the notebook retrieves for it
(``domain`` alone, or ``domains`` together), and the file is rewritten.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from rulebook.config import settings
from rulebook.pipeline import ask

ANSWERS = Path(__file__).resolve().parents[1] / "notebooks" / "data" / "rag_at_a_glance_answers.json"


def main() -> None:
    doc = json.loads(ANSWERS.read_text())
    for entry in doc["answers"]:
        res = ask(entry["question"], domain=entry.get("domain"), domains=entry.get("domains"))
        if res.unverified_citations:
            raise SystemExit(f"{entry['question']!r} cites rules it wasn't given: {res.unverified_citations}")
        entry["answer"] = res.answer
        print(f"{entry['question']}\n{res.answer}\n")
    doc["model"] = settings.claude_model
    doc["recorded"] = date.today().isoformat()
    doc["from"] = "scripts/record_glance_answers.py"
    ANSWERS.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {ANSWERS}")


if __name__ == "__main__":
    main()
