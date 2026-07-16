from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from pypdf import PdfReader

from .models import SourceSpan


class DocumentQualityError(ValueError):
    """Raised before any LLM call when a PDF has no usable text layer."""


@dataclass(frozen=True)
class PageText:
    number: int
    text: str
    printed_page: str | None = None


@dataclass(frozen=True)
class ExtractedDocument:
    pages: tuple[PageText, ...]

    @property
    def text(self) -> str:
        # Preserve the legacy full-text shape so this provenance change does
        # not also change the prompts or invalidate guideline caches.
        return "\n".join(page.text for page in self.pages)

    @property
    def marked_text(self) -> str:
        """Text with trustworthy physical page markers for LLM provenance."""
        return "\n".join(
            f"[[PDF PAGE {page.number}]]\n{page.text}"
            for page in self.pages
        )


@dataclass(frozen=True)
class CompilerDocumentSelection:
    """The policy pages sent to the compiler while the full PDF stays available for citations."""

    document: ExtractedDocument
    strategy: str
    original_page_count: int

    @property
    def selected_page_count(self) -> int:
        return len(self.document.pages)


_PRINTED_PAGE = re.compile(r"\bPage\s+(\d+)(?:\s+of\s+\d+)?\b", re.IGNORECASE)
_NUMBERED_HEADING = re.compile(r"^\d+(?:\.\d+)*\.\s+\S")
_HEADER_NOISE = re.compile(
    r"^(?:page\s+\d+(?:\s+of\s+\d+)?|medical coverage policy:\s*\w+|"
    r"medical policy\s+\w+|synthetic patient\b|confidential\b)",
    re.IGNORECASE,
)
_TOC_CRITERIA_END = re.compile(
    r"(?im)^\s*(general\s+background|clinical\s+background|scientific\s+evidence|"
    r"rationale|references)\s*\.{2,}\s*(\d+)\s*$"
)
_LONG_POLICY_THRESHOLD = 40


def _printed_page(text: str) -> str | None:
    match = _PRINTED_PAGE.search(text[:1000])
    return match.group(1) if match else None


def extract_document(data: bytes) -> ExtractedDocument:
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(PageText(number=index, text=text, printed_page=_printed_page(text)))
    return ExtractedDocument(pages=tuple(pages))


def extract_text(data: bytes) -> str:
    """Backward-compatible full-text helper."""
    return extract_document(data).text


def select_compiler_document(
    document: ExtractedDocument,
    long_policy_threshold: int = _LONG_POLICY_THRESHOLD,
) -> CompilerDocumentSelection:
    """Select a criteria-focused prefix only when the policy TOC gives a safe boundary.

    Many payer policies put actionable coverage criteria first and hundreds of
    references/background pages afterward. We trim only when a table of
    contents explicitly identifies the first background/reference page. If no
    deterministic boundary is available, the full document is retained.
    Physical page numbers are preserved for citation resolution.
    """
    original_count = len(document.pages)
    if original_count <= long_policy_threshold:
        return CompilerDocumentSelection(document, "full_document", original_count)

    toc_text = "\n".join(page.text for page in document.pages[:3])
    candidates = [
        (int(match.group(2)), re.sub(r"\s+", "_", match.group(1).lower()))
        for match in _TOC_CRITERIA_END.finditer(toc_text)
        if 2 <= int(match.group(2)) <= original_count
    ]
    if not candidates:
        return CompilerDocumentSelection(document, "full_document_no_safe_boundary", original_count)

    cutoff, heading = min(candidates, key=lambda item: item[0])
    selected_pages = tuple(page for page in document.pages if page.number <= cutoff)
    if not selected_pages:
        return CompilerDocumentSelection(document, "full_document_no_safe_boundary", original_count)
    return CompilerDocumentSelection(
        ExtractedDocument(pages=selected_pages),
        f"toc_boundary_{heading}",
        original_count,
    )


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u00ad", "").replace("–", "-").replace("—", "-")
    value = re.sub(r"[\u2022\u25cf\u25a0\u007f]", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def _looks_like_heading(line: str) -> bool:
    value = line.strip()
    if not 3 <= len(value) <= 120 or _HEADER_NOISE.match(value):
        return False
    if _NUMBERED_HEADING.match(value):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z/&-]*", value)
    if 1 < len(words) <= 16 and value == value.upper():
        return True
    return value.lower().rstrip(":") in {
        "coverage policy",
        "medical necessity criteria",
        "patient selection criteria",
        "position statement",
        "clinical indications",
    }


def _best_line_index(page: PageText, quote: str) -> int:
    quote_norm = _normalize(quote)
    best = (0.0, 0)
    for index, line in enumerate(page.text.splitlines()):
        line_norm = _normalize(line)
        if not line_norm:
            continue
        quote_tokens = set(quote_norm.split())
        line_tokens = set(line_norm.split())
        coverage = len(quote_tokens & line_tokens) / max(1, min(len(quote_tokens), len(line_tokens)))
        similarity = SequenceMatcher(None, quote_norm, line_norm).ratio()
        score = max(coverage, similarity)
        if score > best[0]:
            best = (score, index)
    return best[1]


def _section_for(pages: tuple[PageText, ...], page_index: int, quote: str) -> str | None:
    page = pages[page_index]
    lines = page.text.splitlines()
    target = _best_line_index(page, quote)
    for line in reversed(lines[:target]):
        if _looks_like_heading(line):
            return line.strip()
    # A section can start near the end of the previous page and continue onto
    # the cited page. Look back only two pages to avoid stale document titles.
    for previous in reversed(pages[max(0, page_index - 2):page_index]):
        for line in reversed(previous.text.splitlines()):
            if _looks_like_heading(line):
                return line.strip()
    return None


def _fuzzy_score(page: PageText, quote: str) -> float:
    quote_norm = _normalize(quote)
    quote_tokens = set(quote_norm.split())
    page_tokens = set(_normalize(page.text).split())
    page_coverage = len(quote_tokens & page_tokens) / max(1, len(quote_tokens))
    # Avoid expensive sequence matching on pages that do not contain most of
    # the quote's vocabulary. This keeps unresolved citations cheap even for
    # hundred-page policies.
    if page_coverage < 0.6:
        return page_coverage / 2
    lines = [line for line in page.text.splitlines() if _normalize(line)]
    best = 0.0
    for start in range(len(lines)):
        for width in range(1, min(8, len(lines) - start) + 1):
            candidate = _normalize(" ".join(lines[start:start + width]))
            if not candidate:
                continue
            candidate_tokens = set(candidate.split())
            token_coverage = len(quote_tokens & candidate_tokens) / max(1, len(quote_tokens))
            if token_coverage < 0.6:
                continue
            similarity = SequenceMatcher(None, quote_norm, candidate).ratio()
            best = max(best, (similarity + token_coverage) / 2)
    return best


def _resolved(
    span: SourceSpan,
    pages: tuple[PageText, ...],
    page_index: int,
    method: str,
    confidence: float,
) -> SourceSpan:
    page = pages[page_index]
    reported_section = (span.section or "").strip()
    section = (
        reported_section
        if reported_section and _normalize(reported_section) in _normalize(page.text)
        else _section_for(pages, page_index, span.text)
    )
    return span.model_copy(update={
        "page": page.number,
        "printed_page": page.printed_page,
        "section": section,
        "match_method": method,
        "match_confidence": round(confidence, 3),
    })


def resolve_source_span(
    span: SourceSpan | None,
    pages: tuple[PageText, ...],
) -> SourceSpan | None:
    """Verify a model-supplied quote and attach its local PDF location.

    Exact normalized matches are preferred. A conservative fuzzy fallback is
    accepted only when it is strong and clearly better than the next page.
    The model's own page is never treated as verified evidence.
    """
    if span is None:
        return None
    quote = _normalize(span.text)
    if len(quote) < 4 or not pages:
        return span.model_copy(update={"match_method": "unverified", "match_confidence": 0.0})

    exact = [index for index, page in enumerate(pages) if quote in _normalize(page.text)]
    if len(exact) == 1:
        return _resolved(span, pages, exact[0], "exact", 1.0)
    if span.page is not None:
        reported_index = span.page - 1
        if reported_index in exact:
            # The model selected a page from explicit page markers and local
            # code verified that the verbatim quote occurs on that page.
            return _resolved(span, pages, reported_index, "page_verified", 0.95)

    scores = sorted(
        ((_fuzzy_score(page, span.text), index) for index, page in enumerate(pages)),
        reverse=True,
    )
    best_score, best_index = scores[0]
    runner_up = scores[1][0] if len(scores) > 1 else 0.0
    if best_score >= 0.82 and best_score - runner_up >= 0.04:
        return _resolved(span, pages, best_index, "fuzzy", best_score)

    if span.page is not None:
        return span.model_copy(update={
            "match_method": "model_reported",
            "match_confidence": span.match_confidence or 0.5,
        })
    return span.model_copy(update={"match_method": "unverified", "match_confidence": 0.0})
