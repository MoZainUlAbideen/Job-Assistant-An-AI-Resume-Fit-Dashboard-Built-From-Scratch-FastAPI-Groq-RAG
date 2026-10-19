"""Extraction + parseability checks on real generated files."""
from app.extract import extract
from app.format_checks import run_checks
from app.resume_parser import parse_resume
from tests.conftest import make_docx, make_pdf


def checks_for(data, name):
    doc = extract(data, name)
    return doc, {c.id: c.status for c in run_checks(doc, parse_resume(doc.text))}


def test_clean_docx_passes():
    doc, c = checks_for(make_docx(), "r.docx")
    assert "Built a document classification service" in doc.text
    assert c["email"] == "pass" and c["tables"] == "pass" and c["section_experience"] == "pass"


def test_docx_contact_only_in_header_fails():
    _, c = checks_for(make_docx(contact_in_header=True), "r.docx")
    assert c["header_contact"] == "fail" and c["email"] == "fail"


def test_docx_big_table_warns():
    _, c = checks_for(make_docx(table=True), "r.docx")
    assert c["tables"] == "warn"


def test_single_column_pdf():
    doc, c = checks_for(make_pdf(), "r.pdf")
    assert doc.file_type == "pdf" and c["columns"] == "pass"
    assert parse_resume(doc.text).email == "ayesha.khan@example.com"


def test_two_column_pdf_warns():
    _, c = checks_for(make_pdf(two_column=True), "r.pdf")
    assert c["columns"] == "warn"


def test_cid_glyphs_flagged_and_bullets_recovered():
    from app.extract import Extracted, _clean
    raw = "Experience\nML Engineer | X  2020 - 2022\n(cid:127) Built models in PyTorch for clients.\n" * 3
    cleaned = _clean(raw)
    assert "(cid:" not in cleaned and cleaned.count("• Built") == 3
    doc = Extracted(text=cleaned, file_type="pdf", cid_glyphs=3)
    c = {x.id: x.status for x in run_checks(doc, parse_resume(cleaned * 20))}
    assert c["glyphs"] == "warn"


def test_bad_files_rejected():
    import pytest
    with pytest.raises(ValueError):
        extract(b"not a pdf", "r.pdf")
    with pytest.raises(ValueError):
        extract(b"x", "r.png")
    with pytest.raises(ValueError):
        extract(b"x" * (5 * 1024 * 1024 + 1), "r.txt")
