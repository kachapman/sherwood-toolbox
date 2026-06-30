"""
markup_bridge.py - Hyperlink + highlighting utilities for HTML markup.

Functions:
- add_image_links: Replace label text with HTML anchor links using link_map.
- highlight_terms: Highlight user-provided terms with CSS classes.

No hardcoded keywords - fully driven by user-provided input.
"""

import csv
import html
import io
import re


def sanitize_terms(terms: list[str]) -> list[str]:
    """
    Sanitize and validate input terms:
    - Trim whitespace
    - Remove empty/None strings
    - Deduplicate while preserving order
    """
    if not terms:
        return []

    seen: set[str] = set()
    sanitized: list[str] = []

    for term in terms:
        if term is None:
            continue
        t = term.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        sanitized.append(t)

    return sanitized


def split_term_input(raw: str) -> list[str]:
    """
    Split a comma-separated term string, honoring double-quoted phrases.

    '"Roof, fascia, and soffit damage", drip edge'
        -> ['Roof, fascia, and soffit damage', 'drip edge']

    Surrounding quotes are stripped from stored terms. Quoting only engages
    when '"' opens a field, so mid-field quotes ('6" drip edge') pass through
    untouched. An unterminated opening quote consumes the rest of the input as
    one term (csv semantics; '""' inside a quoted field collapses to '"').
    Only the first line of input is considered.
    """
    if not raw or not raw.strip():
        return []
    reader = csv.reader(io.StringIO(raw), skipinitialspace=True)
    parts = next(reader, [])
    return sanitize_terms(parts)


def escape_regex(text: str) -> str:
    """Escape regex special characters in plain text."""
    return re.escape(text)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping or adjacent ranges."""
    if not ranges:
        return []

    ranges = sorted(ranges)
    merged: list[tuple[int, int]] = [ranges[0]]
    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _collect_skip_ranges(text: str, css_class: str | None = None) -> list[tuple[int, int]]:
    """Collect ranges that should not be modified by regex replacement."""
    ranges: list[tuple[int, int]] = []

    # Exclude every HTML tag.
    for match in re.finditer(r"<[^>]*?>", text):
        ranges.append((match.start(), match.end()))

    # Keep existing links untouched to avoid nested or duplicate anchors.
    for match in re.finditer(r"<a\b[^>]*>.*?</a>", text, flags=re.IGNORECASE | re.DOTALL):
        ranges.append((match.start(), match.end()))

    # Keep existing highlight spans untouched when color class exists.
    if css_class:
        # Match span tags with target class and their full content.
        pattern = re.compile(
            rf'<span\b[^>]*class=["\']([^"\']*\\b{re.escape(css_class)}\\b[^"\']*)["\'][^>]*>.*?</span>',
            flags=re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(text):
            ranges.append((match.start(), match.end()))

    return _merge_ranges(ranges)


def _ranges_overlap(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    """Return True when [start, end) overlaps any range in `ranges`."""
    for r_start, r_end in ranges:
        if r_end <= start:
            continue
        if r_start >= end:
            break
        return True
    return False


def is_inside_html_tag(pos: int, text: str) -> bool:
    """
    Check if position pos in text is inside an HTML tag (between < and >).
    Used to avoid matching text that is already part of markup.

    Returns True if position is BETWEEN < and > characters.
    """
    for match in re.finditer(r'<[^>]*>', text):
        tag_start = match.start() + 1  # After the '<'
        tag_end = match.end() - 1       # Before the '>'
        if tag_start <= pos < tag_end:
            return True
    return False


def make_safe_pattern(term: str, case_sensitive: bool, whole_word: bool) -> re.Pattern:
    """
    Build a safe regex pattern from user input term.

    The function escapes regex metacharacters and optionally applies whole-word
    boundaries when the term starts/ends with word characters.
    """
    escaped = escape_regex(term)
    flags = 0 if case_sensitive else re.IGNORECASE

    if not term:
        return re.compile("$")

    if whole_word and term:
        prefix = r"(?<!\w)" if term[0].isalnum() or term[0] == "_" else ""
        suffix = r"(?!\w)" if term[-1].isalnum() or term[-1] == "_" else ""
        pattern = f"{prefix}{escaped}{suffix}"
    else:
        pattern = escaped

    try:
        return re.compile(pattern, flags)
    except re.error:
        # Fallback to a literal pattern if anything unexpected occurs.
        return re.compile(re.escape(term), flags)


def make_highlight_span(text: str, css_class: str, inline_style: str | None = None) -> str:
    """Create an HTML highlight span for the given text."""
    if inline_style:
        return f'<span class="{css_class}" style="{inline_style}">{text}</span>'
    return f'<span class="{css_class}">{text}</span>'


def add_image_links(
    text: str,
    link_map: dict[str, str] | None,
    image_map: dict[str, str] | None = None
) -> str:
    """
    Replace label text with HTML anchor links using link_map.

    Args:
        text: Input HTML string (or plain text).
        link_map: Dict mapping label text -> URL/href.
        image_map: Optional fallback map used only when link_map is None.

    Returns:
        Text with links inserted where label text is found.

    Behavior:
        - If link_map is empty/None, return text unchanged (skip hyperlink replacement).
        - Only replace when full label matches (not partial inside tags).
        - Avoids double-wrapping existing anchor tags.
    """
    if not text:
        return text

    resolved_map = link_map if link_map else image_map
    if not resolved_map or not isinstance(resolved_map, dict):
        return text

    result = text
    seen_labels: set[str] = set()

    for label, href in resolved_map.items():
        label = str(label).strip()
        href = str(href).strip()
        if not label or not href or label in seen_labels:
            continue

        seen_labels.add(label)
        skip_ranges = _collect_skip_ranges(result)
        pattern = make_safe_pattern(label, case_sensitive=False, whole_word=False)

        def replacer(match: re.Match[str]) -> str:
            start, end = match.start(), match.end()
            if _ranges_overlap(start, end, skip_ranges):
                return match.group(0)

            link_html = f'<a href="{html.escape(href, quote=True)}">{match.group(0)}</a>'
            return link_html

        new_result = pattern.sub(replacer, result)
        result = new_result

    return result


def highlight_terms(
    text: str,
    terms: list[str],
    css_class: str = "hl",
    case_sensitive: bool = False,
    whole_word: bool = True,
    overlap_strategy: str = "first",
    term_colors: list[str] | None = None,
) -> str:
    """
    Highlight user-provided terms with CSS class wrappers.

    User input is accepted case-insensitively and converted to uppercase
    for matching. Only UPPERCASE text in the document is highlighted.
    No annotations are added unless user provides terms.

    Args:
        text: Input HTML string (or plain text).
        terms: List of keywords/phrases to highlight (from user input).
               Converted to uppercase internally for case-insensitive matching.
        css_class: CSS class name for highlight wrapper (default: "hl").
        case_sensitive: Ignored - always case-insensitive (default: False).
        whole_word: Whether to match whole words only (default: True).
        overlap_strategy: How to handle overlapping matches - "first" or "skip".
    """
    # No annotations unless user provides terms
    if not text or not terms:
        return text

    if term_colors is None:
        term_colors = []

    sanitized_pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for idx, term in enumerate(terms):
        if term is None:
            continue
        # Convert user input to uppercase for case-insensitive matching
        term = term.strip().upper()
        if not term or term in seen:
            continue

        seen.add(term)
        color = ""
        if idx < len(term_colors) and term_colors[idx]:
            color = _normalize_highlight_color(term_colors[idx])
        sanitized_pairs.append((term, color))

    # No annotations unless user provides valid terms
    if not sanitized_pairs:
        return text

    if overlap_strategy not in {"first", "skip"}:
        overlap_strategy = "first"

    result = text
    # Start with ranges already marked in the source so we don't nest into tags.
    skip_ranges = _collect_skip_ranges(result, css_class)

    # Sort by length descending so longer terms are preferred on overlap.
    sorted_pairs = sorted(sanitized_pairs, key=lambda item: len(item[0]), reverse=True)

    for term, color in sorted_pairs:
        # Always use case-insensitive pattern for matching uppercase terms
        pattern = make_safe_pattern(term, case_sensitive=False, whole_word=whole_word)

        def replacer(match: re.Match[str]) -> str:
            start, end = match.start(), match.end()

            if _ranges_overlap(start, end, skip_ranges):
                return match.group(0)

            # Case-insensitive matching, mirroring the PDF highlight layer.
            matched_text = match.group(0)

            # For both supported strategies, first accepted match wins and later
            # overlapping matches are skipped.
            return make_highlight_span(
                matched_text,
                css_class,
                _build_highlight_style(color)
            )

        result = pattern.sub(replacer, result)

        # Refresh skip ranges so future terms do not overlap newly-created spans.
        skip_ranges = _collect_skip_ranges(result, css_class)

    return result


def _normalize_highlight_color(value: str) -> str:
    """Return sanitized CSS color value when supported."""
    color = (value or "").strip()
    if not color:
        return ""

    # Keep common UI-provided hex colors and fallback to safe non-empty values.
    if color.startswith("#"):
        if re.fullmatch(r"#[0-9a-fA-F]{3,8}", color):
            return color

    # Allow rgb/rgba/hsl/hsla as-is but only in trusted UI flow.
    if color.lower().startswith(("rgb(", "rgba(", "hsl(", "hsla(")):
        return color

    # Last-chance fallback: keep non-empty values for advanced callers.
    return color


def _build_highlight_style(color: str) -> str:
    if not color:
        return ""
    normalized = _normalize_highlight_color(color)
    if not normalized:
        return ""
    return f"background-color: {normalized};"
