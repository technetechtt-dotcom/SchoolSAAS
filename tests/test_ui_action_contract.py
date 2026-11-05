"""Catch simple dead UI buttons before deploying the frontend.

This static contract supplements, but cannot replace, role-based browser testing.
"""
import re
from pathlib import Path

HTML=(Path(__file__).resolve().parents[1]/"app"/"index.html").read_text()

def test_literal_button_actions_have_handlers():
    actions=set(re.findall(
        r'btn\(\s*(?:"[^"]*"|\x27[^\x27]*\x27)\s*,\s*"([a-z][a-z0-9-]*)"',HTML))
    handlers=set(re.findall(r'case "([a-z][a-z0-9-]*)"',HTML))
    special=set(re.findall(r'if\(x==="([a-z][a-z0-9-]*)"\)',HTML))
    missing=sorted(actions-handlers-special)
    assert len(actions)>=40,"Unexpected loss of visible application actions"
    assert not missing,f"Dead button handlers: {missing}"

def test_navigation_has_render_and_fallback():
    assert 'async function render()' in HTML
    assert 'if(!can(key))' in HTML
    assert 'Unable to load page' in HTML
    assert 'role="dialog"' in HTML
