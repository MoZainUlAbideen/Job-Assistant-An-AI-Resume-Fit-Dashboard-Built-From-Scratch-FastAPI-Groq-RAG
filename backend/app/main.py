"""
HTTP API (deployed on Render). Stateless on purpose: nothing is stored --
the resume and JD live only for the duration of the request. That means no
database to lose on Render's ephemeral disk, and no one's resume sitting on
a server (v1 committed a SQLite DB with a real resume in it to GitHub).

Endpoints
  GET  /api/health   -> liveness + whether the LLM is configured
  POST /api/scan     -> ATS report (deterministic, no LLM)
  POST /api/tailor   -> grounded edits + before/after score + tailored .docx (base64)
"""
from __future__ import annotations

import base64
import logging
import os
import re

from dotenv import load_dotenv

load_dotenv(override=True)   # .env wins over a stale GROQ_API_KEY set in Windows env vars

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app import llm  # noqa: E402
from app.docx_out import build_docx, edit_docx  # noqa: E402
from app.extract import MAX_BYTES, extract  # noqa: E402
from app.jd_parser import parse_jd  # noqa: E402
from app.ratelimit import RateLimiter  # noqa: E402
from app.resume_parser import parse_resume  # noqa: E402
from app.scoring import score  # noqa: E402
from app.skills import find_skills  # noqa: E402
from app.tailor import tailor  # noqa: E402

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Job Assistant API", version="2.0.0")

origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])

scan_limiter = RateLimiter(per_minute=int(os.getenv("SCAN_PER_MINUTE", "30")),
                           per_day=int(os.getenv("SCAN_PER_DAY", "500")))
tailor_limiter = RateLimiter(per_minute=int(os.getenv("TAILOR_PER_MINUTE", "4")),
                             per_day=int(os.getenv("TAILOR_PER_DAY", "40")))

JD_MIN, JD_MAX = 80, 20_000


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


async def _load(resume: UploadFile, jd_text: str, job_title: str | None):
    jd_text = (jd_text or "").strip()
    if len(jd_text) < JD_MIN:
        raise HTTPException(400, "Paste the full job description (it looks too short).")
    if len(jd_text) > JD_MAX:
        raise HTTPException(400, "Job description is too long (20,000 characters max).")
    data = await resume.read(MAX_BYTES + 1)
    try:
        doc = extract(data, resume.filename or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    parsed = parse_resume(doc.text)
    jd = parse_jd(jd_text, job_title)
    if not jd.requirements:
        raise HTTPException(422, "No recognisable skills found in that job description. Is it the full posting?")
    return data, doc, parsed, jd


def _resume_summary(parsed) -> dict:
    return {
        "sections": parsed.section_order,
        "bullets": len([b for b in parsed.bullets if b.section in ("experience", "projects")]),
        "skills_found": sorted(find_skills(parsed.raw_text)),
        "experience_years": round(parsed.experience_months / 12, 1),
        "degree": parsed.degree_level,
    }


@app.get("/api/health")
def health():
    return {"ok": True, "llm_configured": llm.available(), "model": llm.model_name()}


@app.post("/api/scan")
async def scan(request: Request, resume: UploadFile = File(...), jd_text: str = Form(...),
               job_title: str | None = Form(None)):
    scan_limiter.check(_client_ip(request))
    _, doc, parsed, jd = await _load(resume, jd_text, job_title)
    rep = score(doc, parsed, jd)
    return {"report": rep.to_dict(), "resume": _resume_summary(parsed)}


@app.post("/api/tailor")
async def tailor_endpoint(request: Request, resume: UploadFile = File(...), jd_text: str = Form(...),
                          job_title: str | None = Form(None)):
    tailor_limiter.check(_client_ip(request))
    data, doc, parsed, jd = await _load(resume, jd_text, job_title)
    before = score(doc, parsed, jd)
    result = tailor(parsed, jd, before)

    accepted = [e for e in result.edits if e.status == "accepted"]
    skills_line = ("Core Competencies: " + ", ".join(s["keyword"] for s in result.skills_added)
                   if result.skills_added else None)
    if doc.file_type == "docx":
        out_bytes = edit_docx(data, accepted, skills_line)
    else:
        out_bytes = build_docx(result.new_text)

    # re-score the file we're actually handing back -- what an ATS would see
    new_doc = extract(out_bytes, "tailored.docx")
    after = score(new_doc, parse_resume(new_doc.text), jd)

    stem = re.sub(r"[^\w\-]+", "_", (resume.filename or "resume").rsplit(".", 1)[0])[:60]
    return {
        "before": before.to_dict(),
        "after": after.to_dict(),
        "tailor": result.to_dict(),
        "docx_base64": base64.b64encode(out_bytes).decode(),
        "filename": f"{stem}_tailored.docx",
    }
