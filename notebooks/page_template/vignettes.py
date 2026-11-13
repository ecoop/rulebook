# Copyright (c) 2026 Eric Cooper.
"""Draw the landing page's vignettes: sanguine crayon sketches of the sample games.

Each vignette is a small standalone SVG in img/. The "crayon" is an SVG filter:
lines are nudged a little off true (displacement) and then broken up by paper
tooth (a high-frequency noise mask), so plain vector paths read as conté on paper.

    uv run python notebooks/page_template/vignettes.py

rewrites img/*.svg. Everything is drawn here from scratch: no source images.
"""

from __future__ import annotations

import math
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
def piece(sk: Sketch, name: str, x: float, y: float, s: float) -> str:
    outline, detail = PIECES[name]
    clip = sk.uid("clip")
    detail_fill = "#fff" if name in ("king", "queen") else "none"
    inner = (
        f'<clipPath id="{clip}"><path d="{outline}"/></clipPath>'
        f'<ellipse cx="4" cy="1" rx="44" ry="5" fill="{sk.hatch("light", s)}" stroke="none" opacity="0.4"/>'
        f'<path d="{outline}" fill="#fff" stroke="none"/>'
        f'<rect x="6" y="-170" width="40" height="175" fill="{sk.hatch("light", s)}" clip-path="url(#{clip})" stroke="none"/>'
        f'<rect x="18" y="-170" width="30" height="175" fill="{sk.hatch("cross", s)}" clip-path="url(#{clip})" stroke="none"/>'
        f'<path d="{outline}" stroke-width="1.7"/>'
        + (f'<path d="{detail}" stroke-width="1.3" fill="{detail_fill}"/>' if detail else "")
    )
    return place(x, y, s, inner)


# --- checkers: an 8x8 board in perspective, checkers inside the dark squares ------
def board(sk: Sketch, x, y, s, checkers, front=125, back=72, depth=62, edge=6):
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
        f'<path d="{" ".join(dark)}" fill="{sk.hatch("fine", s)}" stroke="none"/>',
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
    return place(x, y, s, "".join(out))


GAME = [(1, 0, True), (3, 0, True), (5, 0, True), (0, 1, True), (2, 1, True), (6, 1, True),
        (3, 2, True), (4, 5, False), (1, 5, False), (5, 6, False), (7, 6, False), (2, 7, False),
        (4, 7, False), (6, 7, False), (3, 4, False)]


# --- cornhole: a 24" x 48" board seen mostly from the side, front end on the left -----
# The near long edge runs from A (front, on the ground) up to B (back, on its legs);
# W is the board's width going away from us, a little shorter at the back.
A, B, W = (-82.0, 0.0), (62.0, -52.0), (36.0, -48.0)


def _board_pt(X: float, Y: float) -> tuple[float, float]:
    """A point on the board's top, in inches: X across (0 near, 24 far), Y along (0 front, 48 back)."""
    t, u = Y / 48, X / 24
    shrink = 1 - 0.15 * t
    return (A[0] + t * (B[0] - A[0]) + u * W[0] * shrink,
            A[1] + t * (B[1] - A[1]) + u * W[1] * shrink)


def _loop(points) -> str:
    return "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in points) + " Z"


def _bag_outline(cx, cy, size, turn, to_screen, n=40):
    """A bean bag: a soft square (a superellipse), ``size`` inches across."""
    pts = []
    for t in range(n):
        a = 2 * math.pi * t / n
        c, s_ = math.cos(a), math.sin(a)
        r = size / 2
        bx = r * math.copysign(abs(c) ** 0.45, c)
        by = r * math.copysign(abs(s_) ** 0.45, s_)
        rx = bx * math.cos(turn) - by * math.sin(turn)
        ry = bx * math.sin(turn) + by * math.cos(turn)
        pts.append(to_screen(cx + rx, cy + ry))
    return _loop(pts)


def cornhole(sk: Sketch, x, y, s, bag_on_board=True, bag_on_ground=True):
    th = 10  # the frame's depth, as drawn
    corners = [_board_pt(0, 0), _board_pt(0, 48), _board_pt(24, 48), _board_pt(24, 0)]
    near_front, near_back, far_back, far_front = corners
    floor_front = (near_front[0], near_front[1] + th)
    floor_back = (near_back[0] - 3, near_back[1] + 52)
    hole = [_board_pt(12 + 3 * math.cos(2 * math.pi * t / 36), 39 + 3 * math.sin(2 * math.pi * t / 36))
            for t in range(36)]

    def pt(p):
        return f"{p[0]:.1f} {p[1]:.1f}"

    out = [
        # the floor under the board, and the far leg glimpsed through the gap
        f'<path d="M{floor_front[0] - 6} {floor_front[1] + 1} L{floor_back[0] + 26} {floor_back[1] - 8}" '
        f'stroke-width="1" opacity="0.4"/>',
        f'<path d="M{far_back[0] - 5:.1f} {far_back[1] + th:.1f} L{floor_back[0] + W[0] * 0.85:.1f} '
        f'{floor_back[1] + W[1] * 0.85:.1f}" stroke-width="1.2" opacity="0.5"/>',
        # the top, then the side frame and front frame under its edges
        f'<path d="M{pt(near_front)} L{pt(near_back)} L{pt(far_back)} L{pt(far_front)} Z" fill="#fff" stroke-width="1.8"/>',
        f'<path d="M{pt(near_front)} L{pt(near_back)} L{near_back[0]:.1f} {near_back[1] + th:.1f} '
        f'L{floor_front[0]:.1f} {floor_front[1]:.1f} Z" fill="{sk.hatch("light", s)}" stroke-width="1.6"/>',
        f'<path d="M{pt(near_front)} L{pt(far_front)} L{far_front[0]:.1f} {far_front[1] + th - 2:.1f} '
        f'L{floor_front[0]:.1f} {floor_front[1]:.1f} Z" fill="{sk.hatch("tight", s)}" stroke-width="1.5"/>',
        # the near back leg, folded down to the floor
        f'<path d="M{near_back[0] - 5:.1f} {near_back[1] + th:.1f} L{floor_back[0]:.1f} {floor_back[1]:.1f} '
        f'L{floor_back[0] + 7:.1f} {floor_back[1]:.1f} L{near_back[0] + 1:.1f} {near_back[1] + th:.1f}" '
        f'fill="{sk.hatch("light", s)}" stroke-width="1.5"/>',
        # the hole: 6 inches across, 9 inches from the back
        f'<path d="{_loop(hole)}" fill="{DEEP}" fill-opacity="0.85" stroke="{DEEP}" stroke-width="1.5"/>',
    ]
    if bag_on_board:  # a 6-inch bag, the same size as the hole
        out.append(f'<path d="{_bag_outline(11, 17, 6, 0.4, _board_pt)}" fill="{sk.hatch("fine", s)}" '
                   f'stroke="{DEEP}" stroke-width="1.6"/>')
        out.append(f'<path d="{_bag_outline(11, 17, 4.6, 0.4, _board_pt)}" stroke-width="0.9" '
                   f'stroke-dasharray="2 3" opacity="0.8"/>')
    if bag_on_ground:  # on the floor in front, nearer to us
        def ground(gx, gy):
            return (A[0] - 2 + gx * 4.0 + gy * 1.6, A[1] + 36 + gx * 0.6 - gy * 2.2)
        out.append(f'<path d="{_bag_outline(0, 0, 6, 0.2, ground)}" fill="{sk.hatch("fine", s)}" '
                   f'stroke="{DEEP}" stroke-width="1.6"/>')
        out.append(f'<path d="{_bag_outline(0, 0, 4.6, 0.2, ground)}" stroke-width="0.9" '
                   f'stroke-dasharray="2 3" opacity="0.8"/>')
    return place(x, y, s, "".join(out))


# --- the vignettes ---------------------------------------------------------------
FULL_HOUSE = [("K", "S"), ("K", "H"), ("K", "D"), ("7", "C"), ("7", "S")]


def glance() -> str:
    sk = Sketch(320, 200, "Sketch of the three sample games: playing cards, a checkerboard and a cornhole board")
    return sk.render(
        board(sk, 168, 112, 0.5, GAME[::2], front=125, back=72, depth=62)
        + cards(sk, 84, 196, 0.5, [("K", "S"), ("7", "H"), ("2", "C")], spread=20)
        + cornhole(sk, 250, 168, 0.62, bag_on_ground=False)
    )


def embeddings() -> str:
    sk = Sketch(320, 200, "Sketch of a checkerboard with checkers, and a small cornhole board")
    return sk.render(
        board(sk, 128, 172, 0.95, GAME, front=125, back=72, depth=86, edge=7)
        + cornhole(sk, 282, 150, 0.42, bag_on_ground=False)
    )


def evaluation() -> str:
    sk = Sketch(320, 200, "Sketch of a full house in poker beside a checkerboard")
    return sk.render(
        board(sk, 222, 160, 0.68, GAME[:9], front=125, back=72, depth=70)
        + cards(sk, 104, 206, 0.58, FULL_HOUSE, spread=26)
    )


def reranking() -> str:
    sk = Sketch(320, 200, "Sketch of chess pieces in front of a fanned poker hand")
    return sk.render(
        cards(sk, 96, 186, 0.5, FULL_HOUSE, spread=24)
        + piece(sk, "king", 205, 168, 0.72) + piece(sk, "queen", 166, 176, 0.68)
        + piece(sk, "bishop", 246, 178, 0.66) + piece(sk, "knight", 134, 190, 0.66)
        + piece(sk, "rook", 282, 188, 0.62) + piece(sk, "pawn", 210, 196, 0.56)
    )


def chunking() -> str:
    """The whole set, cut into four pieces with gaps between them, like chunks."""
    sk = Sketch(320, 200, "Sketch of cards, chess pieces, a checkerboard and a cornhole board, cut into four pieces")
    scene = (
        board(sk, 168, 92, 0.42, GAME[::3], front=125, back=72, depth=62)
        + cards(sk, 70, 186, 0.44, FULL_HOUSE, spread=24)
        + piece(sk, "king", 160, 176, 0.55) + piece(sk, "knight", 128, 186, 0.52)
        + piece(sk, "rook", 190, 184, 0.5)
        + cornhole(sk, 262, 168, 0.55, bag_on_ground=False)
    )
    sk.defs["scene"] = f'<g id="scene">{scene}</g>'
    pieces = []
    cuts = [(0, 0, 110, 200, -3, -2.0), (110, 0, 60, 200, 0, 1.2), (170, 0, 50, 200, 3, -1.0), (220, 0, 100, 200, 7, 1.5)]
    for cx, cy, cw, ch, dx, turn in cuts:
        clip = sk.uid("cut")
        pieces.append(
            f'<clipPath id="{clip}"><rect x="{cx}" y="{cy}" width="{cw}" height="{ch}"/></clipPath>'
            f'<g transform="translate({dx} 0) rotate({turn} {cx + cw / 2} 100)">'
            f'<use href="#scene" clip-path="url(#{clip})"/>'
            f'<rect x="{cx + 1}" y="{cy + 6}" width="{cw - 2}" height="{ch - 10}" rx="4" '
            f'stroke-width="1" stroke-dasharray="4 4" opacity="0.6"/></g>'
        )
    return sk.render("".join(pieces))


VIGNETTES = {"rag_at_a_glance": glance, "embeddings": embeddings, "evaluation": evaluation,
             "reranking": reranking, "chunking": chunking}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, draw in VIGNETTES.items():
        svg = draw()
        (OUT / f"{name}.svg").write_text(svg)
        print(f"img/{name}.svg  {len(svg) // 1024} KB")
