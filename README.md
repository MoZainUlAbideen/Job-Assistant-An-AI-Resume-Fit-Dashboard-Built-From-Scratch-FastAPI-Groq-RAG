# Job Assistant: ATS resume checker with honest tailoring

Upload a resume, paste a job description, and see what an applicant tracking system (ATS) sees: a match score, which of the job's keywords you have, anything that could filter you out automatically, and layout problems that make resumes unreadable to ATS software. Then generate a tailored `.docx` whose edits are **checked in code so they never invent experience**.

- **Backend:** FastAPI on Render (`backend/`)
- **Frontend:** static HTML/CSS/JS on Vercel (`frontend/`)

## Why v2 exists: an audit of v1

v1 (June 2026) used an LLM to pull skills out of every resume and job, and embedding similarity to match them. Its own saved database (24 scans of 8 jobs, 3 scans each) showed:

| Problem in v1 | Evidence | v2 fix |
|---|---|---|
| Scores changed between rescans of the same job | Same posting scored 0 → 0 → 33 and 60 → 40 → 50 | Fixed skill dictionary + rule-based scoring. **Spread over repeated scans: 0 points** |
| Skills you have marked "missing" | "Deep Learning" and "LLMs" missing for a resume listing PyTorch, TensorFlow, LangChain, Groq | Exact aliases plus "related skills" evidence (PyTorch → Deep Learning) |
| Resume parser dropped whole sections | LLM parse kept 7 bullets and lost the Projects section | Rule-based section/bullet parser: 21/21 bullets |
| Substring matching | `"r" in "pytorch"`, `"java" in "javascript"` | Token-boundary regex; ambiguous words ("Go", "R", "React", "CV") only in safe contexts |
| Rewrites invented experience | *"…leveraging AI agents in a cloud-based environment"*, *"implying autonomous or agent-like capabilities"* | Every rewrite verified in code; **all 25 of v1's distinct rewrites are rejected** by the v2 verifier |
| Not an ATS check | Only skills; no title, years, degree or file-format checks | Title, years of experience, degree, and parseability checks (tables, columns, header contact info, unmapped glyphs) |
| Model retired | `llama-3.3-70b-versatile` was shut down by Groq on 2026-08-16 | `openai/gpt-oss-120b` by default, set with `GROQ_MODEL` |
| Too heavy for free hosting | PyTorch + sentence-transformers | ~85 MB RAM at runtime |

## How it works

```
resume (.pdf/.docx/.txt) ─► extract.py ─► resume_parser.py ─┐
                              │ layout signals              ├─► scoring.py ─► report (deterministic)
job description ─────────────────────────► jd_parser.py ────┘                    │
                                                                                 ▼
                                    tailor.py: LLM proposes bullet rewrites ─► verify_edit() ─► docx_out.py
                                               (Groq, temperature 0)           (rules in code)   re-scored
```

**Score** (renormalized over the parts that apply to a job):

| part | weight | notes |
|---|---|---|
| keywords | 60 | required 1.0, preferred 0.5, soft skills 0.25/0.1; a related-skills match gets 0.4 credit |
| job title | 10 | |
| years of experience | 15 | |
| degree | 5 | |
| format | 10 | |

The job description parser groups alternatives ("PyTorch **or** TensorFlow", "AWS, GCP, or Azure"), separates required from preferred by section and by cue words ("a plus", "preferred"), and ignores boilerplate (About us, Benefits, EEO).

**Tailoring rules.** A JD keyword is added to Skills only if the resume already shows evidence for it. LLM bullet rewrites are rejected if they:
- add a skill the role or project doesn't show
- add any new number
- add new proper nouns or tools
- use filler ("implying", "expertise")
- change too much of the original
- add no keyword

Blocked rewrites are shown in the UI with the reason.

## Evaluation

`uv run python eval/run_eval.py` (no API key needed). Full output: [`backend/eval/results/latest.md`](backend/eval/results/latest.md).

| | dev set (6 postings) | held-out (4 postings) |
|---|---|---|
| keyword precision | 98% | 100% |
| keyword recall | 97% | 78% (first run) |
| required vs preferred | 98% | 98% |
| years / degree | 100% / 100% | 100% / 75% → 100% after one bug fix |

- **Rewrite verifier:** 12/12 fabricated, filler or pointless rewrites blocked; 7/8 honest rewrites accepted. The one honest rewrite it blocked: "SQL pipelines" → "data pipelines" is judged too much of a stretch for "Data Engineering".
- **Known gaps:** held-out recall is 78% because the skill dictionary doesn't cover everything (ROS, SLAM, segmentation, Jetson, domain knowledge like payments). Skills in parentheses ("Python (Pandas)") are treated as alternatives, which is lenient. The dev set was used to fix bugs, so its numbers are optimistic; the held-out column is the honest one.
- **Live LLM eval** (needs your key): `uv run python eval/run_llm_eval.py` reports proposal, acceptance and block rates per posting, and prints every accepted rewrite next to its original for human review.

## Run locally

```bash
cd backend
uv sync                         # installs deps from uv.lock
cp .env.example .env            # paste your GROQ_API_KEY
uv run uvicorn app.main:app --reload --port 8000
uv run pytest                   # 45 tests
```

Frontend: serve `frontend/` with anything static, for example `cd frontend && python -m http.server 5500`, then open http://localhost:5500. `config.js` points to `localhost:8000` automatically when run locally.

## Deploy

1. **Render (API):** Dashboard → New → Blueprint → select this repo (it reads `render.yaml`). Set `GROQ_API_KEY`, and set `ALLOWED_ORIGINS` to your Vercel URL. Health check: `/api/health`.
2. **Vercel (frontend):** New Project → import this repo → Root Directory `frontend` → Framework preset "Other" → Deploy. Put your Render URL in `frontend/config.js` first.

The free Render tier sleeps when idle, so the first request takes up to a minute; the UI says so. Nothing is stored: the API is stateless, and per-IP rate limits protect your Groq quota.

## License

MIT
