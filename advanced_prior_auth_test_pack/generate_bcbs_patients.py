"""Generate synthetic Florida Blue patient charts for regression testing.

The records are deliberately fictional and encode explicit evidence for the
expected Boolean outcome in ``expected_results_bcbs.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


OUTPUT_DIR = Path(__file__).resolve().parent / "charts" / "patients_bcbs"

NAVY = colors.HexColor("#15324B")
BLUE = colors.HexColor("#2E6F95")
PALE_BLUE = colors.HexColor("#EAF3F8")
PALE_GRAY = colors.HexColor("#F4F6F7")
MID_GRAY = colors.HexColor("#66747E")
LINE = colors.HexColor("#D6DEE3")
RED = colors.HexColor("#A33A32")


@dataclass(frozen=True)
class Section:
    title: str
    paragraphs: tuple[str, ...] = ()
    table_headers: tuple[str, ...] = ()
    table_rows: tuple[tuple[str, ...], ...] = ()
    table_widths: tuple[float, ...] = ()


styles = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "ChartTitle",
    parent=styles["Title"],
    fontName="Helvetica-Bold",
    fontSize=18,
    leading=22,
    textColor=NAVY,
    spaceAfter=4,
)
SUBTITLE = ParagraphStyle(
    "ChartSubtitle",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=9.5,
    leading=13,
    textColor=MID_GRAY,
    spaceAfter=10,
)
BADGE = ParagraphStyle(
    "SyntheticBadge",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=9,
    leading=12,
    textColor=RED,
    alignment=TA_CENTER,
)
SECTION_TITLE = ParagraphStyle(
    "SectionTitle",
    parent=styles["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=10.5,
    leading=13,
    textColor=NAVY,
    spaceBefore=9,
    spaceAfter=5,
)
BODY = ParagraphStyle(
    "ChartBody",
    parent=styles["BodyText"],
    fontName="Helvetica",
    fontSize=9.2,
    leading=13,
    textColor=colors.HexColor("#1D2A31"),
    spaceAfter=5,
)
SMALL = ParagraphStyle(
    "TableText",
    parent=BODY,
    fontSize=8.5,
    leading=11,
    spaceAfter=0,
)
SMALL_BOLD = ParagraphStyle(
    "TableTextBold",
    parent=SMALL,
    fontName="Helvetica-Bold",
    textColor=NAVY,
)


def _paragraph(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def _header_footer(clinic: str):
    def draw(canvas, doc) -> None:
        canvas.saveState()
        width, height = LETTER
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(0.62 * inch, height - 0.46 * inch, width - 0.62 * inch, height - 0.46 * inch)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(NAVY)
        canvas.drawString(0.62 * inch, height - 0.35 * inch, clinic.upper())
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(RED)
        canvas.drawRightString(width - 0.62 * inch, height - 0.35 * inch, "SYNTHETIC - TEST ONLY")
        canvas.setStrokeColor(LINE)
        canvas.line(0.62 * inch, 0.48 * inch, width - 0.62 * inch, 0.48 * inch)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MID_GRAY)
        canvas.drawString(0.62 * inch, 0.31 * inch, "Fictional record for authorized software testing")
        canvas.drawRightString(width - 0.62 * inch, 0.31 * inch, f"PDF page {doc.page}")
        canvas.restoreState()

    return draw


def _key_value_table(rows: Iterable[tuple[str, str, str, str]]) -> Table:
    data = [
        [
            _paragraph(left_label, SMALL_BOLD),
            _paragraph(left_value, SMALL),
            _paragraph(right_label, SMALL_BOLD),
            _paragraph(right_value, SMALL),
        ]
        for left_label, left_value, right_label, right_value in rows
    ]
    table = Table(data, colWidths=[1.0 * inch, 2.25 * inch, 1.0 * inch, 2.25 * inch], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), PALE_GRAY),
                ("BACKGROUND", (2, 0), (2, -1), PALE_GRAY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _data_table(section: Section) -> Table:
    data = [[_paragraph(value, SMALL_BOLD) for value in section.table_headers]]
    data.extend([[_paragraph(value, SMALL) for value in row] for row in section.table_rows])
    table = Table(data, colWidths=list(section.table_widths), repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PALE_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE_GRAY]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def build_chart(
    filename: str,
    clinic: str,
    specialty: str,
    patient_rows: tuple[tuple[str, str, str, str], ...],
    request_rows: tuple[tuple[str, str, str, str], ...],
    sections: tuple[Section, ...],
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    doc = SimpleDocTemplate(
        str(path),
        pagesize=LETTER,
        leftMargin=0.62 * inch,
        rightMargin=0.62 * inch,
        topMargin=0.62 * inch,
        bottomMargin=0.62 * inch,
        title=f"Synthetic patient chart - {filename}",
        author="Aira regression test pack",
        subject="Synthetic medical necessity test record",
    )

    story = [
        Spacer(1, 0.06 * inch),
        _paragraph("SYNTHETIC PATIENT RECORD - SOFTWARE TESTING ONLY", BADGE),
        Spacer(1, 0.08 * inch),
        _paragraph("Patient Medical Chart", TITLE),
        _paragraph(f"{clinic} | {specialty} | Florida", SUBTITLE),
        _paragraph("1. Patient and coverage information", SECTION_TITLE),
        _key_value_table(patient_rows),
        _paragraph("2. Prior authorization request", SECTION_TITLE),
        _key_value_table(request_rows),
    ]

    for number, section in enumerate(sections, start=3):
        content = [_paragraph(f"{number}. {section.title}", SECTION_TITLE)]
        content.extend(_paragraph(paragraph) for paragraph in section.paragraphs)
        if section.table_headers:
            content.append(_data_table(section))
        story.append(KeepTogether(content))

    story.extend(
        [
            Spacer(1, 0.12 * inch),
            _paragraph(
                "Attestation: This is a wholly fictional record created for software regression testing. "
                "It must not be used for clinical care, billing, or coverage determination.",
                SUBTITLE,
            ),
        ]
    )
    draw = _header_footer(clinic)
    doc.build(story, onFirstPage=draw, onLaterPages=draw)


def generate() -> None:
    build_chart(
        "bcbs_case_01_varicose_veins_met.pdf",
        clinic="Atlantic Vein and Vascular Center",
        specialty="Vascular Surgery",
        patient_rows=(
            ("Patient", "Elena Sofia Garcia", "DOB / age", "1967-04-18 / 59"),
            ("Member ID", "FLB-SYN-1001", "Plan", "Florida Blue PPO (synthetic)"),
            ("Chart ID", "AVV-2026-1042", "Encounter", "2026-07-08"),
            ("Clinician", "Priya Nair, MD", "Location", "Tampa, FL"),
        ),
        request_rows=(
            ("Procedure", "Endovenous radiofrequency ablation, right great saphenous vein", "CPT", "36475"),
            ("Diagnosis", "Symptomatic venous insufficiency with right-leg varicosities", "ICD-10", "I87.2; I83.891"),
            ("Laterality", "Right", "Requested date", "2026-07-22"),
            ("Authorization", "Initial request", "Payer", "Florida Blue"),
        ),
        sections=(
            Section(
                "Clinical history and symptoms",
                paragraphs=(
                    "The patient has persistent right medial-calf aching, swelling, itching, and burning that began in January 2026 and is worse after standing. Symptoms are anatomically associated with the refluxing right great saphenous distribution.",
                    "Symptoms significantly interfere with activities of daily living. She cannot stand longer than 20 minutes to cook, has stopped her usual grocery-shopping trips, and must elevate the leg during her workday. Pain is rated 7/10 by late afternoon despite conservative care.",
                    "Examination documents rope-like right medial-calf varicosities measuring 4.2 to 5.0 mm, pitting ankle edema, and intact skin without ulceration. The treating clinician assigns CEAP class C3.",
                ),
            ),
            Section(
                "Venous duplex ultrasound - 2026-06-26",
                table_headers=("Finding", "Result", "Interpretation"),
                table_rows=(
                    ("Right great saphenous vein", "Reflux 2.8 seconds at SFJ and proximal thigh", "Pathologic saphenous reflux demonstrated"),
                    ("Visible tributary varicosities", "4.2 to 5.0 mm", "At least 3 mm"),
                    ("Deep venous system", "Compressible; no thrombus", "No DVT"),
                    ("Left leg", "No clinically significant reflux", "Not included in request"),
                ),
                table_widths=(2.0 * inch, 2.25 * inch, 2.25 * inch),
            ),
            Section(
                "Conservative management",
                paragraphs=(
                    "From 2026-02-01 through 2026-06-30, the patient wore prescribed 20-30 mmHg graduated compression stockings during waking hours for five months. Adherence is documented in the nursing log and at follow-up visits.",
                    "She also completed leg elevation, daily walking, weight management counseling, and as-needed acetaminophen. Persistent pain, edema, itching, and burning did not materially improve after more than three months of compression therapy.",
                ),
            ),
            Section(
                "Assessment and plan",
                paragraphs=(
                    "Assessment: Symptomatic right great saphenous venous insufficiency with documented reflux, CEAP C3 disease, varicosities greater than 3 mm, substantial ADL interference, and failed conservative management.",
                    "Plan: Proceed with endovenous radiofrequency ablation of the right great saphenous vein. No treatment is requested for the left leg, accessory veins, perforator veins, or telangiectasia.",
                ),
            ),
        ),
    )

    build_chart(
        "bcbs_case_02_carotid_stenting_not_met.pdf",
        clinic="Gulf Atlantic Vascular Institute",
        specialty="Vascular Surgery and Neurology",
        patient_rows=(
            ("Patient", "Thomas Allen Reed", "DOB / age", "1953-02-11 / 73"),
            ("Member ID", "FLB-SYN-1002", "Plan", "Florida Blue PPO (synthetic)"),
            ("Chart ID", "GAVI-2026-2287", "Encounter", "2026-07-02"),
            ("Clinician", "Aaron Feldman, MD", "Location", "Jacksonville, FL"),
        ),
        request_rows=(
            ("Procedure", "Right carotid angioplasty and stenting with distal embolic protection", "CPT", "37215"),
            ("Diagnosis", "Symptomatic right internal carotid artery stenosis", "ICD-10", "I65.21"),
            ("Laterality", "Right", "Requested date", "2026-07-20"),
            ("Authorization", "Initial request", "Payer", "Florida Blue"),
        ),
        sections=(
            Section(
                "Focal cerebral ischemic event",
                paragraphs=(
                    "On 2026-06-15, the patient experienced abrupt left arm weakness and expressive aphasia lasting 18 minutes. Symptoms resolved completely within 24 hours and neurology diagnosed a right-carotid-territory transient ischemic attack. There is no residual disability.",
                    "The event occurred 35 days before the proposed procedure and is documented as focal cerebral ischemia rather than nonspecific dizziness or syncope.",
                ),
            ),
            Section(
                "Vascular imaging",
                table_headers=("Study", "Result", "Clinical interpretation"),
                table_rows=(
                    ("CTA neck - 2026-06-16", "78% stenosis of proximal right internal carotid artery by NASCET", "Within 50% to 99% range"),
                    ("Duplex - 2026-06-18", "PSV 286 cm/s; EDV 108 cm/s", "Confirms severe right ICA stenosis"),
                    ("Brain MRI - 2026-06-16", "No acute infarct or hemorrhage", "TIA; no disabling stroke"),
                ),
                table_widths=(1.8 * inch, 2.55 * inch, 2.15 * inch),
            ),
            Section(
                "Carotid endarterectomy suitability",
                paragraphs=(
                    "The lesion is surgically accessible. The patient has no prior neck radiotherapy, no prior neck surgery, no tracheostomy, normal cervical mobility, and no high cervical or otherwise inaccessible lesion.",
                    "Vascular surgery explicitly documents that there is no anatomic contraindication to carotid endarterectomy. He is a suitable candidate for standard carotid endarterectomy, which was offered as the preferred treatment.",
                    "The patient prefers a less invasive approach and requested carotid stenting. Patient preference does not create an anatomic contraindication to carotid endarterectomy.",
                ),
            ),
            Section(
                "Medical therapy and authorization rationale",
                paragraphs=(
                    "Current therapy includes aspirin 81 mg daily, clopidogrel 75 mg daily, atorvastatin 80 mg nightly, and blood-pressure control. There is no carotid artery dissection.",
                    "Plan submitted for authorization: carotid angioplasty with stent placement and distal embolic protection. The record intentionally documents that the required anatomic contraindication to carotid endarterectomy is absent.",
                ),
            ),
        ),
    )

    build_chart(
        "bcbs_case_03_intracranial_thrombectomy_insufficient.pdf",
        clinic="Suncoast Comprehensive Stroke Center",
        specialty="Emergency Neurology and Neurointervention",
        patient_rows=(
            ("Patient", "Marcus Daniel Lee", "DOB / age", "1961-09-03 / 64"),
            ("Member ID", "FLB-SYN-1003", "Plan", "Florida Blue PPO (synthetic)"),
            ("Chart ID", "SCSC-2026-0715", "Encounter", "2026-07-15"),
            ("Clinician", "Nina Shah, MD", "Location", "Orlando, FL"),
        ),
        request_rows=(
            ("Procedure", "Endovascular mechanical embolectomy for acute ischemic stroke", "CPT", "61645"),
            ("Diagnosis", "Acute left middle cerebral artery occlusion", "ICD-10", "I63.512"),
            ("Target", "Proximal left M1 segment", "Requested", "Emergent, 2026-07-15"),
            ("Authorization", "Emergency retrospective review", "Payer", "Florida Blue"),
        ),
        sections=(
            Section(
                "Stroke timeline and neurological deficit",
                table_headers=("Time", "Event", "Finding"),
                table_rows=(
                    ("06:20", "Last known well", "Normal speech and right-sided strength"),
                    ("07:05", "Emergency department arrival", "Aphasia, right facial droop, right arm and leg weakness"),
                    ("07:18", "NIH Stroke Scale", "NIHSS 16; substantial clinically significant deficit"),
                    ("11:40", "Neurointerventional decision", "Planned thrombectomy 5 hours 20 minutes after onset"),
                ),
                table_widths=(0.75 * inch, 2.05 * inch, 3.7 * inch),
            ),
            Section(
                "Imaging available in the chart",
                paragraphs=(
                    "CTA head demonstrates an occlusion of the proximal left M1 segment of the middle cerebral artery, within the proximal intracranial anterior circulation.",
                    "Noncontrast CT shows no intracranial hemorrhage. CTA shows no arterial dissection.",
                    "A CT perfusion study was reportedly performed at the transferring facility, but the source images and final neuroradiology report are not present in this chart. No ASPECTS score, ischemic-core volume, penumbra measurement, or other documented evidence of salvageable brain tissue is available for review. Salvageable tissue must not be inferred from the other findings.",
                ),
            ),
            Section(
                "Treatment and transfer documentation",
                paragraphs=(
                    "The patient received tenecteplase at 07:32 after standard screening. There was no clinical improvement before transfer. Blood pressure was managed per stroke protocol.",
                    "The receiving neurointerventional team planned FDA-cleared mechanical thrombectomy within 12 hours of symptom onset based on the M1 occlusion and NIHSS 16. The missing perfusion/ASPECTS documentation remained unresolved at the time of retrospective review.",
                ),
            ),
            Section(
                "Documentation gap",
                paragraphs=(
                    "The chart establishes proximal anterior-circulation occlusion, treatment timing within 12 hours, substantial neurological deficit, and absence of hemorrhage or dissection.",
                    "The chart does not establish the mandatory criterion of salvageable brain tissue in the affected vascular territory. A signed ASPECTS or perfusion interpretation is required to complete the review.",
                ),
            ),
        ),
    )


if __name__ == "__main__":
    generate()
