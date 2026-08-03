"""Extract text from an image-only PDF using Claude vision.

Some source materials arrive as image-only PDFs: field diagrams,
scanned reference sheets, infographics. pypdf's text extraction returns
zero characters on these — every "label" and paragraph is rasterized or
outlined into shapes.

Rather than adding OCR (Tesseract has a system dependency and is weak on
schematics with slanted labels), we send the PDF to Claude's vision API
and ask it to produce a clean Markdown transcription. The output is
cached beside the source as ``<stem>.extracted.md`` so we don't re-pay
for vision on every rebuild. The cache is also inspectable / editable —
if the model gets something wrong you can fix the .md by hand.

USAGE

    uv run python scripts/vision_extract.py rules/goaltimate/some-diagram.pdf

    # Overwrite an existing cache:
    uv run python scripts/vision_extract.py --force rules/goaltimate/some-diagram.pdf

Then add the produced ``.extracted.md`` file to SOURCES in build_index.py
and re-run the index build.
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from anthropic import Anthropic
from llm_guardrails.counters import WindowedCapHook
from llm_guardrails.events import EventLogHook
from llm_guardrails.wrapper import guarded_call

from rulebook import app_state
from rulebook.config import settings

# Guardrails singletons — needed for the vision call below to record
# spend against the cost counter and fire the event-log hook.
app_state.initialize(settings)

# The prompt is deliberately short and prescriptive. Vision models will
# happily invent structure if you give them wiggle room — we want a
# faithful transcription, not a "helpful summary".
EXTRACTION_PROMPT = """This PDF page is a reference diagram for a sport rulebook. Extract its full information content as clean Markdown so it can be indexed for retrieval.

Include:
- Every prose paragraph, verbatim.
- Every dimension, measurement, and label shown in the diagram, described in natural language (e.g. "The field is 26 yards wide and 48 yards tall"). If a label appears only in the diagram (not the prose), still capture it in the Markdown.
- Any bulleted lists (supplies, items, steps) as Markdown bullet lists.
- Spatial relationships the diagram makes explicit (e.g. "The hoop is placed 14 yards from one short side of the perimeter").

Do NOT:
- Invent information not visible on the page.
- Add preamble, commentary, or "Here is the extracted content:" wrappers.
- Reformat measurements into different units unless both units already appear on the page.

Use H2 (`##`) headings for the natural sections of the page. Output only the Markdown."""


def extract(pdf_path: Path, *, force: bool = False) -> Path:
    out_path = pdf_path.with_suffix("").with_suffix(".extracted.md")
    if out_path.exists() and not force:
        print(f"[skip] {out_path.name} already exists (pass --force to overwrite)")
        return out_path

    pdf_bytes = pdf_path.read_bytes()
    b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")

    client = Anthropic(api_key=settings.anthropic_api_key)
    hooks = [
        WindowedCapHook(app_state.cost_counter),
        EventLogHook(enabled=settings.guardrails_enabled),
    ]
    resp, _usage = guarded_call(
        client,
        provider="anthropic",
        hooks=hooks,
        tags={"stage": "vision-extract"},
        model=settings.claude_model,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )
    text = "".join(
        block.text for block in resp.content if getattr(block, "type", None) == "text"
    ).strip()

    header = (
        f"<!-- Auto-extracted from {pdf_path.name} by scripts/vision_extract.py.\n"
        f"     Model: {settings.claude_model}. Edit freely — regeneration is off\n"
        f"     unless you delete this file or pass --force. -->\n\n"
    )
    out_path.write_text(header + text + "\n", encoding="utf-8")
    print(
        f"[done] wrote {out_path} "
        f"({len(text)} chars, "
        f"{resp.usage.input_tokens} in / {resp.usage.output_tokens} out tokens)"
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Path to an image-only PDF")
    parser.add_argument("--force", action="store_true", help="Overwrite existing cache")
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"error: {args.pdf} does not exist", file=sys.stderr)
        sys.exit(1)

    extract(args.pdf, force=args.force)


if __name__ == "__main__":
    main()
