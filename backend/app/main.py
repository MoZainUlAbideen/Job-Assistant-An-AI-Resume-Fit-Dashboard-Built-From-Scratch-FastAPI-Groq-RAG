"""
API layer. This is deliberately thin -- every endpoint just calls into
resume_parser / job_parser / matching_engine and persists the result.
Business logic lives in those modules, not here, so it stays testable
without spinning up a server.
"""
# Must run BEFORE importing resume_parser/job_parser below -- those modules
# instantiate the Anthropic client at import time, which reads
# ANTHROPIC_API_KEY from the environment. A .env file is just a text file;
# nothing loads it automatically -- load_dotenv() is what actually copies
# its contents into this process's environment variables.
from dotenv import load_dotenv
load_dotenv()

import json
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import init_db, get_db, Resume, Job, Application
from app.resume_parser import parse_resume
from app.job_parser import parse_job
from app.matching_engine import match
from app.schemas import ParsedResume, ParsedJob

app = FastAPI(title="Job Search Assistant API")

# Allows the Chrome extension (running on linkedin.com/indeed.com) and the
# dashboard (running on its own origin) to call this API from the browser.
# In production, replace "*" with the extension's actual origin.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.post("/resume/upload")
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    file_bytes = await file.read()
    try:
        parsed: ParsedResume = parse_resume(file_bytes, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    resume_row = Resume(raw_text=parsed.raw_text, parsed_json=parsed.model_dump_json())
    db.add(resume_row)
    db.commit()
    db.refresh(resume_row)
    return {"resume_id": resume_row.id, "parsed": parsed}


class JobCaptureRequest(BaseModel):
    raw_text: str
    source_url: str | None = None


@app.post("/jobs/capture")
def capture_job(payload: JobCaptureRequest, db: Session = Depends(get_db)):
    parsed: ParsedJob = parse_job(payload.raw_text)

    job_row = Job(
        title=parsed.title, company=parsed.company, source_url=payload.source_url,
        raw_text=parsed.raw_text, parsed_json=parsed.model_dump_json(),
    )
    db.add(job_row)
    db.commit()
    db.refresh(job_row)
    return {"job_id": job_row.id, "parsed": parsed}


class MatchRequest(BaseModel):
    resume_id: int
    job_id: int


@app.post("/match/score")
def score_match(payload: MatchRequest, db: Session = Depends(get_db)):
    resume_row = db.get(Resume, payload.resume_id)
    job_row = db.get(Job, payload.job_id)
    if not resume_row or not job_row:
        raise HTTPException(status_code=404, detail="resume_id or job_id not found")

    resume = ParsedResume.model_validate_json(resume_row.parsed_json)
    job = ParsedJob.model_validate_json(job_row.parsed_json)
    result = match(resume, job)

    application = Application(
        job_id=job_row.id, resume_id=resume_row.id,
        fit_score=result.fit_score, match_json=result.model_dump_json(),
        status="captured",
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    return {"application_id": application.id, "result": result}


class BatchJobItem(BaseModel):
    raw_text: str
    source_url: str | None = None


class BatchCaptureRequest(BaseModel):
    resume_id: int
    jobs: list[BatchJobItem]


@app.post("/jobs/capture-batch")
def capture_batch(payload: BatchCaptureRequest, db: Session = Depends(get_db)):
    """
    Takes many raw job postings at once (e.g. every tile visible on a
    LinkedIn/Indeed search results page) and, for each one: parses it,
    scores it against the given resume, and stores an Application row --
    same pipeline as /jobs/capture + /match/score, just looped.

    One bad item shouldn't sink the whole batch -- scraped text from a
    real search results page is messy (ads, promoted listings, truncated
    cards), so each job is parsed independently and failures are reported
    per-item rather than raising for the whole request.
    """
    resume_row = db.get(Resume, payload.resume_id)
    if not resume_row:
        raise HTTPException(status_code=404, detail="resume_id not found")
    resume = ParsedResume.model_validate_json(resume_row.parsed_json)

    results = []
    for item in payload.jobs:
        try:
            parsed_job: ParsedJob = parse_job(item.raw_text)
            job_row = Job(
                title=parsed_job.title, company=parsed_job.company, source_url=item.source_url,
                raw_text=parsed_job.raw_text, parsed_json=parsed_job.model_dump_json(),
            )
            db.add(job_row)
            db.commit()
            db.refresh(job_row)

            match_result = match(resume, parsed_job)
            application = Application(
                job_id=job_row.id, resume_id=resume_row.id,
                fit_score=match_result.fit_score, match_json=match_result.model_dump_json(),
                status="captured",
            )
            db.add(application)
            db.commit()
            db.refresh(application)

            results.append({
                "ok": True,
                "application_id": application.id,
                "job_title": parsed_job.title,
                "company": parsed_job.company,
                "fit_score": match_result.fit_score,
            })
        except Exception as e:
            db.rollback()
            results.append({"ok": False, "error": str(e), "source_url": item.source_url})

    return {"processed": len(payload.jobs), "results": results}


@app.get("/applications")
def list_applications(db: Session = Depends(get_db)):
    apps = db.query(Application).order_by(Application.created_at.desc()).all()
    out = []
    for a in apps:
        job = db.get(Job, a.job_id)
        out.append({
            "application_id": a.id,
            "job_title": job.title if job else None,
            "company": job.company if job else None,
            "fit_score": a.fit_score,
            "status": a.status,
            "created_at": a.created_at.isoformat(),
        })
    return out


class StatusUpdate(BaseModel):
    status: str  # "captured" | "applied" | "interviewing" | "rejected" | "offer"


@app.patch("/applications/{application_id}/status")
def update_status(application_id: int, payload: StatusUpdate, db: Session = Depends(get_db)):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="application not found")
    application.status = payload.status
    db.commit()
    return {"application_id": application_id, "status": application.status}


# Mounted LAST and after every API route above, so it only catches requests
# that don't match an /resume, /jobs, /match, or /applications path -- the
# dashboard becomes the catch-all UI at the root of the running server.
app.mount("/", StaticFiles(directory="static", html=True), name="dashboard")
