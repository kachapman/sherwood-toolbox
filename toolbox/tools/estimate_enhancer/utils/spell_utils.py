import re
import fitz  # PyMuPDF
from spellchecker import SpellChecker
from .spell_vocab import _CONSTRUCTION_WORDS

_SPELL_CHECKER = None

# Regexes to skip known non-word patterns
_SKIP_NUMBER_RE = re.compile(r'^\d+(\.\d+)?$')
_SKIP_CODE_RE = re.compile(r'^[A-Z]\.?\d{3}(\.\d+)*(\(\d+\))?$')
_SKIP_UNIT_RE = re.compile(r'^(SQ|EA|SF|LF|CY|YD|MT|PC|LN)$', re.IGNORECASE)
_SKIP_SYMBOL_RE = re.compile(r'^[^a-zA-Z]+$')
# Pluralized acronyms like SQs, LFs, IDs
_SKIP_ACRONYM_PLURAL_RE = re.compile(r"^[A-Z]{2,}s$")

# Punctuation stripped from word edges, including curly quote variants
_EDGE_PUNCT = '.,;:!?()[]{}"\'’‘“”'


def _get_spell_checker():
    """Lazy-initialize the SpellChecker and seed it with construction vocabulary."""
    global _SPELL_CHECKER
    if _SPELL_CHECKER is None:
        spell = SpellChecker()
        # Lowercase and add the custom vocabulary
        custom = {w.lower() for w in _CONSTRUCTION_WORDS}
        spell.word_frequency.load_words(custom)
        _SPELL_CHECKER = spell
    return _SPELL_CHECKER


def _is_skippable_token(token: str) -> bool:
    """Return True if a sub-token should be ignored during compound-word checks."""
    t = token.strip()
    if not t:
        return True
    if len(t) <= 2:
        return True
    if t.isupper():
        return True
    if _SKIP_NUMBER_RE.match(t):
        return True
    if _SKIP_CODE_RE.match(t):
        return True
    if _SKIP_UNIT_RE.match(t):
        return True
    if _SKIP_SYMBOL_RE.match(t):
        return True
    if _SKIP_ACRONYM_PLURAL_RE.match(t):
        return True
    if any(ch.isdigit() for ch in t):
        return True
    if '@' in t or 'www.' in t.lower() or 'http' in t.lower():
        return True
    return False


def _should_skip_word(word: str) -> bool:
    """Return True if the raw token should not be spell-checked at all."""
    w = word.strip()
    if not w:
        return True

    # Strip surrounding punctuation for inspection
    stripped = w.strip(_EDGE_PUNCT).strip()
    if not stripped:
        return True

    # Too short to judge (initials, clipped fragments)
    if len(stripped) <= 2:
        return True

    # Skip filename-style tokens (IWS_Diagram_Esposito, img_12345, etc.)
    if '_' in stripped:
        return True

    # Skip abbreviations ending with period (e.g., cond., Approx.)
    if w.endswith('.') and len(stripped) <= 6:
        return True

    # Skip pure ALL CAPS tokens (acronyms) and pluralized acronyms (SQs)
    if stripped.isupper():
        return True
    if _SKIP_ACRONYM_PLURAL_RE.match(stripped):
        return True

    # Skip anything containing digits (Roof1, sample2, etc.)
    if any(ch.isdigit() for ch in stripped):
        return True

    # Skip symbols with no letters: &, #:, >, %, etc.
    if _SKIP_SYMBOL_RE.match(stripped):
        return True

    # Skip URLs and email-like fragments
    if 'http' in w.lower() or 'www.' in w.lower() or '@' in w:
        return True

    return False


def _subtokens(word: str):
    """Yield sub-tokens to check for a possibly-compound word.

    Splits on / and - so that 'Wall/roof' is checked as ['Wall', 'roof'].
    Returns an empty list if the word itself should be skipped.
    """
    if _should_skip_word(word):
        return []

    stripped = word.strip(_EDGE_PUNCT).strip()
    if not stripped:
        return []

    # Normalize curly apostrophes and drop possessive endings:
    # "manufacturer’s" is checked as "manufacturer".
    stripped = stripped.replace('’', "'")
    if stripped.lower().endswith("'s"):
        stripped = stripped[:-2]
        if _is_skippable_token(stripped):
            return []

    # If it contains a slash or hyphen, split and evaluate parts
    if '/' in stripped or '-' in stripped:
        parts = re.split(r'[/-]', stripped)
        result = []
        for part in parts:
            part = part.strip()
            if _is_skippable_token(part):
                continue
            result.append(part)
        return result

    # Simple word
    return [stripped]


def check_pdf_spelling(filepath: str, skip_first_page: bool = True,
                       footer_ratio: float = 0.10, page_limit: int = None) -> list:
    """Scan a PDF for spelling mistakes and return a list of error dicts.

    Args:
        filepath: Path to the PDF file.
        skip_first_page: If True, page 1 is not checked.
        footer_ratio: Fraction of page height from the bottom to treat as
                      footer (e.g. 0.10 = bottom 10%% excluded).
        page_limit: If given, only check pages up to this index (0-based).

    Returns:
        List of dicts: {
            'page': <1-based>,
            'line': <approx line number>,
            'description': str,
            'units': '',
            'type': 'Spelling'
        }
    """
    spell = _get_spell_checker()
    errors = []

    doc = fitz.open(filepath)
    try:
        for page_idx in range(len(doc)):
            if page_limit is not None and page_idx >= page_limit:
                break
            if skip_first_page and page_idx == 0:
                continue

            page = doc.load_page(page_idx)
            page_height = page.rect.height
            footer_y = page_height * (1.0 - footer_ratio)

            # Extract words with coordinates: (x0, y0, x1, y1, word, block, line, word)
            word_list = page.get_text("words")
            if not word_list:
                continue

            # Group words by line within block to get line numbers
            # We'll sort by y0, then approximate line number
            words_sorted = sorted(word_list, key=lambda w: (w[1], w[0]))

            seen = set()
            current_line_num = 0
            prev_y = None
            line_tolerance = 3.0  # points

            for w in words_sorted:
                x0, y0, x1, y1, word_text, block_no, line_no, word_no = w
                # Skip footer region
                if y1 > footer_y:
                    continue

                # Approximate global line number
                if prev_y is None or abs(y0 - prev_y) > line_tolerance:
                    current_line_num += 1
                    prev_y = y0

                raw = word_text.strip()
                if not raw:
                    continue

                # Deduplicate by raw word per page
                if raw in seen:
                    continue
                seen.add(raw)

                tokens = _subtokens(raw)
                if not tokens:
                    continue

                # Flag only obvious fast-typing slips: the token is unknown AND
                # a known word sits one edit away (transpose, missed key,
                # double-tap, adjacent key). Unknown words with no close
                # neighbor are treated as jargon or proper names, not typos.
                suggestion = None
                for t in tokens:
                    lowered = t.lower()
                    if lowered in spell:
                        continue
                    near = spell.known(spell.edit_distance_1(lowered))
                    if near:
                        suggestion = max(near, key=lambda c: spell.word_frequency[c])
                        break
                if suggestion:
                    errors.append({
                        'page': page_idx + 1,
                        'line': current_line_num,
                        'description': f"Spelling: '{raw}' (did you mean '{suggestion}'?)",
                        'units': '',
                        'type': 'Spelling'
                    })
    finally:
        doc.close()

    return errors
