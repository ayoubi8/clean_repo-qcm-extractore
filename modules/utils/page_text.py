"""Shared rules for Step 1 page text: what counts as text, a blank page, and a
safe AI rewrite of a page."""
from typing import Optional

# Written instead of a 0 KB file. Later steps rely on continuous page numbers,
# so a really blank page keeps its file.
BLANK_PAGE_MARKER = "[BLANK PAGE]"

# Share of pixels that differ from the page background.
# Below BLANK: nothing to read (at most a page number), no AI call is made.
# Below LIKELY_BLANK: blank only if the OCR models also return nothing.
BLANK_INK_RATIO = 0.0005
LIKELY_BLANK_INK_RATIO = 0.003
_INK_CONTRAST = 48

# An AI "fix" never legitimately removes this much of a page.
MIN_REWRITE_RATIO = 0.7


def has_text(text: Optional[str]) -> bool:
    return bool(text and text.strip())


def is_blank_marker(text: Optional[str]) -> bool:
    return (text or "").strip() == BLANK_PAGE_MARKER


def page_ink_ratio(image) -> float:
    """Share of pixels that stand out from the most common (background) shade."""
    histogram = image.convert("L").histogram()
    total = sum(histogram)
    if not total:
        return 0.0
    background = max(range(256), key=histogram.__getitem__)
    ink = sum(count for shade, count in enumerate(histogram)
              if abs(shade - background) > _INK_CONTRAST)
    return ink / total


def is_safe_rewrite(original: Optional[str], rewritten: Optional[str]) -> bool:
    """False when an AI rewrite is empty or lost a large part of the page."""
    if not has_text(rewritten):
        return False
    return len(rewritten.strip()) >= len((original or "").strip()) * MIN_REWRITE_RATIO
