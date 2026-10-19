"""End-to-end through the HTTP API (LLM faked -- see conftest.fake_llm)."""
import base64

import pytest
from fastapi.testclient import TestClient

from app import main
from app.extract import extract
from tests.conftest import JD_TXT, make_docx, make_pdf


@pytest.fixture
def client(monkeypatch):
    main.scan_limiter.hits.clear()
    main.tailor_limiter.hits.clear()
    return TestClient(main.app)


def post(client, path, data, name, jd=JD_TXT, title=None):
    form = {"jd_text": jd}
    if title:
        form["job_title"] = title
    return client.post(path, files={"resume": (name, data)}, data=form)


def test_health(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = client.get("/api/health").json()
    assert r["ok"] and r["llm_configured"] is False


def test_scan_is_stable_across_formats_and_repeats(client):
    a = post(client, "/api/scan", make_docx(), "r.docx").json()
    b = post(client, "/api/scan", make_docx(), "r.docx").json()
    c = post(client, "/api/scan", make_pdf(), "r.pdf").json()
    assert a["report"]["score"] == b["report"]["score"]          # same input -> same score
    kw = lambda x: {k["keyword"]: k["status"] for k in x["report"]["keywords"]}
    assert kw(a) == kw(c)                                         # PDF and DOCX agree on keywords
    assert a["resume"]["bullets"] == 7


def test_scan_validation(client):
    assert post(client, "/api/scan", make_docx(), "r.docx", jd="too short").status_code == 400
    assert post(client, "/api/scan", b"x", "r.png").status_code == 400
    assert post(client, "/api/scan", make_docx(), "r.docx", jd="We are a lovely company. " * 10).status_code == 422


def test_tailor_without_llm_still_adds_evidenced_skills(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = post(client, "/api/tailor", make_docx(), "r.docx").json()
    added = {s["keyword"] for s in r["tailor"]["skills_added"]}
    assert {"Deep Learning", "LLMs"} <= added
    assert "Kubernetes" in r["tailor"]["gaps"] and "Kubernetes" not in added
    assert r["tailor"]["llm_used"] is False and r["tailor"]["llm_note"]
    assert r["after"]["score"] > r["before"]["score"]


def test_tailor_blocks_fabrication_and_edits_docx_in_place(client, fake_llm):
    r = post(client, "/api/tailor", make_docx(), "ayesha.docx").json()
    edits = r["tailor"]["edits"]
    acc = [e for e in edits if e["status"] == "accepted"]
    rej = {e["rewritten"][:30]: e["reasons"] for e in edits if e["status"] == "rejected"}
    assert len(acc) == 1 and acc[0]["keywords_added"] == ["Deep Learning"]
    assert any("Kubernetes" in " ".join(v) for v in rej.values())
    assert any("implying" in " ".join(v) for v in rej.values())

    out = base64.b64decode(r["docx_base64"])
    text = extract(out, "x.docx").text
    assert "Built a deep learning document classification service" in text
    assert "Kubernetes" not in text and "implying" not in text
    assert "Core Competencies: " in text
    assert r["filename"] == "ayesha_tailored.docx"
    # list style kept on the edited paragraph
    import docx, io
    d = docx.Document(io.BytesIO(out))
    p = next(p for p in d.paragraphs if p.text.startswith("Built a deep learning"))
    assert p.style.name == "List Bullet"
    assert r["after"]["score"] > r["before"]["score"]


def test_tailor_pdf_rebuilds_clean_docx(client, fake_llm):
    r = post(client, "/api/tailor", make_pdf(), "cv.pdf").json()
    text = extract(base64.b64decode(r["docx_base64"]), "x.docx").text
    assert "ayesha.khan@example.com" in text and "Built a deep learning" in text
    assert r["after"]["score"] >= r["before"]["score"]


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main.tailor_limiter, "per_minute", 1)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert post(client, "/api/tailor", make_docx(), "r.docx").status_code == 200
    assert post(client, "/api/tailor", make_docx(), "r.docx").status_code == 429
