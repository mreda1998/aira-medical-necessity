"""Generate synthetic patient-chart PDFs for live end-to-end validation of the
Medical Necessity Checker pipeline against real LLM providers.

These are NOT real patient records — entirely fabricated clinical prose used
to exercise the great-saphenous-vein branch of the BCBS FL varicose veins
guideline (backend/tests/samples/guideline.pdf).

Usage:
    .venv/bin/pip install reportlab   # one-time
    .venv/bin/python backend/tests/samples/make_synthetic_charts.py

Produces, alongside this script:
    chart_meets.pdf         - clearly MEETS great-saphenous criteria
    chart_insufficient.pdf  - missing duplex findings + conservative-therapy
                              duration -> should yield INSUFFICIENT_EVIDENCE
"""

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

OUT_DIR = Path(__file__).parent

styles = getSampleStyleSheet()
title_style = ParagraphStyle("ChartTitle", parent=styles["Title"], fontSize=14)
heading_style = ParagraphStyle("SectionHeading", parent=styles["Heading2"], fontSize=11,
                                spaceBefore=10, spaceAfter=4)
body_style = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=14)


def build_pdf(path: Path, doc_title: str, sections: list[tuple[str, str]]) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=LETTER,
                             topMargin=0.75 * inch, bottomMargin=0.75 * inch,
                             leftMargin=0.85 * inch, rightMargin=0.85 * inch)
    flow = [Paragraph(doc_title, title_style), Spacer(1, 10)]
    for heading, body in sections:
        flow.append(Paragraph(heading, heading_style))
        flow.append(Paragraph(body, body_style))
    doc.build(flow)


MEETS_SECTIONS = [
    ("Patient Demographics",
     "Name: Jane R. Whitfield (synthetic). DOB: 1968-03-11 (age 58). Sex: Female. "
     "MRN: SYN-00042. Encounter date: 2026-06-02. Referring provider: Dr. A. Cascio, "
     "Vascular Surgery."),
    ("History",
     "58-year-old female presents with a several-year history of symptomatic right lower "
     "extremity varicose veins. She reports persistent aching, swelling, and burning of the "
     "right leg that worsens by end of day and significantly interferes with prolonged "
     "standing at her job as a retail manager. No history of deep venous thrombosis. No "
     "known bleeding disorder. No prior venous procedures on the right leg."),
    ("Physical Exam",
     "Right lower extremity: visible tortuous varicosities along the medial thigh and calf, "
     "largest cluster measuring approximately 5 mm in diameter. Skin changes consistent with "
     "CEAP class C4a (pigmentation and mild eczematous changes) over the medial malleolus. "
     "No active or healed ulceration. Mild pitting edema at the ankle. Distal pulses intact. "
     "Left lower extremity unremarkable."),
    ("Duplex Ultrasound Report",
     "Venous duplex ultrasound of the right lower extremity performed 2026-05-20. Great "
     "saphenous vein (GSV) demonstrates reflux with a reflux time of 4.2 seconds (abnormal, "
     "&gt;0.5 s), maximal GSV diameter 6.5 mm at the mid-thigh. Deep venous system patent "
     "and competent throughout, no evidence of deep venous thrombosis. No perforator or "
     "small saphenous vein reflux identified."),
    ("Prior Treatment",
     "Patient has worn 20-30 mmHg graduated compression stockings daily for the past 4 "
     "months as directed, in addition to leg elevation. Despite consistent adherence, her "
     "aching, swelling, and burning symptoms have not improved and continue to limit her "
     "ability to stand for extended periods at work."),
    ("Plan/Order",
     "Discussed treatment options including continued conservative management versus "
     "endovenous ablation. Given demonstrated GSV reflux, CEAP C4a disease, varicosities "
     "&gt;=3 mm, and failure of at least 3 months of compression therapy to relieve "
     "symptoms interfering with activities of daily living, the patient elects to proceed "
     "with intervention. Plan: endovenous radiofrequency ablation of the right great "
     "saphenous vein (CPT 36475). Risks, benefits, and alternatives discussed; patient "
     "consents."),
]

INSUFFICIENT_SECTIONS = [
    ("Patient Demographics",
     "Name: Jane R. Whitfield (synthetic). DOB: 1968-03-11 (age 58). Sex: Female. "
     "MRN: SYN-00043. Encounter date: 2026-06-02. Referring provider: Dr. A. Cascio, "
     "Vascular Surgery."),
    ("History",
     "58-year-old female presents with a several-year history of symptomatic right lower "
     "extremity varicose veins. She reports persistent aching, swelling, and burning of the "
     "right leg that worsens by end of day and significantly interferes with prolonged "
     "standing at her job as a retail manager. No history of deep venous thrombosis. No "
     "known bleeding disorder. No prior venous procedures on the right leg."),
    ("Physical Exam",
     "Right lower extremity: visible tortuous varicosities along the medial thigh and calf, "
     "largest cluster measuring approximately 5 mm in diameter. Skin changes consistent with "
     "CEAP class C4a (pigmentation and mild eczematous changes) over the medial malleolus. "
     "No active or healed ulceration. Mild pitting edema at the ankle. Distal pulses intact. "
     "Left lower extremity unremarkable."),
    ("Prior Treatment",
     "Compression stockings recommended for the right lower extremity."),
    ("Plan/Order",
     "Discussed treatment options including continued conservative management versus "
     "endovenous ablation. Plan: endovenous radiofrequency ablation of the right great "
     "saphenous vein (CPT 36475). Risks, benefits, and alternatives discussed; patient "
     "consents."),
]


def main() -> None:
    build_pdf(OUT_DIR / "chart_meets.pdf",
              "Synthetic Patient Chart - Meets Criteria (Great Saphenous Vein)",
              MEETS_SECTIONS)
    build_pdf(OUT_DIR / "chart_insufficient.pdf",
              "Synthetic Patient Chart - Insufficient Evidence (Great Saphenous Vein)",
              INSUFFICIENT_SECTIONS)
    print(f"Wrote {OUT_DIR / 'chart_meets.pdf'}")
    print(f"Wrote {OUT_DIR / 'chart_insufficient.pdf'}")


if __name__ == "__main__":
    main()
