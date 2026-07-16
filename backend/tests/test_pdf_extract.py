from pathlib import Path
import pytest
from app.models import SourceSpan
from app.pdf_extract import (
    ExtractedDocument,
    PageText,
    extract_document,
    extract_text,
    resolve_source_span,
    select_compiler_document,
)

SAMPLES = Path(__file__).parent / "samples"


@pytest.mark.skipif(not (SAMPLES / "guideline.pdf").exists(), reason="sample PDF not present")
def test_extract_text_from_guideline():
    data = (SAMPLES / "guideline.pdf").read_bytes()
    text = extract_text(data)
    assert "medical necessity" in text.lower()
    assert len(text) > 1000


def test_extract_document_preserves_physical_pages():
    data = (SAMPLES / "chart_meets.pdf").read_bytes()
    document = extract_document(data)
    assert len(document.pages) >= 1
    assert document.pages[0].number == 1
    assert document.text == "\n".join(page.text for page in document.pages)
    assert document.marked_text.startswith("[[PDF PAGE 1]]")


def test_resolve_source_span_adds_page_printed_page_and_section():
    document = ExtractedDocument(pages=(
        PageText(number=1, printed_page="1", text="1. PATIENT DEMOGRAPHICS\nName: Jane Doe"),
        PageText(
            number=2,
            printed_page="2",
            text=(
                "6. BARIATRIC SURGERY CONSULT - APRIL 2, 2026\n"
                "Height 5 ft 5 in; weight 200 lb; measured BMI 33.3 kg/m2."
            ),
        ),
    ))
    resolved = resolve_source_span(SourceSpan(text="measured BMI 33.3 kg/m2"), document.pages)
    assert resolved.page == 2
    assert resolved.printed_page == "2"
    assert resolved.section == "6. BARIATRIC SURGERY CONSULT - APRIL 2, 2026"
    assert resolved.match_method == "exact"
    assert resolved.match_confidence == 1.0


def test_resolve_source_span_does_not_guess_duplicate_quote():
    pages = (
        PageText(number=1, text="Medical policy"),
        PageText(number=2, text="Medical policy"),
    )
    resolved = resolve_source_span(SourceSpan(text="Medical policy"), pages)
    assert resolved.page is None
    assert resolved.match_method == "unverified"


def test_resolve_source_span_verifies_reported_page_for_duplicate_quote():
    pages = (
        PageText(number=1, text="ADULT CRITERIA\nMedical evaluation required"),
        PageText(number=2, text="ADOLESCENT CRITERIA\nMedical evaluation required"),
    )
    resolved = resolve_source_span(
        SourceSpan(
            text="Medical evaluation required",
            page=2,
            section="ADOLESCENT CRITERIA",
        ),
        pages,
    )
    assert resolved.page == 2
    assert resolved.section == "ADOLESCENT CRITERIA"
    assert resolved.match_method == "page_verified"


def test_long_policy_uses_toc_background_boundary_for_compiler():
    pages = [
        PageText(
            number=1,
            text="Table of Contents\nCoverage Policy ........ 2\nGeneral Background ........ 5\nReferences ........ 42",
        ),
        *[PageText(number=n, text=f"Policy page {n}") for n in range(2, 51)],
    ]
    selection = select_compiler_document(
        ExtractedDocument(pages=tuple(pages)),
        long_policy_threshold=10,
    )
    assert selection.original_page_count == 50
    assert selection.selected_page_count == 5
    assert [page.number for page in selection.document.pages] == [1, 2, 3, 4, 5]
    assert selection.strategy == "toc_boundary_general_background"


def test_long_policy_without_safe_toc_boundary_is_not_truncated():
    document = ExtractedDocument(
        pages=tuple(PageText(number=n, text=f"Policy page {n}") for n in range(1, 21))
    )
    selection = select_compiler_document(document, long_policy_threshold=10)
    assert selection.document is document
    assert selection.selected_page_count == 20
    assert selection.strategy == "full_document_no_safe_boundary"
