# Copyright (c) 2026 Eric Cooper.
"""Draw the landing page's vignettes: sanguine crayon sketches of the sample games.

Each vignette is a small standalone SVG in img/. The "crayon" is an SVG filter:
lines are nudged a little off true (displacement) and then broken up by paper
tooth (a high-frequency noise mask), so plain vector paths read as conté on paper.

    uv run python notebooks/page_template/vignettes.py

rewrites img/*.svg. Everything is drawn here from scratch: no source images.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).parent / "img"
INK = "#9c4329"   # sanguine
DEEP = "#6e2a17"  # sanguine, pressed harder

# --- suits, centred on (0, 0), about 24 units tall -------------------------------
SUIT = {
    "S": "M0 -12 C -9 -3, -13 2, -9 7 C -6 10, -2 9, -1 6 L -3 13 L 3 13 L 1 6 C 2 9, 6 10, 9 7 C 13 2, 9 -3, 0 -12 Z",
    "H": "M0 11 C -6 5, -12 0, -12 -5 C -12 -10, -6 -12, 0 -6 C 6 -12, 12 -10, 12 -5 C 12 0, 6 5, 0 11 Z",
    "D": "M0 -12 L 9 0 L 0 12 L -9 0 Z",
    "C": ("M-1 3 L -3 12 L 3 12 L 1 3 Z M0 -11 a5.5 5.5 0 1 0 0.01 0 Z "
          "M-6.5 -1 a5.5 5.5 0 1 0 0.01 0 Z M6.5 -1 a5.5 5.5 0 1 0 0.01 0 Z"),
}

# --- chess pieces: origin at the base centre, up is negative y -------------------
_BASE_L = "C -26 -10, -30 -7, -30 0 Z"
PIECES = {
    "pawn": ("M -26 0 L 26 0 C 26 -6, 22 -9, 18 -10 C 14 -18, 10 -30, 9 -40 L 14 -42 L 14 -46 L 7 -48 "
             "C 14 -52, 16 -60, 14 -66 C 11 -74, 4 -78, 0 -78 C -4 -78, -11 -74, -14 -66 "
             "C -16 -60, -14 -52, -7 -48 L -14 -46 L -14 -42 L -9 -40 C -10 -30, -14 -18, -18 -10 "
             "C -22 -9, -26 -6, -26 0 Z", ""),
    "rook": ("M -30 0 L 30 0 C 30 -7, 26 -10, 22 -11 L 18 -16 L 18 -20 L 14 -22 L 16 -72 L 22 -76 "
             "L 22 -100 L 13 -100 L 13 -92 L 5 -92 L 5 -100 L -5 -100 L -5 -92 L -13 -92 L -13 -100 "
             "L -22 -100 L -22 -76 L -16 -72 L -14 -22 L -18 -20 L -18 -16 L -22 -11 " + _BASE_L,
             "M -16 -76 L 16 -76"),
    "bishop": ("M -28 0 L 28 0 C 28 -7, 24 -10, 20 -11 L 16 -16 L 16 -20 L 10 -22 C 11 -45, 9 -62, 8 -72 "
               "L 16 -74 L 16 -79 L 8 -82 C 18 -90, 20 -102, 12 -112 C 8 -116, 4 -119, 2 -120 "
               "C 6 -122, 6 -128, 0 -128 C -6 -128, -6 -122, -2 -120 C -4 -119, -8 -116, -12 -112 "
               "C -20 -102, -18 -90, -8 -82 L -16 -79 L -16 -74 L -8 -72 C -9 -62, -11 -45, -10 -22 "
               "L -16 -20 L -16 -16 L -20 -11 C -24 -10, -28 -7, -28 0 Z",
               "M 5 -110 L -6 -95"),
    "queen": ("M -32 0 L 32 0 C 32 -8, 28 -11, 23 -12 L 18 -18 L 18 -22 L 11 -24 C 12 -55, 10 -80, 9 -94 "
              "L 18 -97 L 18 -102 L 9 -105 C 16 -112, 20 -120, 22 -130 L 14 -121 L 10 -134 L 4 -123 "
              "L 0 -137 L -4 -123 L -10 -134 L -14 -121 L -22 -130 C -20 -120, -16 -112, -9 -105 "
              "L -18 -102 L -18 -97 L -9 -94 C -10 -80, -12 -55, -11 -24 L -18 -22 L -18 -18 "
              "L -23 -12 C -28 -11, -32 -8, -32 0 Z",
              "M 0 -137 m -4.5 -5 a 4.5 4.5 0 1 0 9 0 a 4.5 4.5 0 1 0 -9 0"),
    "king": ("M -32 0 L 32 0 C 32 -8, 28 -11, 23 -12 L 18 -18 L 18 -22 L 11 -24 C 12 -55, 10 -82, 9 -98 "
             "L 18 -101 L 18 -106 L 9 -109 C 18 -116, 21 -126, 17 -134 L -17 -134 C -21 -126, -18 -116, "
             "-9 -109 L -18 -106 L -18 -101 L -9 -98 C -10 -82, -12 -55, -11 -24 L -18 -22 L -18 -18 "
             "L -23 -12 C -28 -11, -32 -8, -32 0 Z",
             "M -3.5 -134 L -3.5 -144 L -11 -144 L -11 -151 L -3.5 -151 L -3.5 -160 L 3.5 -160 L 3.5 -151 "
             "L 11 -151 L 11 -144 L 3.5 -144 L 3.5 -134"),
    "knight": ("M -30 0 L 30 0 C 30 -7, 26 -10, 22 -11 L 18 -16 L 18 -20 L 21 -24 C 27 -50, 30 -80, 22 -100 "
               "C 16 -114, 5 -123, -5 -122 L -8 -132 L -13 -119 C -23 -113, -32 -99, -37 -87 "
               "C -40 -80, -35 -73, -28 -75 C -22 -77, -15 -80, -9 -78 C -17 -66, -23 -46, -20 -24 "
               "L -18 -20 L -18 -16 L -22 -11 " + _BASE_L,
               "M 14 -104 C 20 -92, 22 -80, 21 -66 M 6 -110 C 13 -98, 15 -86, 14 -74 "
               "M -15 -101 m -2.5 0 a 2.5 2.5 0 1 0 5 0 a 2.5 2.5 0 1 0 -5 0 M -33 -82 l 3 1"),
}


class Sketch:
    """One SVG: collects pattern definitions and unique ids while it's drawn."""

    def __init__(self, width: int, height: int, label: str):
        self.width, self.height, self.label = width, height, label
        self.defs: dict[str, str] = {}
        self._n = 0

    def uid(self, stem: str) -> str:
        self._n += 1
        return f"{stem}{self._n}"

    def hatch(self, kind: str, scale: float) -> str:
        """A hatching pattern whose spacing stays the same at any drawing scale."""
        spec = {  # spacing, angle, colour, line width, opacity
            "light": (7, 40, INK, 1.8, 0.75),
            "cross": (7, -35, INK, 1.6, 0.6),
            "tight": (4, 40, DEEP, 2.0, 1.0),
            "fine": (4, 40, INK, 1.5, 0.9),
        }[kind]
        gap, angle, colour, width, opacity = spec
        pid = f"h-{kind}-{round(scale * 100)}"
        if pid not in self.defs:
            self.defs[pid] = (
                f'<pattern id="{pid}" width="{gap}" height="{gap}" patternUnits="userSpaceOnUse" '
                f'patternTransform="rotate({angle}) scale({1 / scale:.4f})">'
                f'<line x1="0" y1="0" x2="0" y2="{gap}" stroke="{colour}" stroke-width="{width}" '
                f'opacity="{opacity}"/></pattern>'
            )
        return f"url(#{pid})"

    def render(self, body: str) -> str:
        return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" role="img" aria-label="{self.label}">
<style>.ink path, .ink rect, .ink ellipse, .ink polygon, .ink circle {{ vector-effect: non-scaling-stroke; }}</style>
<defs>
  <filter id="crayon" x="-5%" y="-5%" width="110%" height="110%">
    <feTurbulence type="fractalNoise" baseFrequency="0.05" numOctaves="2" seed="4" result="wob"/>
    <feDisplacementMap in="SourceGraphic" in2="wob" scale="2.2" xChannelSelector="R" yChannelSelector="G" result="moved"/>
    <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" seed="9" result="grain"/>
    <feColorMatrix in="grain" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -3 0 0 0 2.3" result="tooth"/>
    <feComposite in="moved" in2="tooth" operator="in"/>
  </filter>
  {"".join(self.defs.values())}
</defs>
<g class="ink" filter="url(#crayon)" fill="none" stroke="{INK}" stroke-linecap="round" stroke-linejoin="round">
{body}
</g>
</svg>
"""


def place(x: float, y: float, s: float, inner: str) -> str:
    return f'<g transform="translate({x} {y}) scale({s})">{inner}</g>'


# --- cards -----------------------------------------------------------------------
def fan(sk: Sketch, hand: list[tuple[str, str]], s: float, spread: float = 30) -> str:
    """A fan of cards, pivoting about (0, 0); the cards sit above it."""
    w, h, lift = 104, 150, 120
    x, y = -w / 2, -lift - h
    n = len(hand)
    tight = sk.hatch("tight", s)
    out = []
    for i, (rank, suit) in enumerate(hand):
        angle = -spread + 2 * spread * i / (n - 1) if n > 1 else 0
        top = i == n - 1
        parts = [
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#fff" stroke-width="1.7"/>',
            f'<text x="{x + 15}" y="{y + 27}" text-anchor="middle" font-family="Georgia, serif" '
            f'font-size="22" fill="{INK}" stroke="none">{rank}</text>',
            f'<path d="{SUIT[suit]}" transform="translate({x + 15} {y + 42}) scale(0.5)" '
            f'fill="{tight}" stroke-width="1.2"/>',
        ]
        if top:
            parts.append(f'<path d="{SUIT[suit]}" transform="translate(4 {y + h / 2 + 6}) scale(1.9)" '
                         f'fill="{tight}" stroke-width="1.3"/>')
        else:
            parts.append(f'<path d="M{x + w - 5} {y + 8} L{x + w - 5} {y + h - 8}" stroke="{INK}" '
                         f'stroke-width="3" opacity="0.18"/>')
        out.append(f'<g transform="rotate({angle:.1f})">{"".join(parts)}</g>')
    return "".join(out)


def cards(sk: Sketch, x, y, s, hand, spread=30):
    return place(x, y, s, fan(sk, hand, s, spread))


# --- chess -----------------------------------------------------------------------
def piece(sk: Sketch, name: str, x: float, y: float, s: float, hatch_scale: float | None = None) -> str:
    outline, detail = PIECES[name]
    hs = s if hatch_scale is None else hatch_scale
    clip = sk.uid("clip")
    detail_fill = "#fff" if name in ("king", "queen") else "none"
    inner = (
        f'<clipPath id="{clip}"><path d="{outline}"/></clipPath>'
        f'<ellipse cx="4" cy="1" rx="44" ry="5" fill="{sk.hatch("light", hs)}" stroke="none" opacity="0.4"/>'
        f'<path d="{outline}" fill="#fff" stroke="none"/>'
        f'<rect x="6" y="-170" width="40" height="175" fill="{sk.hatch("light", hs)}" clip-path="url(#{clip})" stroke="none"/>'
        f'<rect x="18" y="-170" width="30" height="175" fill="{sk.hatch("cross", hs)}" clip-path="url(#{clip})" stroke="none"/>'
        f'<path d="{outline}" stroke-width="1.7"/>'
        + (f'<path d="{detail}" stroke-width="1.3" fill="{detail_fill}"/>' if detail else "")
    )
    return place(x, y, s, inner)


# --- checkers: an 8x8 board in perspective, checkers inside the dark squares ------
def board(sk: Sketch, x, y, s, checkers, front=125, back=72, depth=62, edge=6, pieces=(), squares="fine"):
    """Front edge centred on (0, 0), ``front`` and ``back`` half-widths, ``depth`` tall."""
    k = 0.55  # rows get shallower toward the back

    def row_y(j):
        t = j / 8
        return -depth * (t * (1 + k)) / (1 + k * t)

    def x_at(i, yy):
        t = -yy / depth
        half = front + (back - front) * t
        return -half + 2 * half * i / 8

    dark = []
    for j in range(8):
        for i in range(8):
            if (i + j) % 2 == 0:
                y0, y1 = row_y(j), row_y(j + 1)
                dark.append(f"M{x_at(i, y0):.1f} {y0:.1f} L{x_at(i + 1, y0):.1f} {y0:.1f} "
                            f"L{x_at(i + 1, y1):.1f} {y1:.1f} L{x_at(i, y1):.1f} {y1:.1f} Z")
    out = [
        f'<path d="M{-front} 0 L{-front} {edge} L{front} {edge} L{front} 0" fill="{sk.hatch("light", s)}" stroke-width="1.3"/>',
        f'<path d="M{-front} 0 L{front} 0 L{back} {-depth} L{-back} {-depth} Z" fill="#fff" stroke-width="1.5"/>',
        f'<path d="{" ".join(dark)}" stroke="none" '
        + (f'fill="{INK}" fill-opacity="0.3"/>' if squares == "tone" else f'fill="{sk.hatch(squares, s)}"/>'),
    ]
    for i, j, filled in checkers:
        yc = (row_y(j) + row_y(j + 1)) / 2
        xc = (x_at(i, yc) + x_at(i + 1, yc)) / 2
        sq_w, sq_h = x_at(i + 1, yc) - x_at(i, yc), row_y(j) - row_y(j + 1)
        rx, ry, side = sq_w * 0.36, sq_h * 0.32, sq_h * 0.3
        fill = sk.hatch("tight", s) if filled else "#fff"
        out.append(f'<path d="M{xc - rx:.1f} {yc:.1f} L{xc - rx:.1f} {yc - side:.1f} '
                   f'A{rx:.1f} {ry:.1f} 0 0 1 {xc + rx:.1f} {yc - side:.1f} L{xc + rx:.1f} {yc:.1f} '
                   f'A{rx:.1f} {ry:.1f} 0 0 1 {xc - rx:.1f} {yc:.1f} Z" fill="#fff" stroke-width="1"/>')
        out.append(f'<ellipse cx="{xc:.1f}" cy="{yc - side:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
                   f'fill="{fill}" stroke-width="1"/>')
    # chess pieces, back rows first so nearer pieces overlap them
    for name, i, j in sorted(pieces, key=lambda p: -p[2]):
        yc = (row_y(j) + row_y(j + 1)) / 2
        xc = (x_at(i, yc) + x_at(i + 1, yc)) / 2
        ps = (x_at(i + 1, yc) - x_at(i, yc)) * 0.85 / 60  # a piece's base is about 60 wide
        out.append(piece(sk, name, round(xc, 1), round(yc + 2, 1), round(ps, 3), hatch_scale=s * ps))
    return place(x, y, s, "".join(out))


GAME = [(1, 0, True), (3, 0, True), (5, 0, True), (0, 1, True), (2, 1, True), (6, 1, True),
        (3, 2, True), (4, 5, False), (1, 5, False), (5, 6, False), (7, 6, False), (2, 7, False),
        (4, 7, False), (6, 7, False), (3, 4, False)]


# --- the vignettes ---------------------------------------------------------------
FULL_HOUSE = [("K", "S"), ("K", "H"), ("K", "D"), ("7", "C"), ("7", "S")]
CARD_W, CARD_H = 104, 150


def card(sk: Sketch, x, y, s, rank, suit) -> str:
    """One card face up, its top-left corner at (x, y), drawn at scale ``s``."""
    tight = sk.hatch("tight", s)
    inner = (
        f'<rect x="0" y="0" width="{CARD_W}" height="{CARD_H}" rx="10" fill="#fff" stroke-width="1.7"/>'
        f'<text x="15" y="27" text-anchor="middle" font-family="Georgia, serif" font-size="22" '
        f'fill="{INK}" stroke="none">{rank}</text>'
        f'<path d="{SUIT[suit]}" transform="translate(15 42) scale(0.5)" fill="{tight}" stroke-width="1.2"/>'
        f'<path d="{SUIT[suit]}" transform="translate({CARD_W / 2} {CARD_H / 2 + 4}) scale(1.7)" '
        f'fill="{tight}" stroke-width="1.3"/>'
        f'<text x="{CARD_W - 15}" y="{CARD_H - 12}" text-anchor="middle" font-family="Georgia, serif" '
        f'font-size="22" fill="{INK}" stroke="none" transform="rotate(180 {CARD_W - 15} {CARD_H - 19})">{rank}</text>'
    )
    return place(x, y, s, inner)


def glance() -> str:
    sk = Sketch(320, 170, "Sketch of a poker hand beside a checkerboard with checkers")
    return sk.render(
        board(sk, 212, 150, 0.68, GAME[::2], front=125, back=72, depth=70)
        + cards(sk, 86, 178, 0.5, [("K", "S"), ("7", "H"), ("2", "C")], spread=20)
    )


def embeddings() -> str:
    sk = Sketch(320, 170, "Sketch of a checkerboard with checkers")
    return sk.render(board(sk, 160, 158, 1.1, GAME, front=125, back=78, depth=92, edge=7))


def evaluation() -> str:
    sk = Sketch(320, 170, "Sketch of a full house in poker beside a checkerboard")
    return sk.render(
        board(sk, 222, 150, 0.68, GAME[:9], front=125, back=72, depth=70)
        + cards(sk, 100, 190, 0.56, FULL_HOUSE, spread=26)
    )


def reranking() -> str:
    """The poker hand up front; chess pieces small and faint behind it."""
    sk = Sketch(320, 170, "Sketch of a poker hand, with chess pieces small in the background")
    behind = (
        piece(sk, "knight", 238, 108, 0.36) + piece(sk, "queen", 259, 102, 0.36)
        + piece(sk, "king", 281, 99, 0.38) + piece(sk, "bishop", 302, 104, 0.34)
        + piece(sk, "pawn", 270, 116, 0.28)
    )
    return sk.render(
        f'<g opacity="0.55">{behind}</g>'
        + cards(sk, 128, 200, 0.6, FULL_HOUSE, spread=26)
    )


def _dashed(x, y, w, h, turn=0.0) -> str:
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="3" stroke-width="1" '
            f'stroke-dasharray="4 4" opacity="0.7" transform="rotate({turn} {x + w / 2:.1f} {y + h / 2:.1f})"/>')


def chunking() -> str:
    """Each rule set cut into chunks: the poker hand card by card, the chessboard into tiles."""
    sk = Sketch(320, 120, "Sketch of a poker hand and a chessboard, each cut into several pieces")

    # Poker: the hand laid out in two rows, each card its own piece.
    s, gap = 0.3, 9
    w, h = CARD_W * s, CARD_H * s
    poker = []
    rows = [(FULL_HOUSE[:3], 9), (FULL_HOUSE[3:], 9 + h + 12)]
    for r, (hand, y) in enumerate(rows):
        x0 = 14 + (0 if r == 0 else (w + gap) / 2)
        for i, (rank, suit) in enumerate(hand):
            x = x0 + i * (w + gap)
            turn = (-2.0, 1.5, -1.0, 2.0, -1.5)[r * 3 + i]
            poker.append(f'<g transform="rotate({turn} {x + w / 2:.1f} {y + h / 2:.1f})">'
                         + card(sk, x, y, s, rank, suit) + "</g>")
            poker.append(_dashed(x - 3, y - 3, w + 6, h + 6, turn))

    # Chess: the board with its pieces, cut into three strips pulled a little apart.
    # The pieces stand clear of the cuts, so each strip holds whole pieces.
    bx, by, bs = 236, 101, 0.62
    scene = board(sk, bx, by, bs, [], front=118, back=76, depth=80, edge=6, squares="tone",
                  pieces=[("rook", 0, 0), ("knight", 1, 2), ("king", 4, 0), ("queen", 3, 4),
                          ("bishop", 6, 1), ("pawn", 7, 3)])
    sk.defs["chess"] = f'<g id="chess">{scene}</g>'
    half = 118 * bs
    cuts = [bx - half - 5, bx - 24, bx + 24, bx + half + 5]
    top, bottom = 30, by + 6 * bs + 5
    tiles = []
    for k, dx in enumerate((-6, 0, 6)):
        x0, x1 = cuts[k], cuts[k + 1]
        clip = sk.uid("tile")
        tiles.append(
            f'<clipPath id="{clip}"><rect x="{x0:.1f}" y="{top}" width="{x1 - x0:.1f}" height="{bottom - top:.1f}"/></clipPath>'
            f'<g transform="translate({dx} 0)"><use href="#chess" clip-path="url(#{clip})"/>'
            + _dashed(x0 + 1, top, x1 - x0 - 2, bottom - top) + "</g>"
        )
    return sk.render("".join(poker) + "".join(tiles))


VIGNETTES = {"rag_at_a_glance": glance, "embeddings": embeddings, "evaluation": evaluation,
             "reranking": reranking, "chunking": chunking}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, draw in VIGNETTES.items():
        svg = draw()
        (OUT / f"{name}.svg").write_text(svg)
        print(f"img/{name}.svg  {len(svg) // 1024} KB")
