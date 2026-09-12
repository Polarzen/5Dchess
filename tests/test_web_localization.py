"""Visible-only Simplified Chinese regression checks for the Web UI."""
from __future__ import annotations

from html.parser import HTMLParser
import re

import pytest

from src.web.app import app


_JS_ASSETS = ("game.js", "p2p.js", "p2p_invite.js")
_USER_VISIBLE_ATTRIBUTES = {
    "alt",
    "aria-description",
    "aria-label",
    "aria-placeholder",
    "aria-valuetext",
    "placeholder",
    "title",
}
_ALLOWED_BRAND_PHRASES = ("5D Chess", ".5dpgn")
_ALLOWED_WORDS = {"AI", "T", "L"}
_FORBIDDEN_VISIBLE_TERMS = (
    "Action",
    "Submit Action",
    "CHECK",
    "Present",
    "Required",
    "Movable",
    "Inactive",
    "Replay",
    "Turn",
    "PLAYABLE",
    "HISTORICAL",
    "ACTIVE",
    "INACTIVE",
    "PRESENT",
    "REQ",
    "PLAY",
    "OFF",
    "Canonical turn",
    "Legacy time",
    "side",
    "PvP",
    "PvE",
    "Room",
    "You white",
    "Opponent connected",
    "Waiting for opponent",
    "Opponent offline",
    "Action Moves",
    "Checkmate",
    "Stalemate",
    "Draw",
    "Hotseat",
    "Online P2P",
    "Canonical Action AI",
    "BoardCoord",
)


class _VisibleHTMLParser(HTMLParser):
    """Collect text and player-facing attributes while skipping code blocks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        for name, value in attrs:
            if value and name.lower() in _USER_VISIBLE_ATTRIBUTES:
                self.parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data)


def _html_visible_strings(source: str) -> list[str]:
    parser = _VisibleHTMLParser()
    parser.feed(source)
    parser.close()
    return parser.parts


def _strip_js_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\r\n]*", "", source)


def _consume_js_literal(source: str, start: int) -> tuple[str, int] | None:
    quote = source[start]
    if quote not in "'\"`":
        return None

    index = start + 1
    if quote != "`":
        while index < len(source):
            if source[index] == "\\":
                index += 2
            elif source[index] == quote:
                return source[start:index + 1], index + 1
            else:
                index += 1
        return None

    while index < len(source):
        if source[index] == "\\":
            index += 2
        elif source.startswith("${", index):
            expression_end = _consume_js_expression(source, index + 2)
            if expression_end is None:
                return None
            index = expression_end
        elif source[index] == "`":
            return source[start:index + 1], index + 1
        else:
            index += 1
    return None


def _consume_js_expression(source: str, start: int) -> int | None:
    depth = 1
    index = start
    while index < len(source):
        if source[index] in "'\"`":
            nested = _consume_js_literal(source, index)
            if nested is None:
                return None
            _, index = nested
        elif source[index] == "{":
            depth += 1
            index += 1
        elif source[index] == "}":
            depth -= 1
            index += 1
            if depth == 0:
                return index
        else:
            index += 1
    return None


def _literal_body(literal: str) -> str:
    return literal[1:-1]


def _strip_template_expressions(value: str) -> str:
    # Dynamic values are checked by their own localized helper/sink; this
    # detector audits the literal player-facing text around those values.
    output: list[str] = []
    index = 0
    while index < len(value):
        if value.startswith("${", index):
            expression_end = _consume_js_expression(value, index + 2)
            if expression_end is None:
                break
            index = expression_end
        else:
            output.append(value[index])
            index += 1
    return "".join(output)


def _visible_fragment(value: str) -> list[str]:
    value = _strip_template_expressions(value)
    if "<" in value and ">" in value:
        return _html_visible_strings(value)
    return [value]


def _object_body(source: str, name: str) -> str:
    match = re.search(
        rf"\b{re.escape(name)}\b\s*=\s*(?:Object\.freeze\(\s*)?\{{",
        source,
    )
    if not match:
        return ""
    body_start = match.end()
    closing = re.search(r"\n\s*\}\s*\)?;", source[body_start:])
    return source[body_start:body_start + closing.start()] if closing else source[body_start:]


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"\bfunction\s+{re.escape(name)}\s*\(", source)
    if not match:
        return ""
    next_function = source.find("\nfunction ", match.end())
    return source[match.end():next_function if next_function >= 0 else len(source)]


def _extract_visible_js_literals(source: str) -> list[str]:
    """Extract literals at known UI sinks, excluding comments and code values."""
    source = _strip_js_comments(source)
    patterns = (
        r"(?:textContent|innerHTML)\s*=\s*",
        r"\bshowToast\(\s*",
        r"\bprompt\(\s*",
        r"\.title\s*=\s*",
        r"setAttribute\(\s*['\"](?:title|aria-label|aria-valuetext)['\"]\s*,\s*",
        r"\btext\s*:\s*",
        r"\bmakeBadge\(\s*",
    )
    literals: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, source, re.DOTALL):
            literal = _consume_js_literal(source, match.end())
            if literal is not None:
                literals.append(_literal_body(literal[0]))

    for name in ("ERROR_MESSAGES", "peerLabels"):
        body = _object_body(source, name)
        for match in re.finditer(r":\s*", body, re.DOTALL):
            literal = _consume_js_literal(body, match.end())
            if literal is not None:
                literals.append(_literal_body(literal[0]))

    for name in ("modeLabel", "resultLabel", "colorLabel"):
        body = _function_body(source, name)
        for match in re.finditer(r":\s*", body, re.DOTALL):
            literal = _consume_js_literal(body, match.end())
            if literal is not None:
                literals.append(_literal_body(literal[0]))
    return [fragment for literal in literals for fragment in _visible_fragment(literal)]


def _unapproved_english(value: str) -> list[str]:
    normalized = value
    for phrase in _ALLOWED_BRAND_PHRASES:
        normalized = normalized.replace(phrase, "")
    normalized = normalized.replace("5D", "")
    for word in _ALLOWED_WORDS:
        normalized = re.sub(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", "", normalized, flags=re.IGNORECASE)
    # T/L coordinates can be adjacent to their numeric coordinate without a
    # word boundary, for example L0 or t1.
    normalized = re.sub(r"(?<![A-Za-z])[tTlL](?=\d)", "", normalized)
    return re.findall(r"[A-Za-z]+", normalized)


def _assert_visible_chinese(values: list[str]) -> None:
    issues: list[str] = []
    for value in values:
        for term in _FORBIDDEN_VISIBLE_TERMS:
            if re.search(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", value, re.IGNORECASE):
                issues.append(f"forbidden {term!r} in {value!r}")
        words = _unapproved_english(value)
        if words:
            issues.append(f"unapproved English {words!r} in {value!r}")
    assert not issues, "\n".join(issues)


@pytest.fixture()
def client():
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_visible_html_and_dom_sinks_are_simplified_chinese(client):
    page = client.get("/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    visible_html = _html_visible_strings(html)
    assert "同屏双人对弈" in html
    assert "在线双人对弈" in html
    assert "人机对弈" in html
    assert "棋谱回放" in html
    _assert_visible_chinese(visible_html)

    for asset in _JS_ASSETS:
        script = client.get(f"/static/js/{asset}")
        assert script.status_code == 200
        source = script.get_data(as_text=True)
        _assert_visible_chinese(_extract_visible_js_literals(source))


def test_detector_ignores_comments_and_protocol_values_but_rejects_bad_label():
    source = """
    // node.textContent = 'Submit Action';
    const protocol = 'room_not_found';
    node.textContent = '提交行动';
    """
    literals = _extract_visible_js_literals(source)
    assert literals == ["提交行动"]
    _assert_visible_chinese(literals)

    bad_source = "node.textContent = 'Submit Action';"
    with pytest.raises(AssertionError, match="Submit Action"):
        _assert_visible_chinese(_extract_visible_js_literals(bad_source))
