# Job Search Assistant — Backend (v1 core)

## What's here

```
app/
  schemas.py          Pydantic data shapes shared across the app
  resume_parser.py     PDF/docx -> raw text -> structured resume (LLM extraction)
  job_parser.py         Raw JD text -> structured job posting (LLM extraction)
  embeddings.py          Local sentence-embedding model + FAISS similarity search
  matching_engine.py    Fit score, skill-gap detection, grounded bullet rewrites
  database.py             SQLite models (Resume, Job, Application) via SQLAlchemy
  main.py                    FastAPI endpoints wiring it all together
static/
  index.html                The dashboard -- served directly by the app, no separate build step
requirements.txt
.env.example
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then paste your real Groq API key in .env (console.groq.com/keys)
export $(cat .env | xargs)        # or use python-dotenv / your OS's env var settings
uvicorn app.main:app --reload
```

First run will download the `all-MiniLM-L6-v2` embedding model (~90MB) from
Hugging Face — needs an internet connection once, then it's cached locally
and every future run is offline for embeddings. (This step was blocked in
the sandbox this was built in, since that environment only allows a fixed
list of domains — it will work normally on your machine.)

## Using it

Once uvicorn is running, open **`http://localhost:8000/`** in your browser
— that's the dashboard (a departure-board-styled tracker: upload your
resume, paste a job description, get a fit score with gap analysis, and
track applications through Captured → Applied → Interviewing → Offer).

`http://localhost:8000/docs` still works separately if you want to test
endpoints directly or debug a specific request.

## API endpoints (v1)

- `POST /resume/upload` — multipart file upload (.pdf or .docx) -> parsed resume
- `POST /jobs/capture` — `{raw_text, source_url}` -> parsed job (this is what the Chrome extension will call)
- `POST /match/score` — `{resume_id, job_id}` -> fit score + gaps + suggested rewrites
- `GET /applications` — list all scored jobs with status
- `PATCH /applications/{id}/status` — update tracker status (applied/interviewing/etc.)

Try it interactively once running: open `http://localhost:8000/docs` (FastAPI
auto-generates a test UI from the code — nothing extra to build for this).

## The theory, in one page (see chat for the fuller version)

**Two-stage parsing.** Extracting text from a file is mechanical (pdfplumber/
python-docx). Turning that text into *structured* data (skills list, discrete
bullets) needs understanding, so that stage uses an LLM prompted to return
strict JSON, which we then validate through Pydantic — never trust raw model
output as if it were already the shape you asked for. (Currently uses
Groq's `llama-3.3-70b-versatile` via JSON mode; swapping providers only
touches the 3 files below, nothing else in the app.)

**Embeddings over keywords.** A JD asking for "distributed systems" should
match a resume bullet about "microservices at scale" even though they share
no words. Embedding models map text to vectors positioned by *meaning*;
cosine similarity (the angle between two vectors) measures how close two
pieces of text are in meaning, independent of exact wording or length.

**FAISS** is just a fast index over many vectors, so "what's the closest
resume bullet to this JD requirement" is a quick lookup instead of an O(n)
loop — the standard pattern regardless of scale.

**Grounded rewrites, not free generation.** An LLM asked to "make this resume
match the job" will happily invent experience the user never had. We instead
give it exactly one real, verbatim resume bullet and one target skill, and
tell it to rephrase using only what's already there — with an explicit
escape hatch (`NO_HONEST_CONNECTION`) if it can't honestly connect the two.
Constraining the input, not just the instructions, is what makes this safe
to ship.

## Verified in this build (see chat for the actual test runs)

- docx/PDF text extraction — ran against a real test file, confirmed correct output
- Pydantic schema + SQLite round-trip — saved and reloaded a parsed resume, fields intact
- FAISS inner-product search ranks by semantic closeness correctly on hand-built vectors
- All modules import and compile cleanly

**Not yet verified** (needs your real Groq API key + internet for the
embedding model download, neither available in the sandbox this was built
in): the actual LLM extraction prompts (`resume_parser.structure_resume`,
`job_parser.parse_job`) and the rewrite generation. Run these against a real
resume/JD as your first step — that's where prompt tuning usually needs a
pass or two.

## Not yet built (next steps)
- Chrome extension (JD capture from LinkedIn/Indeed job pages)
- Dashboard UI (Streamlit, per our plan)
- Auth (fine to skip for a single-user portfolio demo)
