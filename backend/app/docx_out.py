"""
Write the tailored resume as .docx.

  * DOCX in  -> edit the original file in place: only the changed bullet
    paragraphs' text is replaced (paragraph style, bullets/numbering and
    the first run's font are kept), plus one inserted Skills line.
  * PDF/TXT in -> we can't edit a PDF faithfully, so we rebuild a clean,
    single-column, ATS-safe .docx from the tailored text. As a side effect
    this also fixes PDF-only problems like "(cid:127)" bullets.
"""
from __future__ import annotations

import re
from io import BytesIO

import docx
from docx.enum.text import WD_BREAK
from docx.shared import Inches, Pt

from app.resume_parser import BULLET_RE, DATE_RANGE_RE, detect_heading
from app.tailor import Edit


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", BULLET_RE.sub("", s)).strip().lower()


def _set_text(p, text: str) -> None:
    runs = p.runs
    if not runs:
        p.add_run(text)
        return
    # keep the run that holds a manual bullet glyph, if any
    lead = ""
    m = re.match(r"^\s*([•\-\*▪●◦‣∙·–—►➢✓])\s*", p.text)
    if m:
        lead = m.group(0)
    runs[0].text = lead + text
    for r in runs[1:]:
        r.text = ""


def edit_docx(original: bytes, accepted: list[Edit], skills_line: str | None) -> bytes:
    d = docx.Document(BytesIO(original))
    paras = d.paragraphs
    applied = 0
    for e in accepted:
        target = _norm(e.original)
        for p in paras:
            n = _norm(p.text)
            if n and (n == target or (len(n) > 30 and target.startswith(n))):
                _set_text(p, e.rewritten)
                applied += 1
                break
    if skills_line:
        idx = next((i for i, p in enumerate(paras) if detect_heading(p.text) == "skills"), None)
        if idx is not None and idx + 1 < len(paras):
            nxt = paras[idx + 1]
            new_p = nxt.insert_paragraph_before(skills_line, style=nxt.style)
            if nxt.runs and new_p.runs:
                new_p.runs[0].font.size = nxt.runs[0].font.size
                new_p.runs[0].font.name = nxt.runs[0].font.name
        else:
            d.add_paragraph("Skills").runs[0].bold = True
            d.add_paragraph(skills_line)
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


def build_docx(text: str) -> bytes:
    d = docx.Document()
    for s in d.sections:
        s.left_margin = s.right_margin = Inches(0.7)
        s.top_margin = s.bottom_margin = Inches(0.6)
    style = d.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    style.paragraph_format.space_after = Pt(2)

    lines = [l.rstrip() for l in text.splitlines()]
    first = True
    for line in lines:
        if not line.strip():
            continue
        if first:
            p = d.add_paragraph()
            r = p.add_run(line.strip())
            r.bold, r.font.size = True, Pt(16)
            first = False
            continue
        if detect_heading(line):
            p = d.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            r = p.add_run(line.strip().upper())
            r.bold, r.font.size = True, Pt(11.5)
            continue
        if BULLET_RE.match(line):
            d.add_paragraph(BULLET_RE.sub("", line).strip(), style="List Bullet")
            continue
        p = d.add_paragraph()
        r = p.add_run(line.strip())
        if DATE_RANGE_RE.search(line) or re.search(r"\b(?:19|20)\d{2}\s*$", line) \
                or (len(line.split()) <= 12 and ("|" in line or " — " in line) and "@" not in line):
            r.bold = True     # role / company / project header lines
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()
