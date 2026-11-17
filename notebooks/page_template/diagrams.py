# Copyright (c) 2026 Eric Cooper.
"""Draw the RAG flow diagrams: blue crayon sketches of what each stage does.

The same conté as the landing page's vignettes (vignettes.py's Sketch: its crayon
filter and hatching), in blue: sanguine for the games, blue for the pipeline. The
blue is darker than the sanguine, and the words get a crayon of their own that
wobbles less and skips less, because the vignettes are looked at and these are read.

    uv run python notebooks/page_template/diagrams.py

rewrites img/flow_*.svg: an overview of the whole pipeline, then one diagram per
stage (ingestion, chunking, embeddings, retrieval, generation). Every word on a
diagram is the notebooks' own: chunk, vector, embedding space, passages.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from vignettes import Sketch

OUT = Path(__file__).parent / "img"
# Ultramarine: CIELAB L* 32 (the sanguine #9c4329 is 40, so darker, to be read),
# chroma ~50 like the sanguine's so it reads as blue crayon, not slate; hue kept
# short of violet so the blue and the red stay apart when they meet.
INK = "#264796"
DEEP = "#18316d"  # pressed harder: L* ~22
WEIGHT = 1.45     # every stroke a little heavier than the vignettes'
WORDS = (1.4, 2.8)  # the words' crayon (wobble, tooth): steadier and more solid than the lines'
FONT = 'font-family="Georgia, serif" font-style="italic"'


class Diagram(Sketch):
    """A Sketch in blue, with every stroke ``WEIGHT`` times heavier and crisper words."""

    def __init__(self, width: int, height: int, label: str):
        super().__init__(width, height, label, ink=INK, deep=DEEP, words=WORDS)

    def render(self, body: str) -> str:
        body = re.sub(r'stroke-width="([\d.]+)"',
                      lambda m: f'stroke-width="{float(m[1]) * WEIGHT:.2f}"', body)
        return super().render(body)


# --- marks -----------------------------------------------------------------------
def label(x, y, text, size=12, anchor="middle") -> str:
    """Words, all in one style: the same blue whether caption, arrow or heading."""
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" {FONT} font-size="{size}" '
            f'fill="{INK}" stroke="none">{text}</text>')


def arrow(x1, y1, x2, y2, bend=0.0, width=1.6) -> str:
    """A hand-drawn arrow: a gently bowed stroke and an open two-stroke head."""
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy) or 1
    cx, cy = mx - dy / n * bend, my + dx / n * bend
    hx, hy = x2 - cx, y2 - cy                      # the head points along the last of the curve
    hn = math.hypot(hx, hy) or 1
    ux, uy = hx / hn, hy / hn
    a = 8
    lx, ly = x2 - a * ux + a * 0.55 * uy, y2 - a * uy - a * 0.55 * ux
    rx, ry = x2 - a * ux - a * 0.55 * uy, y2 - a * uy + a * 0.55 * ux
    return (f'<path d="M{x1:.1f} {y1:.1f} Q {cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}" stroke-width="{width}"/>'
            f'<path d="M{lx:.1f} {ly:.1f} L{x2:.1f} {y2:.1f} L{rx:.1f} {ry:.1f}" stroke-width="{width}"/>')


def link(x1, y1, x2, y2, above, bend=-5, size=12) -> str:
    """An arrow with its verb written above it."""
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    return arrow(x1, y1, x2, y2, bend=bend) + label(mx, my - 10 + min(0, bend) / 2, above, size)


def writing(x, y, length, rows, gap=9, sw=1.1, seed=0) -> str:
    """Rows of handwriting as short wavy strokes, word by word."""
    d = []
    for r in range(rows):
        yy = y + r * gap
        ln = length if r < rows - 1 else length * 0.6
        xx = x
        while xx < x + ln - 3:
            w = min(5 + (int(xx) * 7 + (r + seed) * 13) % 10, x + ln - xx)
            d.append(f"M{xx:.1f} {yy:.1f} q {w / 4:.1f} -2 {w / 2:.1f} 0 t {w / 2:.1f} 0")
            xx += w + 3.5
    return f'<path d="{" ".join(d)}" stroke-width="{sw}" opacity="0.8"/>'


def page(x, y, w, h, turn=0.0, fold=False) -> str:
    """A sheet of writing; ``fold`` turns down its top-right corner."""
    rows = int((h - 18) // 9)
    if fold:
        f = 12
        body = (f'<path d="M{x} {y} L{x + w - f} {y} L{x + w} {y + f} L{x + w} {y + h} L{x} {y + h} Z" '
                f'fill="#fff" stroke-width="1.5"/>'
                f'<path d="M{x + w - f} {y} L{x + w - f} {y + f} L{x + w} {y + f}" stroke-width="1.2"/>')
    else:
        body = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="#fff" stroke-width="1.5"/>'
    body += writing(x + 8, y + 14, w - 16, rows, seed=int(x))
    return f'<g transform="rotate({turn} {x + w / 2} {y + h / 2})">{body}</g>'


def pdf_stack(x, y, w=58, h=74) -> str:
    back = "".join(
        f'<rect x="{x + 8 - 4 * i}" y="{y - 8 + 4 * i}" width="{w}" height="{h}" rx="2" fill="#fff" stroke-width="1.3"/>'
        for i in range(2))
    tag = (f'<rect x="{x + 6}" y="{y + h - 20}" width="26" height="13" fill="#fff" stroke-width="1.1"/>'
           + label(x + 19, y + h - 10, "PDF", 9))
    return back + page(x, y, w, h, fold=True) + tag


def slip(x, y, w=46, h=20, turn=0.0, seed=0) -> str:
    """A chunk: a slip of paper with two lines of writing."""
    return (f'<g transform="rotate({turn} {x + w / 2} {y + h / 2})">'
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="#fff" stroke-width="1.3"/>'
            + writing(x + 6, y + 8, w - 12, 2, gap=6, sw=1, seed=seed) + "</g>")


def vector(x, y) -> str:
    """A column of numbers between square brackets, trailing off: the embedding itself."""
    vals = ["0.12", "−0.48", "0.91", "0.07", "−0.33", "0.56"]
    step, w = 10, 40
    h = len(vals) * step + 16
    nums = "".join(
        f'<text x="{x + w - 7}" y="{y + 12 + i * step}" text-anchor="end" font-family="Georgia, serif" '
        f'font-size="9" fill="{DEEP}" stroke="none">{t}</text>' for i, t in enumerate(vals))
    more = "".join(f'<circle cx="{x + w / 2 + 3}" cy="{y + len(vals) * step + 6 + k * 3.5}" r="0.9" '
                   f'fill="{DEEP}" stroke="none"/>' for k in range(3))
    brackets = f'<path d="M{x + 4} {y} h-4 v{h} h4 M{x + w - 4} {y} h4 v{h} h-4" stroke-width="1.6"/>'
    return brackets + nums + more


DOTS = [(22, 18), (40, 30), (58, 14), (30, 52), (70, 46), (86, 26), (52, 62), (92, 58), (16, 38), (76, 66)]


def space(sk: Sketch, x, y, w=104, h=80, dots=DOTS, star=None, ring=None) -> str:
    """Embedding space: two axes and the chunks' points in it; ``star`` marks the
    question and ``ring`` (dx, dy, r) circles its nearest chunks."""
    out = [f'<path d="M{x} {y} L{x} {y + h} L{x + w} {y + h}" stroke-width="1.3" opacity="0.7"/>']
    if ring:
        rx, ry, r = ring
        out.append(f'<ellipse cx="{x + rx}" cy="{y + ry}" rx="{r}" ry="{r * 0.82:.1f}" stroke="{DEEP}" '
                   f'stroke-width="1.4" stroke-dasharray="4 3"/>')
    tight = sk.hatch("tight", 1)
    for dx, dy in dots:
        out.append(f'<circle cx="{x + dx}" cy="{y + dy}" r="3.4" fill="{tight}" stroke-width="1.1"/>')
    if star:
        sx, sy = x + star[0], y + star[1]
        pts = " ".join(f"{sx + r * math.cos(a):.1f},{sy + r * math.sin(a):.1f}"
                       for k in range(10)
                       for r, a in [(7 if k % 2 == 0 else 3, -math.pi / 2 + k * math.pi / 5)])
        out.append(f'<polygon points="{pts}" fill="{DEEP}" stroke="{DEEP}" stroke-width="1"/>')
    return "".join(out)


def bubble(x, y, w=50, h=34) -> str:
    """A question: a speech bubble holding a question mark."""
    return (f'<path d="M{x + 8} {y} H{x + w - 8} Q{x + w} {y} {x + w} {y + 8} V{y + h - 8} '
            f'Q{x + w} {y + h} {x + w - 8} {y + h} H{x + 18} L{x + 8} {y + h + 9} L{x + 10} {y + h} '
            f'H{x + 8} Q{x} {y + h} {x} {y + h - 8} V{y + 8} Q{x} {y} {x + 8} {y} Z" fill="#fff" stroke-width="1.5"/>'
            + label(x + w / 2, y + h / 2 + 7, "?", 20))


def model_box(sk: Sketch, x, y, w=62, h=46, text="Claude") -> str:
    return (f'<rect x="{x + 4}" y="{y + 4}" width="{w}" height="{h}" rx="9" fill="{sk.hatch("light", 1)}" '
            f'stroke="none" opacity="0.5"/>'
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="#fff" stroke-width="1.7"/>'
            + label(x + w / 2, y + h / 2 + 5, text, 14))


def answer(x, y, w=70, h=78) -> str:
    """A written answer, two of its lines ending in a bracketed citation."""
    body = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="#fff" stroke-width="1.5"/>'
    rows = []
    for r, (ln, cite) in enumerate([(54, None), (30, 18), (52, None), (22, 18), (40, None)]):
        yy = y + 15 + r * 12
        rows.append(writing(x + 8, yy, ln, 1, seed=r))
        if cite:
            bx = x + 8 + ln + 3
            rows.append(f'<path d="M{bx + 2} {yy - 5} h-2 v9 h2 M{bx + cite} {yy - 5} h2 v9 h-2" '
                        f'stroke="{DEEP}" stroke-width="1.5"/>'
                        f'<path d="M{bx + 4} {yy} h{cite - 6}" stroke="{DEEP}" stroke-width="1.4"/>')
    return f'<g transform="rotate(2 {x + w / 2} {y + h / 2})">{body}{"".join(rows)}</g>'


def shrunk(x, y, inner: str, s=0.62) -> str:
    return f'<g transform="translate({x} {y}) scale({s})">{inner}</g>'


# --- the diagrams ----------------------------------------------------------------
def overview() -> str:
    """The pipeline in two parts: prepare the rulebook once, then answer each question.
    Embedding space is the hinge: built by the first part, searched by the second."""
    sk = Diagram(800, 252, "Flow in two parts. Prepare, once per rulebook: rulebook PDFs through ingestion, "
                           "chunking and embeddings into embedding space. Answer, for each question: retrieval "
                           "searches that space, and generation writes a cited answer")
    bw, bh = 74, 32

    def box(x, y, name):
        return (f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="6" fill="#fff" stroke-width="1.6"/>'
                + label(x + bw / 2, y + 20, name, 12))

    def carry(x0, x1, y, what=None):
        """An arrow between stages, with what it carries written above it."""
        out = arrow(x0, y, x1, y, bend=-2, width=1.4)
        return out + (label((x0 + x1) / 2, y - 8, what, 10) if what else "")

    # prepare
    y1 = 46
    c1 = y1 + bh / 2
    xs = [100, 222, 344]
    sx, sy, sw, sh = 472, 24, 92, 66                  # embedding space
    out = [label(14, 18, "prepare", 11, "start"), label(62, 18, "once per rulebook", 11, "start"),
           shrunk(18, y1 - 8, pdf_stack(0, 0)), label(40, y1 + 66, "rulebook PDFs", 11),
           carry(66, xs[0] - 4, c1)]
    out += [box(x, y1, name) for x, name in zip(xs, ["ingestion", "chunking", "embeddings"], strict=True)]
    out += [carry(xs[0] + bw + 4, xs[1] - 4, c1, "text"), carry(xs[1] + bw + 4, xs[2] - 4, c1, "chunks"),
            carry(xs[2] + bw + 4, sx - 8, c1, "vectors"),
            space(sk, sx, sy, w=sw, h=sh, dots=[(dx * 0.9, dy * 0.8) for dx, dy in DOTS]),
            label(sx + sw + 8, sy + 30, "embedding", 11, "start"), label(sx + sw + 8, sy + 44, "space", 11, "start")]
    # the line between the two parts
    out.append('<path d="M14 128 H786" stroke-width="1" stroke-dasharray="2 5" opacity="0.6"/>')
    # answer: retrieval sits right under the space it searches
    y2 = 184
    c2 = y2 + bh / 2
    rx = sx + sw / 2 - bw / 2
    gx = rx + bw + 60
    out += [label(14, 154, "answer", 11, "start"), label(58, 154, "for each question", 11, "start"),
            bubble(rx - 92, y2 - 4, 42, 30), label(rx - 71, y2 + 52, "question", 11),
            carry(rx - 44, rx - 4, c2), box(rx, y2, "retrieval"),
            arrow(sx + sw / 2, sy + sh + 6, sx + sw / 2, y2 - 4, width=1.4),
            label(sx + sw / 2 - 6, 150, "nearest chunks", 10, "end"),
            carry(rx + bw + 4, gx - 4, c2, "passages"), box(gx, y2, "generation"),
            carry(gx + bw + 4, gx + bw + 28, c2),
            shrunk(gx + bw + 34, y2 - 18, answer(0, 0)), label(gx + bw + 56, y2 + 66, "a cited answer", 11)]
    return sk.render("".join(out))


def ingestion() -> str:
    sk = Diagram(360, 160, "Flow: rulebook PDFs, extracted to plain text")
    return sk.render(
        pdf_stack(52, 36)
        + link(132, 78, 216, 78, "extract")
        + page(234, 28, 70, 92, turn=2)
        + label(84, 142, "rulebook PDFs") + label(270, 142, "plain text, by page")
    )


def chunking() -> str:
    sk = Diagram(360, 160, "Flow: plain text, split into short chunks")
    cuts = "".join(f'<path d="M34 {y} h82" stroke="{DEEP}" stroke-width="1.3" stroke-dasharray="5 4"/>'
                   for y in (58.5, 85.5))       # between lines of writing, three to a chunk
    return sk.render(
        page(40, 22, 70, 104) + cuts
        + link(132, 74, 204, 74, "split")
        + slip(222, 26, 76, 26, turn=-4, seed=1) + slip(236, 62, 76, 26, turn=2, seed=2)
        + slip(224, 98, 76, 26, turn=-2, seed=3)
        + label(75, 148, "text") + label(266, 148, "chunks")
    )


def embeddings() -> str:
    sk = Diagram(360, 160, "Flow: an embedding model embeds a chunk as a vector, stored as a point in embedding space")
    return sk.render(
        slip(8, 60, 58, 26, seed=4)
        + link(74, 73, 150, 73, "embed")
        + vector(156, 34)
        + link(204, 73, 240, 73, "store", bend=-4)
        + space(sk, 248, 30, w=100)
        + label(37, 116, "a chunk") + label(176, 130, "a vector")
        + label(298, 130, "a point in") + label(298, 144, "embedding space")
    )


def retrieval() -> str:
    sk = Diagram(360, 172, "Flow: the question is embedded by the same model; the chunks nearest it come back as passages")
    sx, sy = 136, 38
    star = (60, 32)
    callout = (f'<path d="M{sx + star[0] + 34} {sy - 18} Q {sx + star[0] + 18} {sy - 12} '
               f'{sx + star[0] + 8} {sy + star[1] - 8}" stroke="{DEEP}" stroke-width="1"/>'
               + label(sx + star[0] + 38, sy - 16, "your question", 11, "start"))
    return sk.render(
        bubble(8, 56, 46, 32)
        + link(60, 76, 126, 74, "embed")
        + space(sk, sx, sy, star=star, ring=(star[0], star[1] - 6, 30)) + callout
        + link(246, 74, 282, 74, "top k", bend=-4)
        + slip(290, 40, 56, 20, turn=-3, seed=5) + slip(296, 66, 56, 20, turn=2, seed=6)
        + slip(290, 92, 56, 20, turn=-1, seed=7)
        + label(31, 142, "question") + label(188, 142, "its nearest chunks") + label(318, 142, "passages")
    )


def generation() -> str:
    sk = Diagram(360, 160, "Flow: the question and passages go to Claude as a prompt; Claude generates a cited answer")
    return sk.render(
        bubble(12, 18, 46, 30)
        + slip(10, 72, 52, 18, turn=-3, seed=8) + slip(14, 94, 52, 18, turn=2, seed=9)
        # the question and the passages join, and go in together: that's the prompt
        + '<path d="M64 42 Q 86 48 96 73" stroke-width="1.6"/><path d="M70 92 Q 88 88 96 73" stroke-width="1.6"/>'
        + link(96, 73, 140, 73, "prompt", bend=-2)
        + model_box(sk, 146, 50)
        + link(214, 74, 262, 74, "generate", bend=-4)
        + answer(268, 34)
        + label(40, 138, "question") + label(40, 151, "+ passages")
        + label(178, 138, "language model") + label(304, 138, "a cited answer")
    )


DIAGRAMS = {"flow_overview": overview, "flow_ingestion": ingestion, "flow_chunking": chunking,
            "flow_embeddings": embeddings, "flow_retrieval": retrieval, "flow_generation": generation}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, draw in DIAGRAMS.items():
        svg = draw()
        (OUT / f"{name}.svg").write_text(svg)
        print(f"img/{name}.svg  {len(svg) // 1024} KB")
