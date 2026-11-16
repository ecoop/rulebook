# Copyright (c) 2026 Eric Cooper.
"""diagrams: the RAG flow diagrams are well-formed and the committed SVGs are current."""

from __future__ import annotations

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_dir = Path(__file__).parents[1] / "notebooks" / "page_template"
sys.path.insert(0, str(_dir))  # diagrams.py imports Sketch from its neighbour, vignettes.py
_spec = importlib.util.spec_from_file_location("diagrams", _dir / "diagrams.py")
diagrams = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diagrams)


@pytest.mark.parametrize("name", sorted(diagrams.DIAGRAMS))
def test_diagram_is_well_formed_svg(name):
    root = ET.fromstring(diagrams.DIAGRAMS[name]())
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.get("aria-label")


@pytest.mark.parametrize("name", sorted(diagrams.DIAGRAMS))
def test_committed_svg_matches_generator(name):
    # img/ is published as-is; rerun diagrams.py after changing a drawing.
    assert (diagrams.OUT / f"{name}.svg").read_text() == diagrams.DIAGRAMS[name]()
