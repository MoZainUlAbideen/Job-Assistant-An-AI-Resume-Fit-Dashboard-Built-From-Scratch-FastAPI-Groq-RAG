"""
Parseability checks -- the stuff that makes an ATS mangle a resume before any
keyword matching even happens. Each check is pass / warn / fail with a plain
explanation and a concrete fix.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.extract import Extracted
from app.resume_parser import EMAIL_RE, PHONE_RE, ParsedResume

WEAK_OPENERS = ("utilized", "worked on", "responsible for", "helped", "assisted", "was involved",
                "participated in", "tasked with", "duties included", "handled")


@dataclass
class Check:
    id: str
    label: str
    status: str      # "pass" | "warn" | "fail"
    detail: str


def run_checks(doc: Extracted, r: ParsedResume) -> list[Check]:
    c: list[Check] = []
    words = len(r.raw_text.split())

    if len(r.raw_text.strip()) < 200:
        c.append(Check("text_layer", "Text is machine-readable", "fail",
                       "Almost no text could be extracted — this looks like a scanned/image PDF. "
                       "An ATS will see an empty resume. Export from Word/Google Docs instead of scanning."))
        return c
    c.append(Check("text_layer", "Text is machine-readable", "pass", f"{words} words extracted."))

    if doc.cid_glyphs:
        c.append(Check("glyphs", "Characters map to real text", "warn",
                       f"{doc.cid_glyphs} characters came out as '(cid:NN)' codes — usually custom bullet symbols "
                       "or icon fonts. Many ATS show these as garbage. Use plain '•' bullets and a standard font."))
    else:
        c.append(Check("glyphs", "Characters map to real text", "pass", "No unmapped glyphs found."))

    if doc.multi_column_pages:
        c.append(Check("columns", "Single-column layout", "warn",
                       "Looks like a multi-column layout. ATS parsers often read straight across columns, "
                       "mixing sections together. A single column is safest."))
    elif doc.file_type == "pdf":
        c.append(Check("columns", "Single-column layout", "pass", "Reading order looks linear."))

    if doc.file_type == "docx":
        if doc.has_tables and doc.table_text_chars > 0.15 * max(len(r.raw_text), 1):
            c.append(Check("tables", "No layout tables", "warn",
                           "A significant part of the resume is inside tables. Some ATS skip or scramble table "
                           "cells — move that content into normal paragraphs."))
        else:
            c.append(Check("tables", "No layout tables", "pass", "Content isn't locked in tables."))
        if doc.has_text_boxes:
            c.append(Check("textboxes", "No text boxes", "fail",
                           "Text boxes found. Most ATS ignore text inside them entirely."))
        hf = doc.header_footer_text
        if hf and (EMAIL_RE.search(hf) or PHONE_RE.search(hf)) and not EMAIL_RE.search(r.raw_text):
            c.append(Check("header_contact", "Contact info in the body", "fail",
                           "Your contact details are only in the page header/footer, which many ATS don't read. "
                           "Put them in the first lines of the document body."))

    c.append(Check("email", "Email address", "pass" if r.email else "fail",
                   "Found." if r.email else "No email address found in the resume body."))
    c.append(Check("phone", "Phone number", "pass" if r.phone else "warn",
                   "Found." if r.phone else "No phone number found."))
    c.append(Check("linkedin", "LinkedIn profile", "pass" if r.has_linkedin else "warn",
                   "Found." if r.has_linkedin else "Recruiters expect a LinkedIn URL."))

    has_exp = "experience" in r.section_order
    has_proj = "projects" in r.section_order
    for sec, label in (("education", "Education"), ("skills", "Skills")):
        ok = sec in r.section_order
        c.append(Check(f"section_{sec}", f"'{label}' section heading", "pass" if ok else "warn",
                       "Found." if ok else f"No standard '{label}' heading detected. ATS map content by headings "
                                           f"— use a plain heading like '{label}'."))
    c.append(Check("section_experience", "'Experience' section heading",
                   "pass" if has_exp else ("warn" if has_proj else "fail"),
                   "Found." if has_exp else "No 'Experience' heading detected — ATS rely on it to find your work "
                                            "history (use 'Experience' or 'Work Experience')."))

    if words < 250:
        c.append(Check("length", "Length", "warn", f"Only {words} words — thin for keyword matching."))
    elif words > 1100 or doc.page_count > 2:
        c.append(Check("length", "Length", "warn",
                       f"{words} words / {doc.page_count} pages — long. Keep it to 1–2 pages."))
    else:
        c.append(Check("length", "Length", "pass", f"{words} words, {doc.page_count} page(s)."))

    if doc.file_type == "txt":
        c.append(Check("filetype", "File type", "warn",
                       "Plain text can't be layout-checked. Upload the PDF/DOCX you actually send."))
    return c


def format_score(checks: list[Check]) -> float:
    pen = sum(25 if ch.status == "fail" else 7 if ch.status == "warn" else 0 for ch in checks)
    return max(0.0, 100.0 - pen)


def writing_tips(r: ParsedResume) -> dict:
    """Not scored (an ATS doesn't care), but this is what a human reader notices next."""
    work = [b for b in r.bullets if b.section in ("experience", "projects")]
    if not work:
        return {"bullets": 0, "quantified": 0, "weak_openers": []}
    quantified = [b for b in work if re.search(r"\d", b.text)]
    weak = [b.text for b in work if b.text.lower().startswith(WEAK_OPENERS)]
    return {"bullets": len(work), "quantified": len(quantified), "weak_openers": weak[:6]}
