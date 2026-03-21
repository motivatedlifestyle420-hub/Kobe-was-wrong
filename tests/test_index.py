"""Tests for Index.html – structural and content validation."""
from html.parser import HTMLParser
from pathlib import Path

INDEX = Path(__file__).parent.parent / "Index.html"


# ---------------------------------------------------------------------------
# Minimal HTML-element collector
# ---------------------------------------------------------------------------

class _Collector(HTMLParser):
    """Collect tags, ids, and text nodes from an HTML document."""

    def __init__(self):
        super().__init__()
        self.tags: list[str] = []
        self.ids: set[str] = set()
        self.button_texts: list[str] = []
        self.title_text: str = ""
        self._in_title = False
        self._in_button = False
        self._current_button: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs_dict = dict(attrs)
        if "id" in attrs_dict:
            self.ids.add(attrs_dict["id"])
        if tag == "title":
            self._in_title = True
        if tag == "button":
            self._in_button = True
            self._current_button = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "button":
            self._in_button = False
            self.button_texts.append("".join(self._current_button).strip())

    def handle_data(self, data):
        if self._in_title:
            self.title_text += data
        if self._in_button:
            self._current_button.append(data)


def _parse() -> _Collector:
    collector = _Collector()
    collector.feed(INDEX.read_text(encoding="utf-8"))
    return collector


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_index_html_exists():
    """Index.html must be present in the repository root."""
    assert INDEX.exists(), "Index.html not found"


def test_page_title():
    """The <title> element must read 'Kobe Was Wrong'."""
    c = _parse()
    assert c.title_text == "Kobe Was Wrong"


def test_required_element_ids():
    """Key interactive elements must expose their expected IDs."""
    expected_ids = {"proveBtn", "renameBtn", "receiptBtn", "resetBtn", "log", "stamp", "confetti"}
    c = _parse()
    missing = expected_ids - c.ids
    assert not missing, f"Missing element IDs: {missing}"


def test_prove_button_present():
    """A 'Prove Kobe Wrong' button must exist."""
    c = _parse()
    assert any("Prove Kobe Wrong" in t for t in c.button_texts), (
        "'Prove Kobe Wrong' button not found"
    )


def test_all_four_buttons_present():
    """All four action buttons must be present."""
    c = _parse()
    labels = {"Prove Kobe Wrong", "Rename Kobe", "Generate “Wrong Receipt”", "Reset"}
    found = {label for label in labels if any(label in t for t in c.button_texts)}
    missing = labels - found
    assert not missing, f"Missing buttons: {missing}"


def test_page_has_script():
    """The page must include at least one <script> block."""
    c = _parse()
    assert "script" in c.tags, "No <script> tag found in Index.html"


def test_page_is_valid_html_document():
    """The page must declare a doctype and contain html/head/body tags."""
    source = INDEX.read_text(encoding="utf-8").lower()
    assert "<!doctype html>" in source
    c = _parse()
    assert "html" in c.tags
    assert "head" in c.tags
    assert "body" in c.tags


def test_receipt_board_section_present():
    """A Receipt Board heading must be present."""
    source = INDEX.read_text(encoding="utf-8")
    assert "Receipt Board" in source


def test_stamp_element_present():
    """The stamp overlay element (id='stamp') must exist."""
    c = _parse()
    assert "stamp" in c.ids


def test_charset_utf8():
    """Page must declare UTF-8 charset."""
    source = INDEX.read_text(encoding="utf-8").lower()
    assert 'charset="utf-8"' in source or "charset=utf-8" in source
