# Copyright (c) 2026 Eric Cooper.
"""vignettes: the landing-page sketches get the games' boards right."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_path = Path(__file__).parents[1] / "notebooks" / "page_template" / "vignettes.py"
_spec = importlib.util.spec_from_file_location("vignettes", _path)
vignettes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vignettes)


def test_checkers_sit_on_dark_squares():
    # board() shades a square dark when column + row is even (a dark square in each
    # player's left-hand corner); checkers is played on the dark squares only.
    off = [(i, j) for i, j, _ in vignettes.GAME if (i + j) % 2]
    assert off == [], f"checkers on light squares: {off}"


def test_no_two_checkers_share_a_square():
    squares = [(i, j) for i, j, _ in vignettes.GAME]
    assert len(squares) == len(set(squares))
