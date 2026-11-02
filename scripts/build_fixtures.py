"""Generate the synthetic sample documents and test-case variants in fixtures/docs.

All documents describe a fictional offshore gas operator ("Region South Gas Operator")
and are written around three planned Issues: riser corrosion, repeated pump failure and a
safety barrier integrity gap. Public documents in fixtures/docs/public are not generated
here; their manifest rows are kept as they are.

Run from the repository root, with throwaway dependencies so they stay out of pyproject.toml:

    uv run --with python-docx --with reportlab --with pypdf python scripts/build_fixtures.py

LibreOffice (`soffice`) is used for the legacy `.doc` files. Without it those files are
skipped with a warning. The script never touches the network.
"""

import csv
import io
import random
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from docx import Document
from docx.shared import Pt
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import ListFlowable, ListItem, SimpleDocTemplate, Spacer
from reportlab.platypus import Paragraph as PdfParagraph
from reportlab.platypus import Table as PdfTable
from reportlab.platypus import TableStyle as PdfTableStyle

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "docs"
MANIFEST_PATH = FIXTURES_DIR / "manifest.csv"
MANIFEST_COLUMNS = (
    "id",
    "file",
    "format",
    "origin",
    "node",
    "layer",
    "document_type",
    "confidentiality",
    "version",
    "previous_version_id",
    "duplicate_of",
    "related_issue",
    "source_url",
    "license",
)
FICTION_NOTICE = "Fictional test fixture. Region South Gas Operator is not a real company."

# A fixed timestamp keeps regenerated DOCX files byte-identical, so git only sees real changes.
FIXED_ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)

NODE_LAYERS = {
    "national_oil_company": 0,
    "region_south_operator": 1,
    "platform_sp12": 2,
    "platform_sp14": 2,
    "sp12_inspection_team": 3,
    "sp12_maintenance_team": 3,
    "region_south_hse_team": 3,
    "region_south_well_operations_team": 3,
    "region_south_archive": 4,
}

RISER_CORROSION = "riser_corrosion_sp12"
PUMP_FAILURE = "pump_failure_sp12"
BARRIER_GAP = "safety_barrier_gap_sp12"


@dataclass(frozen=True)
class Heading:
    """A section heading; level 1 is a top-level section."""

    text: str
    level: int = 1


@dataclass(frozen=True)
class Paragraph:
    """A plain body paragraph."""

    text: str


@dataclass(frozen=True)
class Bullets:
    """A bulleted list."""

    items: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    """A table with one header row."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


Block = Heading | Paragraph | Bullets | Table


@dataclass(frozen=True)
class FixtureDocument:
    """One generated file and the metadata written to its manifest row."""

    id: str
    file: str
    title: str
    author: str
    issued_on: date
    node: str
    document_type: str
    confidentiality: str
    related_issues: tuple[str, ...]
    blocks: tuple[Block, ...]
    version: int = 1
    previous_version_id: str = ""
    duplicate_of: str = ""
    is_scanned: bool = False

    @property
    def file_format(self) -> str:
        """Return the file extension without the dot."""
        return Path(self.file).suffix.lstrip(".")


@dataclass(frozen=True)
class ExactCopy:
    """A byte-identical copy of another fixture under a different filename."""

    id: str
    file: str
    source_id: str


def _document_control_table(document: FixtureDocument) -> Table:
    return Table(
        header=("Field", "Value"),
        rows=(
            ("Document ID", document.id.upper()),
            ("Revision", str(document.version)),
            ("Date", document.issued_on.isoformat()),
            ("Prepared by", document.author),
            ("Owner node", document.node),
            ("Classification", document.confidentiality.upper()),
        ),
    )


def _all_blocks(document: FixtureDocument) -> tuple[Block, ...]:
    return (_document_control_table(document), *document.blocks)


# Shared verbatim between an inspection report and a later shift report, so the
# partial-overlap detector has an exact paragraph to find.
RISER_R3_SPLASH_ZONE_FINDING = (
    "Wall loss on riser R-3 is concentrated in the splash zone between EL +5.0 m and EL +9.0 m, "
    "on the south-facing side (3 to 6 o'clock). The coating there has blistered and disbonded "
    "over roughly 1.8 m2, and cathodic protection does not reach this zone because it is above "
    "the mean water line for most of the tide cycle. The minimum reading of 18.9 mm at EL +8.5 m "
    "is 1.2 mm thinner than the same location in April 2024."
)

RISER_R3_2024_READINGS = (
    ("R-3 EL +12.0 m, 12 o'clock", "22.2", "21.9", "2024-04-16", "D. Okafor"),
    ("R-3 EL +12.0 m, 6 o'clock", "22.2", "21.7", "2024-04-16", "D. Okafor"),
    ("R-3 EL +8.5 m, 3 o'clock", "22.2", "20.4", "2024-04-16", "D. Okafor"),
    ("R-3 EL +8.5 m, 6 o'clock", "22.2", "20.1", "2024-04-16", "D. Okafor"),
    ("R-3 EL +5.0 m, 6 o'clock", "22.2", "20.9", "2024-04-17", "M. Rostami"),
    ("R-3 EL +2.0 m, 6 o'clock", "22.2", "21.6", "2024-04-17", "M. Rostami"),
    ("R-3 clamp C-2, 9 o'clock", "22.2", "21.8", "2024-04-17", "M. Rostami"),
)

RISER_R3_2026_READINGS = (
    ("R-3 EL +12.0 m, 12 o'clock", "22.2", "21.8", "2026-03-09", "D. Okafor"),
    ("R-3 EL +12.0 m, 6 o'clock", "22.2", "21.5", "2026-03-09", "D. Okafor"),
    ("R-3 EL +8.5 m, 3 o'clock", "22.2", "19.3", "2026-03-09", "D. Okafor"),
    ("R-3 EL +8.5 m, 6 o'clock", "22.2", "18.9", "2026-03-09", "D. Okafor"),
    ("R-3 EL +5.0 m, 6 o'clock", "22.2", "20.0", "2026-03-10", "M. Rostami"),
    ("R-3 EL +2.0 m, 6 o'clock", "22.2", "21.4", "2026-03-10", "M. Rostami"),
    ("R-3 clamp C-2, 9 o'clock", "22.2", "21.7", "2026-03-10", "M. Rostami"),
)

RISER_R3_ROPE_ACCESS_READINGS = (
    ("R-3 EL +6.5 m, 4 o'clock", "22.2", "18.6", "2026-04-02", "M. Rostami"),
    ("R-3 EL +6.5 m, 5 o'clock", "22.2", "18.4", "2026-04-02", "M. Rostami"),
    ("R-3 EL +7.5 m, 5 o'clock", "22.2", "18.7", "2026-04-02", "M. Rostami"),
)

UT_HEADER = ("Location", "Nominal (mm)", "Measured (mm)", "Date", "Inspector")


def _inspection_riser_2024() -> FixtureDocument:
    return FixtureDocument(
        id="ins-01",
        file="synthetic/inspection_sp12_riser_r3_2024.docx",
        title="Ultrasonic Wall Thickness Survey - Gas Export Riser R-3, Platform SP-12 (2024)",
        author="Daniel Okafor, NDT Inspector",
        issued_on=date(2024, 4, 22),
        node="sp12_inspection_team",
        document_type="inspection_report",
        confidentiality="internal",
        related_issues=(RISER_CORROSION,),
        blocks=(
            Heading("1. Scope"),
            Paragraph(
                "This report covers the 2024 ultrasonic thickness (UT) survey of the 20-inch gas "
                "export riser R-3 on Platform SP-12, from the topsides tie-in at EL +12.0 m down "
                "to EL +2.0 m. The riser is API 5L X65 line pipe with a nominal wall of 22.2 mm "
                "and a minimum allowable wall of 17.5 mm. Readings were taken with a calibrated "
                "single-element probe through the coating where it was intact, and on bare metal "
                "where coating had already failed."
            ),
            Heading("2. Readings"),
            Table(UT_HEADER, RISER_R3_2024_READINGS),
            Heading("3. Findings"),
            Bullets(
                (
                    "General wall loss above EL +10 m is below 0.5 mm and consistent with the "
                    "2021 baseline.",
                    "Localised wall loss of up to 2.1 mm in the splash zone at EL +8.5 m, "
                    "south-facing side.",
                    "Coating breakdown (blistering, rust staining) over about 0.6 m2 in the "
                    "splash zone.",
                    "No defects found at clamp C-2.",
                )
            ),
            Heading("4. Recommendation"),
            Paragraph(
                "Repeat the splash zone survey within 24 months and add more clock positions "
                "between EL +5 m and EL +9 m. Plan a coating repair for the splash zone at the "
                "next suitable weather window."
            ),
        ),
    )


def _inspection_riser_2026_v1() -> FixtureDocument:
    return FixtureDocument(
        id="ins-02-v1",
        file="synthetic/inspection_sp12_riser_r3_2026_v1.docx",
        title="Ultrasonic Wall Thickness Survey - Gas Export Riser R-3, Platform SP-12 (2026)",
        author="Daniel Okafor, NDT Inspector",
        issued_on=date(2026, 3, 16),
        node="sp12_inspection_team",
        document_type="inspection_report",
        confidentiality="internal",
        related_issues=(RISER_CORROSION,),
        blocks=(
            Heading("1. Scope"),
            Paragraph(
                "Repeat UT survey of riser R-3, as recommended in the 2024 report INS-01. Same "
                "locations and the same probe type were used so the readings can be compared "
                "directly. Rope access was not available during this campaign."
            ),
            Heading("2. Readings"),
            Table(UT_HEADER, RISER_R3_2026_READINGS),
            Heading("3. Findings"),
            Paragraph(RISER_R3_SPLASH_ZONE_FINDING),
            Paragraph(
                "The corrosion rate at EL +8.5 m, 6 o'clock is about 0.63 mm per year over the "
                "last 23 months. At this rate the wall reaches the 17.5 mm minimum allowable "
                "thickness in about 2.2 years, by mid-2028."
            ),
            Heading("4. Recommendation"),
            Bullets(
                (
                    "Raise riser R-3 splash zone corrosion as an Issue with the regional "
                    "integrity group.",
                    "Carry out a rope access survey of EL +5 m to EL +9 m at extra clock "
                    "positions before the next revision of this report.",
                    "Assess repair options: splash zone wrap, clamp-on sleeve, or riser "
                    "section replacement.",
                )
            ),
        ),
    )


def _inspection_riser_2026_v2() -> FixtureDocument:
    v1 = _inspection_riser_2026_v1()
    return replace(
        v1,
        id="ins-02-v2",
        file="cases/inspection_sp12_riser_r3_2026_v2.docx",
        issued_on=date(2026, 4, 9),
        version=2,
        previous_version_id=v1.id,
        blocks=(
            Heading("Change note"),
            Paragraph(
                "Revision 2 adds three rope access readings taken on 2026-04-02 between "
                "EL +6.5 m and EL +7.5 m, revises the minimum measured wall from 18.9 mm to "
                "18.4 mm, and shortens the estimated remaining life from 2.2 to 1.4 years. "
                "Readings from revision 1 are unchanged."
            ),
            Heading("1. Scope"),
            Paragraph(
                "Repeat UT survey of riser R-3, as recommended in the 2024 report INS-01, "
                "extended with a rope access survey of the splash zone."
            ),
            Heading("2. Readings"),
            Table(UT_HEADER, RISER_R3_2026_READINGS + RISER_R3_ROPE_ACCESS_READINGS),
            Heading("3. Findings"),
            Paragraph(RISER_R3_SPLASH_ZONE_FINDING),
            Paragraph(
                "The rope access readings found thinner wall at EL +6.5 m, 5 o'clock (18.4 mm). "
                "Using the 2024 reading at the nearest surveyed point, the local corrosion rate "
                "is about 0.9 mm per year, giving roughly 1.4 years to the 17.5 mm minimum."
            ),
            Heading("4. Recommendation"),
            Bullets(
                (
                    "Treat riser R-3 splash zone corrosion as a high-priority Issue.",
                    "Install a temporary splash zone wrap within 6 months.",
                    "Commission an engineering assessment of a permanent clamp-on sleeve "
                    "versus riser section replacement.",
                    "Reduce the survey interval for R-3 to 6 months until a repair is in place.",
                )
            ),
        ),
    )


def _inspection_firewater_caisson() -> FixtureDocument:
    return FixtureDocument(
        id="ins-03",
        file="synthetic/inspection_sp12_firewater_caisson_2026.docx",
        title="UT Survey - Firewater Pump Caisson FW-P-7101A and Deluge Ring Main, Platform SP-12",
        author="Mehdi Rostami, NDT Inspector",
        issued_on=date(2026, 5, 20),
        node="sp12_inspection_team",
        document_type="inspection_report",
        confidentiality="confidential",
        related_issues=(BARRIER_GAP,),
        blocks=(
            Heading("1. Scope"),
            Paragraph(
                "UT survey of the caisson of diesel firewater pump FW-P-7101A and of the riser "
                "area deluge ring main. Both are safety-critical elements under performance "
                "standard PS-12 (firewater). The caisson is 24-inch carbon steel with a nominal "
                "wall of 12.7 mm and a minimum allowable wall of 8.0 mm."
            ),
            Heading("2. Readings"),
            Table(
                UT_HEADER,
                (
                    ("Caisson EL +4.0 m, 0 deg", "12.7", "11.9", "2026-05-12", "M. Rostami"),
                    ("Caisson EL +1.0 m, 90 deg", "12.7", "10.6", "2026-05-12", "M. Rostami"),
                    ("Caisson EL -2.0 m, 180 deg", "12.7", "7.9", "2026-05-13", "M. Rostami"),
                    ("Caisson EL -2.0 m, 270 deg", "12.7", "8.4", "2026-05-13", "M. Rostami"),
                    ("Deluge ring main DR-04", "7.1", "6.8", "2026-05-14", "D. Okafor"),
                    ("Deluge ring main DR-07", "7.1", "5.2", "2026-05-14", "D. Okafor"),
                ),
            ),
            Heading("3. Findings"),
            Bullets(
                (
                    "The caisson reading at EL -2.0 m, 180 deg (7.9 mm) is below the 8.0 mm "
                    "minimum allowable wall.",
                    "Deluge ring main DR-07 shows internal wall loss and scale. Two deluge "
                    "nozzles downstream of DR-07 were found partly blocked during the last "
                    "function test.",
                    "Together these findings mean the firewater barrier for the riser area "
                    "may not meet its PS-12 performance standard.",
                    "The closure time of riser ESD valve ESDV-1203 was outside the scope of "
                    "this survey but is reported as a separate barrier concern.",
                )
            ),
            Heading("4. Recommendation"),
            Paragraph(
                "Record a barrier impairment for PS-12 and put compensating measures in place. "
                "Plan a caisson repair or sleeve, flush and replace deluge pipework at DR-07, "
                "and repeat the deluge function test after the work."
            ),
        ),
    )


def _shift_report(
    *,
    document_id: str,
    file: str,
    issued_on: date,
    author: str,
    related_issues: tuple[str, ...],
    blocks: tuple[Block, ...],
) -> FixtureDocument:
    return FixtureDocument(
        id=document_id,
        file=file,
        title=f"Shift Handover Report - Platform SP-12 - {issued_on.isoformat()}",
        author=author,
        issued_on=issued_on,
        node="platform_sp12",
        document_type="shift_report",
        confidentiality="internal",
        related_issues=related_issues,
        blocks=blocks,
    )


def _shift_reports() -> list[FixtureDocument]:
    return [
        _shift_report(
            document_id="shift-01",
            file="synthetic/shift_report_sp12_2026_08_04.docx",
            issued_on=date(2026, 8, 4),
            author="Kaveh Bahrami, Night Shift Supervisor",
            related_issues=(PUMP_FAILURE,),
            blocks=(
                Heading("Plant status"),
                Paragraph(
                    "Production steady at 410 MMscfd. Both export risers in service. Seawater "
                    "lift pump P-4101A duty, P-4101B standby."
                ),
                Heading("Events"),
                Paragraph(
                    "02:40 P-4101A tripped on high vibration (11.2 mm/s at motor non-drive end, "
                    "trip set point 10 mm/s). P-4101B started automatically and has run "
                    "normally since. This is the first trip since the P-4101A motor was "
                    "replaced on 2026-07-18."
                ),
                Paragraph(
                    "04:10 Maintenance checked coupling and alignment with a dial gauge and "
                    "reported it within tolerance. No soft foot check was done because the "
                    "feeler gauge set was on the other platform."
                ),
                Heading("Handover actions"),
                Bullets(
                    (
                        "Day shift to restart P-4101A after maintenance sign-off and log "
                        "vibration every 2 hours for the first 24 hours.",
                        "Raise a notification for a laser alignment check.",
                    )
                ),
            ),
        ),
        _shift_report(
            document_id="shift-02",
            file="synthetic/shift_report_sp12_2026_08_21.docx",
            issued_on=date(2026, 8, 21),
            author="Ali Tehrani, Day Shift Supervisor",
            related_issues=(PUMP_FAILURE, BARRIER_GAP),
            blocks=(
                Heading("Plant status"),
                Paragraph(
                    "Production at 395 MMscfd. P-4101A back on duty since 2026-08-05, P-4101B "
                    "standby."
                ),
                Heading("Events"),
                Paragraph(
                    "11:15 High bearing temperature alarm on P-4101A drive-end bearing "
                    "(92 deg C, alarm 90 deg C). 11:32 the pump tripped at 96 deg C. P-4101B "
                    "took over. P-4101A had run for 16 days since the last restart. Vibration "
                    "had crept up from 4.1 to 7.6 mm/s over the last week."
                ),
                Paragraph(
                    "14:00 Monthly partial stroke test of riser ESD valve ESDV-1203 failed: "
                    "the valve moved but the stroke time was 38 s against a 20 s acceptance "
                    "limit. Instrument technician suspects a sticking solenoid or hydraulic "
                    "supply restriction."
                ),
                Heading("Handover actions"),
                Bullets(
                    (
                        "Keep P-4101A isolated. Maintenance to inspect bearings and take an "
                        "oil sample.",
                        "Report ESDV-1203 as a safety-critical element failure to the OIM and "
                        "the regional HSE team. Raise a barrier impairment.",
                    )
                ),
            ),
        ),
        _shift_report(
            document_id="shift-03",
            file="synthetic/shift_report_sp12_2026_09_09.docx",
            issued_on=date(2026, 9, 9),
            author="Kaveh Bahrami, Night Shift Supervisor",
            related_issues=(PUMP_FAILURE, BARRIER_GAP),
            blocks=(
                Heading("Plant status"),
                Paragraph(
                    "Production cut back to 350 MMscfd to reduce cooling demand. P-4101A "
                    "restarted on 2026-09-05 after a bearing change."
                ),
                Heading("Events"),
                Paragraph(
                    "01:55 P-4101A tripped on high vibration again (10.8 mm/s), after only 4 "
                    "days of running. This is the third trip in five weeks. P-4101B started "
                    "but is now running at 5.8 mm/s, higher than its usual 3 mm/s."
                ),
                Paragraph(
                    "03:20 Low pressure alarm on the firewater ring main jockey supply, which "
                    "is fed from the seawater lift header. Pressure recovered after the header "
                    "was lined up, but redundancy on seawater lift is effectively lost."
                ),
                Heading("Pattern noted by shift"),
                Paragraph(
                    "All three P-4101A trips happened after the July motor replacement. Each "
                    "run was shorter than the last (16, 16 and 4 days). Bearing change did not "
                    "fix it. Shift recommends a proper root cause analysis rather than another "
                    "bearing swap."
                ),
                Heading("Handover actions"),
                Bullets(
                    (
                        "OIM to ask the regional operator for specialist support on P-4101A.",
                        "Monitor P-4101B vibration hourly. Do not exceed 7 mm/s.",
                    )
                ),
            ),
        ),
    ]


def _shift_report_with_copied_paragraph() -> FixtureDocument:
    return _shift_report(
        document_id="shift-04",
        file="cases/shift_report_sp12_2026_09_27.docx",
        issued_on=date(2026, 9, 27),
        author="Ali Tehrani, Day Shift Supervisor",
        related_issues=(RISER_CORROSION, PUMP_FAILURE),
        blocks=(
            Heading("Plant status"),
            Paragraph(
                "Production at 360 MMscfd. P-4101A still isolated pending failure analysis. "
                "P-4101B on duty at 5.5 mm/s."
            ),
            Heading("Events"),
            Paragraph(
                "Rope access team arrived for the riser R-3 splash zone wrap preparation. "
                "The inspection team asked that the following note from their report is "
                "passed to every shift until the wrap is installed:"
            ),
            Paragraph(RISER_R3_SPLASH_ZONE_FINDING),
            Paragraph(
                "No hot work or heavy lifts over the R-3 riser area until the wrap is in place. "
                "Regional operator confirmed an RFP for an independent pump failure analysis "
                "will be issued next week."
            ),
            Heading("Handover actions"),
            Bullets(
                (
                    "Support rope access permit for R-3 on day shift only.",
                    "Keep the P-4101A isolation in place and tagged.",
                )
            ),
        ),
    )


def _personnel_profile(
    *,
    document_id: str,
    file: str,
    name: str,
    role: str,
    node: str,
    related_issues: tuple[str, ...],
    summary: str,
    expertise: tuple[str, ...],
    certifications: tuple[str, ...],
    projects: tuple[tuple[str, str, str], ...],
) -> FixtureDocument:
    return FixtureDocument(
        id=document_id,
        file=file,
        title=f"Personnel Profile - {name}",
        author="Region South HR and Competence Office",
        issued_on=date(2026, 6, 1),
        node=node,
        document_type="personnel_profile",
        confidentiality="confidential",
        related_issues=related_issues,
        blocks=(
            Heading("Role"),
            Paragraph(f"{name}, {role}."),
            Paragraph(summary),
            Heading("Expertise"),
            Bullets(expertise),
            Heading("Certifications"),
            Bullets(certifications),
            Heading("Past projects"),
            Table(("Year", "Project", "Contribution"), projects),
        ),
    )


def _personnel_profiles() -> list[FixtureDocument]:
    return [
        _personnel_profile(
            document_id="prof-01",
            file="synthetic/profile_leila_moradi.docx",
            name="Dr. Leila Moradi",
            role="Senior Corrosion Engineer, SP-12 Inspection Team",
            node="sp12_inspection_team",
            related_issues=(RISER_CORROSION,),
            summary=(
                "Fourteen years in offshore integrity management, nine of them in Region South. "
                "Technical authority for corrosion on Platforms SP-11 to SP-14."
            ),
            expertise=(
                "External corrosion of risers and splash zone protection",
                "Corrosion growth rate analysis and remaining life assessment",
                "Risk-based inspection planning for pipelines and risers",
                "Coating and wrap systems for splash zones",
            ),
            certifications=(
                "AMPP Senior Corrosion Technologist",
                "API 570 Piping Inspector",
                "PhD in Materials Engineering",
            ),
            projects=(
                ("2022", "SP-11 riser splash zone wrap", "Lead engineer, selected wrap system"),
                ("2024", "SP-12 riser R-3 UT survey review", "Reviewed INS-01 findings"),
                ("2025", "Region South RBI plan update", "Wrote riser inspection intervals"),
                ("2026", "SP-12 riser R-3 integrity assessment", "Project lead"),
            ),
        ),
        _personnel_profile(
            document_id="prof-02",
            file="synthetic/profile_reza_kamali.docx",
            name="Reza Kamali",
            role="Corrosion and Cathodic Protection Engineer, SP-12 Inspection Team",
            node="sp12_inspection_team",
            related_issues=(RISER_CORROSION, BARRIER_GAP),
            summary=(
                "Seven years in cathodic protection design and survey for offshore jackets, "
                "risers and caissons."
            ),
            expertise=(
                "Sacrificial anode and impressed current CP design",
                "CP surveys with ROV and diver support",
                "Caisson internal corrosion and inhibitor programmes",
            ),
            certifications=(
                "AMPP CP3 Cathodic Protection Technologist",
                "IRATA Level 1 rope access",
            ),
            projects=(
                ("2021", "SP-12 riser R-3 baseline survey", "CP readings and anode inspection"),
                ("2023", "SP-14 jacket anode retrofit", "CP design calculations"),
                ("2026", "SP-12 firewater caisson assessment", "Caisson corrosion review"),
            ),
        ),
        _personnel_profile(
            document_id="prof-03",
            file="synthetic/profile_sara_nikpour.docx",
            name="Sara Nikpour",
            role="Rotating Equipment Engineer, SP-12 Maintenance Team",
            node="sp12_maintenance_team",
            related_issues=(PUMP_FAILURE,),
            summary=(
                "Ten years with centrifugal and vertical caisson pumps offshore. Led the 2019 "
                "root cause analysis of repeated seawater lift pump trips on SP-14."
            ),
            expertise=(
                "Vibration analysis and operating deflection shape studies",
                "Laser shaft alignment and soft foot correction",
                "Root cause analysis of pump and bearing failures",
                "Vertical turbine and caisson pump overhaul",
            ),
            certifications=(
                "ISO 18436-2 Vibration Analyst Category III",
                "Certified Maintenance and Reliability Professional (CMRP)",
            ),
            projects=(
                ("2019", "SP-14 P-4101B repeated trip RCA", "RCA lead, see RES-01"),
                ("2022", "Region South pump alignment standard", "Author"),
                ("2026", "SP-12 pump reliability study", "Project lead"),
            ),
        ),
        _personnel_profile(
            document_id="prof-04",
            file="synthetic/profile_hamid_farahani.docx",
            name="Hamid Farahani",
            role="Well Control Specialist, Region South Well Operations Team",
            node="region_south_well_operations_team",
            related_issues=(BARRIER_GAP,),
            summary=(
                "Twenty years in drilling and well operations, including six as a rig-based "
                "well control supervisor. Now the regional authority on well barrier "
                "verification."
            ),
            expertise=(
                "Well barrier schematics and barrier verification testing",
                "Blowout preventer testing and maintenance review",
                "Surface and subsurface safety valve testing",
                "Kick detection and well kill planning",
            ),
            certifications=(
                "IWCF Level 4 Well Control (Supervisor), surface and subsea",
                "IADC WellSharp Supervisor",
            ),
            projects=(
                ("2020", "SP-14 well integrity campaign", "Barrier verification lead"),
                ("2024", "Region South well barrier standard", "Co-author"),
                ("2026", "SP-12 SCE barrier review", "Reviewed ESD and SSSV test records"),
            ),
        ),
        _personnel_profile(
            document_id="prof-05",
            file="synthetic/profile_nasrin_jafari.docx",
            name="Nasrin Jafari",
            role="Process Safety Engineer, Region South HSE Team",
            node="region_south_hse_team",
            related_issues=(BARRIER_GAP,),
            summary=(
                "Eight years in process safety, with a focus on barrier management and "
                "performance standards for safety-critical elements."
            ),
            expertise=(
                "Bow-tie analysis and barrier management",
                "Performance standards for ESD, firewater and deluge systems",
                "Barrier impairment assessment and compensating measures",
            ),
            certifications=(
                "TUV Functional Safety Engineer (IEC 61511)",
                "NEBOSH International Diploma",
            ),
            projects=(
                ("2023", "Region South bow-tie library", "Lead author"),
                ("2025", "SP-12 performance standard review", "Updated PS-07 and PS-12"),
            ),
        ),
    ]


def _project_report_riser() -> FixtureDocument:
    return FixtureDocument(
        id="proj-01",
        file="synthetic/project_report_sp12_riser_r3_integrity.pdf",
        title="Project Report - SP-12 Riser R-3 Integrity Assessment",
        author="Dr. Leila Moradi, Senior Corrosion Engineer",
        issued_on=date(2026, 6, 30),
        node="sp12_inspection_team",
        document_type="project_report",
        confidentiality="internal",
        related_issues=(RISER_CORROSION,),
        blocks=(
            Heading("Project summary"),
            Table(
                ("Item", "Value"),
                (
                    ("Project name", "SP-12 Riser R-3 Integrity Assessment"),
                    ("Owner node", "sp12_inspection_team"),
                    ("Domain", "Asset integrity / external corrosion"),
                    ("Completion status", "Phase 1 complete, phase 2 in progress"),
                    ("Related executors", "Dr. Leila Moradi, Reza Kamali"),
                    ("Related knowledge items", "INS-01, INS-02 (rev 2), scanned 2021 baseline"),
                ),
            ),
            Heading("Research goals"),
            Bullets(
                (
                    "Measure the corrosion growth rate on riser R-3 in the splash zone.",
                    "Estimate the remaining life against the 17.5 mm minimum wall.",
                    "Compare repair options and recommend one.",
                )
            ),
            Heading("Documents used"),
            Paragraph(
                "2021 baseline survey (scanned paper record), 2024 survey INS-01, 2026 survey "
                "INS-02 revisions 1 and 2, the riser design basis, and the Region South RBI plan."
            ),
            Heading("Experiments and analyses"),
            Paragraph(
                "Readings from 2021, 2024 and 2026 were aligned by elevation and clock position. "
                "A linear growth model gave 0.63 mm per year at EL +8.5 m and about 0.9 mm per "
                "year at EL +6.5 m. Coating adhesion pull-off tests on two coupons gave 1.1 and "
                "1.4 MPa, well under the 5 MPa specified for the original system."
            ),
            Heading("Implementation activities"),
            Bullets(
                (
                    "Rope access survey added to the 2026 campaign.",
                    "Temporary splash zone wrap specified and ordered.",
                )
            ),
            Heading("Achievements"),
            Bullets(
                (
                    "First corrosion growth rate for R-3 based on three surveys.",
                    "Remaining life estimate accepted by the regional integrity group.",
                )
            ),
            Heading("Challenges"),
            Bullets(
                (
                    "The 2021 baseline exists only as a scanned paper record.",
                    "Readings in 2021 used different clock position labels, so two points "
                    "could not be matched.",
                    "Weather windows for rope access are short in winter.",
                )
            ),
            Heading("Unresolved questions"),
            Bullets(
                (
                    "Is the growth rate linear, or is it speeding up as the coating fails?",
                    "Can a clamp-on sleeve be installed without a production shutdown?",
                )
            ),
        ),
    )


def _project_report_pump() -> FixtureDocument:
    return FixtureDocument(
        id="proj-02",
        file="synthetic/project_report_sp12_pump_reliability.docx",
        title="Project Report - SP-12 Seawater Lift Pump Reliability Study",
        author="Sara Nikpour, Rotating Equipment Engineer",
        issued_on=date(2026, 9, 30),
        node="sp12_maintenance_team",
        document_type="project_report",
        confidentiality="internal",
        related_issues=(PUMP_FAILURE, BARRIER_GAP),
        blocks=(
            Heading("Project summary"),
            Table(
                ("Item", "Value"),
                (
                    ("Project name", "SP-12 Seawater Lift Pump Reliability Study"),
                    ("Owner node", "sp12_maintenance_team"),
                    ("Domain", "Rotating equipment reliability"),
                    ("Completion status", "On hold, waiting for external failure analysis"),
                    ("Related executors", "Sara Nikpour"),
                    ("Related RFPs", "RFP-01 (independent failure analysis of P-4101A)"),
                    ("Related knowledge items", "SHIFT-01 to SHIFT-03, RES-01"),
                ),
            ),
            Heading("Research goals"),
            Bullets(
                (
                    "Find why P-4101A trips repeatedly since the July 2026 motor replacement.",
                    "Check whether the 2019 SP-14 root cause applies to SP-12.",
                    "Restore seawater lift redundancy, which also supports the firewater "
                    "ring main jockey supply.",
                )
            ),
            Heading("Experiments and analyses"),
            Paragraph(
                "Vibration spectra from the three trips show a dominant 1x running speed "
                "component with a strong 2x component, which points to misalignment or a "
                "bent shaft rather than bearing defects alone. Oil analysis after the second "
                "trip found iron and silicon, suggesting bearing wear and some sand ingress."
            ),
            Heading("Implementation activities"),
            Bullets(
                (
                    "Drive-end bearing replaced on 2026-09-04.",
                    "Laser alignment kit requested from the regional workshop.",
                )
            ),
            Heading("Achievements"),
            Paragraph("Trip pattern documented and linked to the motor replacement date."),
            Heading("Challenges"),
            Bullets(
                (
                    "No laser alignment kit or soft foot gauges on SP-12.",
                    "No in-house metallurgical lab for the failed bearings.",
                )
            ),
            Heading("Unresolved questions"),
            Bullets(
                (
                    "Is the motor base plate distorted (soft foot)?",
                    "Is the column shaft bent or are the line shaft bearings worn?",
                    "Why is the standby pump P-4101B now also vibrating more?",
                )
            ),
        ),
    )


def _issue_resolution_sp14_pump() -> FixtureDocument:
    return FixtureDocument(
        id="res-01",
        file="synthetic/issue_resolution_sp14_pump_p4101b_2019.docx",
        title="Issue Resolution - Repeated Trips of Seawater Lift Pump P-4101B, Platform SP-14",
        author="Sara Nikpour, Rotating Equipment Engineer",
        issued_on=date(2019, 11, 15),
        node="region_south_archive",
        document_type="issue_resolution",
        confidentiality="internal",
        related_issues=(PUMP_FAILURE,),
        blocks=(
            Heading("Problem"),
            Paragraph(
                "Between May and August 2019, seawater lift pump P-4101B on Platform SP-14 "
                "tripped seven times on high vibration. Mean time between trips was 21 days. "
                "The trips started after the pump motor was replaced in April 2019."
            ),
            Heading("Investigation"),
            Bullets(
                (
                    "Vibration spectra showed high 1x and 2x components at the motor.",
                    "Laser alignment found 0.42 mm parallel offset, outside the 0.05 mm "
                    "tolerance. The previous dial gauge check had not found it.",
                    "Soft foot check found 0.25 mm on one motor foot.",
                    "Teardown found worn line shaft bearings with embedded sand.",
                    "Metallurgical lab analysis showed abrasive wear, not fatigue.",
                )
            ),
            Heading("Root cause"),
            Paragraph(
                "Misalignment after the motor replacement, made worse by soft foot, overloaded "
                "the bearings. Sand ingress through a damaged intake screen sped up the wear. "
                "The dial gauge procedure used offshore was not accurate enough for this pump."
            ),
            Heading("Fix"),
            Bullets(
                (
                    "Shimmed the motor base and corrected soft foot.",
                    "Laser aligned to within 0.05 mm.",
                    "Replaced line shaft bearings with a sand-tolerant material.",
                    "Replaced the intake screen and added it to the inspection plan.",
                    "Made laser alignment and soft foot checks mandatory after any motor "
                    "change in the Region South pump alignment standard.",
                )
            ),
            Heading("Result"),
            Paragraph(
                "No vibration trips in the following 14 months. Mean time between failures "
                "rose from 21 days to more than 400 days."
            ),
        ),
    )


def _node_descriptions() -> list[FixtureDocument]:
    return [
        FixtureDocument(
            id="node-01",
            file="synthetic/node_region_south_operator.docx",
            title="Node Description - Region South Gas Operator",
            author="Region South Planning Office",
            issued_on=date(2026, 1, 10),
            node="region_south_operator",
            document_type="node_description",
            confidentiality="public",
            related_issues=(RISER_CORROSION, PUMP_FAILURE, BARRIER_GAP),
            blocks=(
                Heading("Scope of activity"),
                Paragraph(
                    "Region South Gas Operator runs the offshore South Field gas development "
                    "on behalf of the National Oil Company. It operates four wellhead and "
                    "processing platforms (SP-11 to SP-14) and the export pipelines to the "
                    "onshore terminal."
                ),
                Heading("Responsibilities"),
                Bullets(
                    (
                        "Production planning and reporting to the National Oil Company.",
                        "Regional integrity, HSE and well operations teams that support "
                        "every platform.",
                        "Contracting, including RFPs for specialist studies.",
                        "Approving barrier impairments and major repairs.",
                    )
                ),
                Heading("Child nodes"),
                Paragraph(
                    "platform_sp12, platform_sp14, region_south_hse_team, "
                    "region_south_well_operations_team, region_south_archive."
                ),
            ),
        ),
        FixtureDocument(
            id="node-02",
            file="synthetic/node_platform_sp12.docx",
            title="Node Description - Platform SP-12",
            author="SP-12 Offshore Installation Manager",
            issued_on=date(2026, 1, 10),
            node="platform_sp12",
            document_type="node_description",
            confidentiality="internal",
            related_issues=(RISER_CORROSION, PUMP_FAILURE, BARRIER_GAP),
            blocks=(
                Heading("Scope of activity"),
                Paragraph(
                    "Platform SP-12 is a normally manned wellhead and processing platform in "
                    "South Field, 95 km offshore in 65 m of water. It has 12 production wells, "
                    "gas dehydration, and two 20-inch export risers (R-3 and R-4). Design "
                    "capacity is 450 MMscfd."
                ),
                Heading("Key systems"),
                Bullets(
                    (
                        "Seawater lift pumps P-4101A/B for cooling and firewater jockey supply.",
                        "Diesel firewater pumps FW-P-7101A/B and deluge systems.",
                        "Riser ESD valves ESDV-1203 (R-3) and ESDV-1204 (R-4).",
                    )
                ),
                Heading("Child nodes"),
                Paragraph("sp12_inspection_team, sp12_maintenance_team."),
            ),
        ),
        FixtureDocument(
            id="node-03",
            file="synthetic/node_platform_sp14.docx",
            title="Node Description - Platform SP-14",
            author="SP-14 Offshore Installation Manager",
            issued_on=date(2026, 1, 10),
            node="platform_sp14",
            document_type="node_description",
            confidentiality="internal",
            related_issues=(PUMP_FAILURE,),
            blocks=(
                Heading("Scope of activity"),
                Paragraph(
                    "Platform SP-14 is a wellhead platform with 8 wells and a smaller "
                    "processing train. It shares the seawater lift pump design (P-4101A/B) "
                    "with SP-12, so lessons from SP-14 pump failures apply to SP-12."
                ),
            ),
        ),
        FixtureDocument(
            id="node-04",
            file="synthetic/node_sp12_inspection_team.docx",
            title="Node Description - SP-12 Inspection Team",
            author="SP-12 Inspection Team Lead",
            issued_on=date(2026, 1, 10),
            node="sp12_inspection_team",
            document_type="node_description",
            confidentiality="internal",
            related_issues=(RISER_CORROSION, BARRIER_GAP),
            blocks=(
                Heading("Scope of activity"),
                Paragraph(
                    "The SP-12 inspection team plans and carries out non-destructive testing "
                    "of risers, piping, caissons and structures on Platform SP-12, and keeps "
                    "the corrosion records. It reports to the platform and to the regional "
                    "integrity group."
                ),
                Heading("Typical outputs"),
                Bullets(
                    (
                        "UT wall thickness surveys and inspection reports.",
                        "Corrosion growth rate and remaining life estimates.",
                        "Input to Issues and RFPs for repairs or specialist studies.",
                    )
                ),
            ),
        ),
    ]


def _rfp_pump_failure_analysis() -> FixtureDocument:
    return FixtureDocument(
        id="rfp-01",
        file="synthetic/rfp_sp12_pump_failure_analysis.docx",
        title="RFP-01 - Independent Failure Analysis of Seawater Lift Pump P-4101A, Platform SP-12",
        author="Region South Contracts Office",
        issued_on=date(2026, 10, 5),
        node="region_south_operator",
        document_type="rfp",
        confidentiality="internal",
        related_issues=(PUMP_FAILURE,),
        blocks=(
            Heading("1. Problem description"),
            Paragraph(
                "Seawater lift pump P-4101A on Platform SP-12 has tripped three times in five "
                "weeks since its motor was replaced in July 2026 (two high vibration trips, one "
                "high bearing temperature trip). The standby pump P-4101B now also shows rising "
                "vibration. Loss of both pumps would affect process cooling and the firewater "
                "ring main jockey supply."
            ),
            Heading("2. Sub-issues"),
            Bullets(
                (
                    "Inspection: on-site vibration, alignment and soft foot checks.",
                    "Root cause analysis: teardown and metallurgical analysis of failed parts.",
                    "Repair options: corrective actions for P-4101A and P-4101B.",
                )
            ),
            Heading("3. Related knowledge"),
            Paragraph(
                "Shift reports SHIFT-01 to SHIFT-03, the SP-12 pump reliability study "
                "(PROJ-02), and the 2019 SP-14 issue resolution (RES-01). These will be shared "
                "with the selected bidder."
            ),
            Heading("4. Research gaps"),
            Bullets(
                (
                    "Whether the 2019 SP-14 root cause (misalignment and soft foot) repeats.",
                    "Whether the column shaft or line shaft bearings are damaged.",
                    "Why the standby pump vibration is increasing.",
                )
            ),
            Heading("5. Technical requirements"),
            Bullets(
                (
                    "Vibration analysis by an ISO 18436-2 Category III analyst.",
                    "Laser alignment and soft foot measurement on both pumps.",
                    "Teardown inspection of P-4101A with a photographic record.",
                    "Metallurgical lab analysis of bearings and any failed shaft parts.",
                )
            ),
            Heading("6. Expected outputs"),
            Bullets(
                (
                    "Root cause analysis report with evidence for each cause.",
                    "Ranked repair options with cost and schedule estimates.",
                    "Changes to the maintenance procedure to prevent repeat failures.",
                )
            ),
            Heading("7. Evaluation criteria"),
            Table(
                ("Criterion", "Weight"),
                (
                    ("Understanding of the problem", "15%"),
                    ("Methodology and technical completeness", "30%"),
                    ("Team expertise", "20%"),
                    ("Schedule and feasibility", "10%"),
                    ("Risk and HSE management", "10%"),
                    ("Cost", "15%"),
                ),
            ),
            Heading("8. Mandatory requirements"),
            Bullets(
                (
                    "M1: Offshore HSE plan and valid offshore survival certificates for all "
                    "site staff.",
                    "M2: Metallurgical analysis in an accredited lab (ISO/IEC 17025).",
                    "M3: Final report within 12 weeks of contract award.",
                    "M4: Platform data stays on operator systems; no upload to external or "
                    "cloud services.",
                    "M5: A compliance matrix against this RFP.",
                )
            ),
            Heading("9. Constraints"),
            Paragraph(
                "Offshore bed space is limited to three people for at most 10 days. Work on "
                "P-4101B must not remove it from service for more than 4 hours at a time."
            ),
            Heading("10. Required expertise and documentation"),
            Paragraph(
                "Bidders must submit CVs of key staff, two references for similar pump RCAs, "
                "a phased schedule, a cost breakdown, and a risk register."
            ),
        ),
    )


def _proposal_strong() -> FixtureDocument:
    return FixtureDocument(
        id="prop-01",
        file="synthetic/proposal_meridian_rotating_integrity.pdf",
        title="Proposal for RFP-01 - Meridian Rotating Integrity (fictional)",
        author="Meridian Rotating Integrity, Bid Manager",
        issued_on=date(2026, 10, 26),
        node="region_south_operator",
        document_type="proposal",
        confidentiality="confidential",
        related_issues=(PUMP_FAILURE,),
        blocks=(
            Heading("1. Our understanding"),
            Paragraph(
                "P-4101A has tripped three times since its July 2026 motor replacement, with "
                "run times falling from 16 to 4 days. Spectra with strong 1x and 2x components, "
                "iron and silicon in the oil, and the 2019 SP-14 history all point to "
                "misalignment, possible soft foot and sand-assisted bearing wear. We will test "
                "these hypotheses and look for others, including a bent column shaft and base "
                "plate distortion, which could also explain the rising P-4101B vibration."
            ),
            Heading("2. Methodology"),
            Table(
                ("Phase", "Activities", "Duration"),
                (
                    ("1 Desk review", "Review shift reports, PROJ-02, RES-01, spectra", "1 week"),
                    (
                        "2 Offshore survey",
                        "Vibration and ODS on both pumps, laser alignment, soft foot, "
                        "base plate flatness, intake screen check",
                        "8 days offshore",
                    ),
                    (
                        "3 Teardown and lab",
                        "Teardown of P-4101A, shaft runout, ISO/IEC 17025 metallurgical lab",
                        "4 weeks",
                    ),
                    (
                        "4 RCA and options",
                        "Cause tree, ranked repair options, procedure",
                        "2 weeks",
                    ),
                ),
            ),
            Heading("3. Team"),
            Bullets(
                (
                    "Project lead: rotating equipment engineer, 18 years, ISO 18436-2 Cat IV.",
                    "Field engineer: laser alignment specialist, ISO 18436-2 Cat III.",
                    "Metallurgist: chartered engineer, failure analysis lab manager.",
                    "CVs and two references for similar caisson pump RCAs are in Annex A.",
                )
            ),
            Heading("4. Schedule"),
            Paragraph(
                "Final report 10 weeks after award, two weeks inside the 12-week limit. Three "
                "people offshore for 8 days, within the bed space constraint. P-4101B checks "
                "are split into 3-hour windows."
            ),
            Heading("5. Risk and HSE management"),
            Table(
                ("Risk", "Mitigation"),
                (
                    ("P-4101B fails during survey", "Survey P-4101B first, at low load"),
                    ("Weather delays offshore", "Two spare days built into phase 2"),
                    ("Parts damaged in transport", "Sealed, labelled transport; photo record"),
                ),
            ),
            Paragraph(
                "Full offshore HSE plan in Annex B. All site staff hold valid offshore "
                "survival certificates."
            ),
            Heading("6. Cost"),
            Table(
                ("Item", "Cost (USD)"),
                (
                    ("Phase 1", "8,000"),
                    ("Phase 2 (offshore)", "41,000"),
                    ("Phase 3 (teardown and lab)", "27,000"),
                    ("Phase 4 (report)", "12,000"),
                    ("Total", "88,000"),
                ),
            ),
            Heading("7. Compliance matrix"),
            Table(
                ("Requirement", "Compliant", "Where"),
                (
                    ("M1 HSE plan and certificates", "Yes", "Section 5, Annex B"),
                    ("M2 Accredited metallurgical lab", "Yes", "Section 2, phase 3"),
                    ("M3 Report within 12 weeks", "Yes", "Section 4"),
                    ("M4 Data stays on operator systems", "Yes", "Annex C data plan"),
                    ("M5 Compliance matrix", "Yes", "This section"),
                ),
            ),
        ),
    )


def _proposal_middling() -> FixtureDocument:
    return FixtureDocument(
        id="prop-02",
        file="synthetic/proposal_coastline_engineering.docx",
        title="Proposal for RFP-01 - Coastline Engineering Services (fictional)",
        author="Coastline Engineering Services, Sales",
        issued_on=date(2026, 10, 27),
        node="region_south_operator",
        document_type="proposal",
        confidentiality="confidential",
        related_issues=(PUMP_FAILURE,),
        blocks=(
            Heading("1. Understanding"),
            Paragraph(
                "The P-4101A pump on SP-12 has tripped several times on vibration. We believe "
                "the likely cause is misalignment after the motor change."
            ),
            Heading("2. Approach"),
            Bullets(
                (
                    "Offshore vibration survey and laser alignment of P-4101A.",
                    "Teardown of P-4101A in our workshop with visual inspection of bearings.",
                    "RCA report with recommendations.",
                )
            ),
            Paragraph(
                "Metallurgical analysis is not included. It can be added later as a variation "
                "if visual inspection is not conclusive."
            ),
            Heading("3. Team"),
            Paragraph("A senior pump engineer and a technician. CVs available on request."),
            Heading("4. Schedule"),
            Paragraph("About 3 months, depending on offshore logistics."),
            Heading("5. Cost"),
            Paragraph("Lump sum USD 54,000, excluding any lab work."),
            Heading("6. HSE"),
            Paragraph(
                "Our standard offshore HSE plan applies. Staff certificates will be provided "
                "before mobilisation."
            ),
        ),
    )


def _proposal_weak() -> FixtureDocument:
    return FixtureDocument(
        id="prop-03",
        file="synthetic/proposal_quickfix_pump_services.docx",
        title="Proposal for RFP-01 - QuickFix Pump Services (fictional)",
        author="QuickFix Pump Services",
        issued_on=date(2026, 10, 30),
        node="region_south_operator",
        document_type="proposal",
        confidentiality="confidential",
        related_issues=(PUMP_FAILURE,),
        blocks=(
            Heading("Proposal"),
            Paragraph(
                "Thank you for your enquiry. Pumps that trip repeatedly are usually worn out. "
                "We propose to supply and install a new pump and motor set to replace P-4101A. "
                "This is faster and cheaper than a long study."
            ),
            Paragraph(
                "We can also upload your vibration data to our cloud analytics portal for a "
                "free health check."
            ),
            Heading("Price"),
            Paragraph("USD 120,000 for the new pump set, installation extra."),
            Heading("Delivery"),
            Paragraph("Lead time to be confirmed by the factory."),
        ),
    )


def _legacy_pump_overhaul_report() -> FixtureDocument:
    return FixtureDocument(
        id="legacy-01",
        file="cases/legacy_sp14_pump_overhaul_completion_2019.doc",
        title="Work Order Completion Report - P-4101B Overhaul, Platform SP-14",
        author="SP-14 Maintenance Supervisor",
        issued_on=date(2019, 9, 2),
        node="region_south_archive",
        document_type="maintenance_record",
        confidentiality="internal",
        related_issues=(PUMP_FAILURE,),
        blocks=(
            Heading("Work done"),
            Bullets(
                (
                    "Pump pulled, line shaft bearings replaced (sand-tolerant grade).",
                    "Motor base re-shimmed, soft foot reduced from 0.25 mm to 0.02 mm.",
                    "Laser alignment: final parallel offset 0.03 mm, angularity 0.02 mm/100 mm.",
                    "Intake screen replaced.",
                )
            ),
            Heading("Test run"),
            Table(
                ("Parameter", "Before", "After"),
                (
                    ("Vibration, motor NDE (mm/s)", "9.6", "2.1"),
                    ("DE bearing temperature (deg C)", "88", "61"),
                    ("Discharge pressure (barg)", "7.8", "8.4"),
                ),
            ),
        ),
    )


def _legacy_riser_inspection_procedure() -> FixtureDocument:
    return FixtureDocument(
        id="legacy-02",
        file="cases/legacy_riser_ut_inspection_procedure_2017.doc",
        title="Procedure RS-INT-014 - Ultrasonic Thickness Inspection of Risers",
        author="Region South Integrity Group",
        issued_on=date(2017, 3, 1),
        node="region_south_archive",
        document_type="procedure",
        confidentiality="internal",
        related_issues=(RISER_CORROSION,),
        blocks=(
            Heading("1. Purpose"),
            Paragraph(
                "Defines how to measure riser wall thickness with ultrasonic testing so that "
                "results from different campaigns can be compared."
            ),
            Heading("2. Requirements"),
            Bullets(
                (
                    "Record each reading with elevation (EL, metres) and clock position "
                    "viewed from above, 12 o'clock = platform north.",
                    "Use the same probe type and calibration block in every campaign.",
                    "Take at least four clock positions per elevation in the splash zone.",
                    "Report any reading below 85% of nominal wall to the corrosion engineer "
                    "within 24 hours.",
                )
            ),
            Heading("3. Survey interval"),
            Paragraph(
                "Every 3 years in normal conditions; every 2 years or less where wall loss "
                "exceeds 10% of nominal."
            ),
        ),
    )


def _scanned_riser_baseline() -> FixtureDocument:
    return FixtureDocument(
        id="scan-01",
        file="cases/scanned_sp12_riser_r3_baseline_2021.pdf",
        title="Riser R-3 Baseline UT Readings - Platform SP-12 (2021, scanned)",
        author="Reza Kamali, CP Engineer",
        issued_on=date(2021, 6, 14),
        node="sp12_inspection_team",
        document_type="inspection_report",
        confidentiality="internal",
        related_issues=(RISER_CORROSION,),
        is_scanned=True,
        blocks=(
            Heading("Baseline readings"),
            Paragraph(
                "Field sheet transcribed from the 2021 campaign. Clock positions use the old "
                "convention (12 o'clock = riser guide), so 3 and 9 o'clock are swapped "
                "compared with later surveys."
            ),
            Table(
                UT_HEADER,
                (
                    ("R-3 EL +12.0 m, 12 o'clock", "22.2", "22.0", "2021-06-10", "R. Kamali"),
                    ("R-3 EL +8.5 m, 9 o'clock", "22.2", "21.2", "2021-06-10", "R. Kamali"),
                    ("R-3 EL +8.5 m, 6 o'clock", "22.2", "21.0", "2021-06-10", "R. Kamali"),
                    ("R-3 EL +5.0 m, 6 o'clock", "22.2", "21.5", "2021-06-11", "R. Kamali"),
                    ("R-3 EL +2.0 m, 6 o'clock", "22.2", "22.0", "2021-06-11", "R. Kamali"),
                ),
            ),
            Paragraph(
                "Coating in good condition apart from light rust staining at EL +8.5 m. "
                "CP potentials -0.98 V vs Ag/AgCl below the water line."
            ),
        ),
    )


def _write_docx(document: FixtureDocument, path: Path) -> None:
    word = Document()
    word.core_properties.title = document.title
    word.core_properties.author = document.author
    word.core_properties.last_modified_by = document.author
    word.core_properties.comments = FICTION_NOTICE
    word.core_properties.revision = document.version
    issued_at = datetime(document.issued_on.year, document.issued_on.month, document.issued_on.day)
    word.core_properties.created = issued_at
    word.core_properties.modified = issued_at
    word.sections[0].header.paragraphs[0].text = FICTION_NOTICE

    word.add_heading(document.title, level=0)
    for block in _all_blocks(document):
        match block:
            case Heading(text, level):
                word.add_heading(text, level=level)
            case Paragraph(text):
                word.add_paragraph(text)
            case Bullets(items):
                for item in items:
                    word.add_paragraph(item, style="List Bullet")
            case Table(header, rows):
                table = word.add_table(rows=1, cols=len(header))
                table.style = "Table Grid"
                for cell, text in zip(table.rows[0].cells, header, strict=True):
                    cell.text = ""
                    run = cell.paragraphs[0].add_run(text)
                    run.bold = True
                    run.font.size = Pt(10)
                for row in rows:
                    for cell, text in zip(table.add_row().cells, row, strict=True):
                        cell.text = text
                word.add_paragraph()
    word.save(str(path))
    _normalize_zip_timestamps(path)


def _normalize_zip_timestamps(path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(buffer, "w") as target:
        for entry in source.infolist():
            fixed_entry = zipfile.ZipInfo(entry.filename, date_time=FIXED_ZIP_TIMESTAMP)
            fixed_entry.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(fixed_entry, source.read(entry.filename))
    path.write_bytes(buffer.getvalue())


def _column_widths(table: Table, total_width: float) -> list[float]:
    # Width follows the longest text in each column, so short columns like dates stay narrow.
    longest = [
        max(len(row[index]) for row in (table.header, *table.rows))
        for index in range(len(table.header))
    ]
    weights = [min(max(length, 6), 45) for length in longest]
    return [total_width * weight / sum(weights) for weight in weights]


def _write_pdf(document: FixtureDocument, path: Path) -> None:
    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle("cell", parent=styles["BodyText"], fontSize=9, leading=11)
    header_style = ParagraphStyle("header", parent=cell_style, fontName="Helvetica-Bold")
    margin = 20 * mm
    usable_width = A4[0] - 2 * margin
    story: list[object] = [PdfParagraph(document.title, styles["Title"])]
    for block in _all_blocks(document):
        match block:
            case Heading(text, level):
                story.append(PdfParagraph(text, styles[f"Heading{min(level + 1, 4)}"]))
            case Paragraph(text):
                story.append(PdfParagraph(text, styles["BodyText"]))
            case Bullets(items):
                story.append(
                    ListFlowable(
                        [ListItem(PdfParagraph(item, styles["BodyText"])) for item in items],
                        bulletType="bullet",
                    )
                )
            case Table(header, rows):
                cells = [[PdfParagraph(text, header_style) for text in header]]
                cells += [[PdfParagraph(text, cell_style) for text in row] for row in rows]
                pdf_table = PdfTable(
                    cells, colWidths=_column_widths(block, usable_width), repeatRows=1
                )
                pdf_table.setStyle(
                    PdfTableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ]
                    )
                )
                story += [pdf_table, Spacer(1, 6)]

    def draw_footer(canvas: Canvas, _template: object) -> None:
        canvas.setFont("Helvetica-Oblique", 8)
        canvas.drawString(margin, 10 * mm, FICTION_NOTICE)

    # invariant=1 drops the creation timestamp and random file ID, so output is reproducible.
    SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        title=document.title,
        author=document.author,
        subject=FICTION_NOTICE,
        invariant=1,
    ).build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width_px: float
) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= width_px:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _write_scanned_pdf(document: FixtureDocument, path: Path) -> None:
    """Render the document as a single page image, so the PDF has no text layer."""
    dots_per_inch = 120
    page_width, page_height = int(8.27 * dots_per_inch), int(11.69 * dots_per_inch)
    margin = 80
    usable_width = page_width - 2 * margin
    page = Image.new("L", (page_width, page_height), color=246)
    draw = ImageDraw.Draw(page)
    title_font = ImageFont.load_default(size=26)
    heading_font = ImageFont.load_default(size=21)
    body_font = ImageFont.load_default(size=16)
    cell_font = ImageFont.load_default(size=14)
    cursor_y = margin

    for line in _wrap_text(draw, document.title, title_font, usable_width):
        draw.text((margin, cursor_y), line, fill=20, font=title_font)
        cursor_y += 34
    cursor_y += 12

    for block in _all_blocks(document):
        match block:
            case Heading(text, _level):
                draw.text((margin, cursor_y), text, fill=25, font=heading_font)
                cursor_y += 34
            case Paragraph(text):
                for line in _wrap_text(draw, text, body_font, usable_width):
                    draw.text((margin, cursor_y), line, fill=35, font=body_font)
                    cursor_y += 22
                cursor_y += 12
            case Bullets(items):
                for item in items:
                    for line in _wrap_text(draw, "- " + item, body_font, usable_width):
                        draw.text((margin, cursor_y), line, fill=35, font=body_font)
                        cursor_y += 22
            case Table(header, rows):
                widths = _column_widths(block, usable_width)
                for row_index, row in enumerate((header, *rows)):
                    wrapped = [
                        _wrap_text(draw, text, cell_font, width - 10)
                        for text, width in zip(row, widths, strict=True)
                    ]
                    row_height = 18 * max(len(lines) for lines in wrapped) + 10
                    cell_x = float(margin)
                    for lines, width in zip(wrapped, widths, strict=True):
                        draw.rectangle(
                            (cell_x, cursor_y, cell_x + width, cursor_y + row_height),
                            outline=60,
                            width=2 if row_index == 0 else 1,
                        )
                        for line_index, line in enumerate(lines):
                            draw.text(
                                (cell_x + 5, cursor_y + 5 + 18 * line_index),
                                line,
                                fill=30,
                                font=cell_font,
                            )
                        cell_x += width
                    cursor_y += row_height
                cursor_y += 16

    draw.text((margin, page_height - 50), FICTION_NOTICE, fill=90, font=cell_font)
    # Seeded speckle and a small skew make it look scanned while staying reproducible.
    speckles = random.Random(document.id)
    for _ in range(2500):
        x, y = speckles.randrange(page_width), speckles.randrange(page_height)
        draw.point((x, y), fill=speckles.randrange(150, 230))
    scanned = page.rotate(0.7, resample=Image.Resampling.BICUBIC, fillcolor=246)
    issued_at = datetime(document.issued_on.year, document.issued_on.month, document.issued_on.day)
    scanned.save(
        path,
        "PDF",
        resolution=dots_per_inch,
        title=document.title,
        creationDate=issued_at.timetuple(),
        modDate=issued_at.timetuple(),
    )


def _find_soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def _write_legacy_doc(document: FixtureDocument, path: Path, soffice: str) -> None:
    with tempfile.TemporaryDirectory() as workspace:
        workspace_dir = Path(workspace)
        docx_path = workspace_dir / (path.stem + ".docx")
        _write_docx(document, docx_path)
        # A private profile lets this run while the user has LibreOffice open.
        profile_uri = (workspace_dir / "profile").as_uri()
        subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={profile_uri}",
                "--headless",
                "--convert-to",
                "doc:MS Word 97",
                "--outdir",
                str(workspace_dir),
                str(docx_path),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        shutil.move(workspace_dir / (path.stem + ".doc"), path)


def _render(document: FixtureDocument, soffice: str | None) -> None:
    path = FIXTURES_DIR / document.file
    path.parent.mkdir(parents=True, exist_ok=True)
    if document.is_scanned:
        _write_scanned_pdf(document, path)
    elif document.file_format == "docx":
        _write_docx(document, path)
    elif document.file_format == "pdf":
        _write_pdf(document, path)
    elif soffice is not None:
        _write_legacy_doc(document, path, soffice)


def _manifest_row(document: FixtureDocument, *, row_id: str, file: str, duplicate_of: str) -> dict:
    return {
        "id": row_id,
        "file": file,
        "format": Path(file).suffix.lstrip("."),
        "origin": "synthetic",
        "node": document.node,
        "layer": str(NODE_LAYERS[document.node]),
        "document_type": document.document_type,
        "confidentiality": document.confidentiality,
        "version": str(document.version),
        "previous_version_id": document.previous_version_id,
        "duplicate_of": duplicate_of,
        "related_issue": ";".join(document.related_issues),
        "source_url": "",
        "license": "",
    }


def _existing_public_rows() -> list[dict]:
    if not MANIFEST_PATH.is_file():
        return []
    with MANIFEST_PATH.open(newline="", encoding="utf-8") as manifest:
        return [row for row in csv.DictReader(manifest) if row["origin"] == "public"]


def _all_documents() -> list[FixtureDocument]:
    inspection_2024 = _inspection_riser_2024()
    format_duplicate = replace(
        inspection_2024,
        id="ins-01-pdf",
        file="cases/inspection_sp12_riser_r3_2024.pdf",
        duplicate_of=inspection_2024.id,
    )
    return [
        inspection_2024,
        _inspection_riser_2026_v1(),
        _inspection_firewater_caisson(),
        *_shift_reports(),
        *_personnel_profiles(),
        _project_report_riser(),
        _project_report_pump(),
        _issue_resolution_sp14_pump(),
        *_node_descriptions(),
        _rfp_pump_failure_analysis(),
        _proposal_strong(),
        _proposal_middling(),
        _proposal_weak(),
        format_duplicate,
        _inspection_riser_2026_v2(),
        _shift_report_with_copied_paragraph(),
        _legacy_pump_overhaul_report(),
        _legacy_riser_inspection_procedure(),
        _scanned_riser_baseline(),
    ]


EXACT_COPIES = (
    ExactCopy(id="prof-01-copy", file="cases/cv_moradi_final.docx", source_id="prof-01"),
)


def main() -> int:
    """Regenerate synthetic/ and cases/, then rewrite the manifest."""
    for folder in ("synthetic", "cases"):
        shutil.rmtree(FIXTURES_DIR / folder, ignore_errors=True)

    soffice = _find_soffice()
    documents = _all_documents()
    if soffice is None:
        skipped = [document.file for document in documents if document.file_format == "doc"]
        print(f"warning: soffice not found, skipping {skipped}", file=sys.stderr)
        documents = [document for document in documents if document.file_format != "doc"]
    by_id = {document.id: document for document in documents}
    rows = []
    for document in documents:
        _render(document, soffice)
        rows.append(
            _manifest_row(
                document,
                row_id=document.id,
                file=document.file,
                duplicate_of=document.duplicate_of,
            )
        )
    for copy in EXACT_COPIES:
        source = by_id[copy.source_id]
        shutil.copyfile(FIXTURES_DIR / source.file, FIXTURES_DIR / copy.file)
        rows.append(_manifest_row(source, row_id=copy.id, file=copy.file, duplicate_of=source.id))

    rows += _existing_public_rows()
    with MANIFEST_PATH.open("w", newline="", encoding="utf-8") as manifest:
        writer = csv.DictWriter(manifest, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} manifest rows to {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
