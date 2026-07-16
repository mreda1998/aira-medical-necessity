from pathlib import Path
import pytest
from app.pdf_extract import extract_text

SAMPLES = Path(__file__).parent / "samples"


@pytest.mark.skipif(not (SAMPLES / "guideline.pdf").exists(), reason="sample PDF not present")
def test_extract_text_from_guideline():
    data = (SAMPLES / "guideline.pdf").read_bytes()
    text = extract_text(data)
    assert "medical necessity" in text.lower()
    assert len(text) > 1000
