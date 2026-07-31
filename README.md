# JobControl — Resume-Fit Intelligence

An AI-assisted job search tool: upload your resume, capture job postings
(manually or via a bulk-scanning Chrome extension), and get a fit score,
skill-gap analysis, and reasoned advice for each one — plus a
GROQ/LLM-generated tailored resume for roles you're a strong match for.

## Structure

- **`backend/`** — FastAPI app: resume/JD parsing, embedding-based fit
  scoring, resume tailoring, and a built-in dashboard (served at `/`).
  See `backend/README.md` for setup.
- **`extension/`** — Chrome extension that bulk-captures job listings from
  a LinkedIn/Indeed search results page you're actively browsing, and
  sends them to the backend for scoring. See `extension/README.md`.

## Quick start

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # add your Groq API key (console.groq.com/keys)
uvicorn app.main:app --reload
```

Then open `http://localhost:8000/`.

## How it works

1. **Extraction** — resumes and job postings are parsed into structured
   data (skills, experience bullets, requirements) via an LLM prompted for
   strict JSON output.
2. **Matching** — required skills are checked against the resume's skill
   list and, via sentence embeddings + FAISS, against its experience
   bullets — so a JD asking for "distributed systems" can still match a
   bullet about "microservices at scale" even with no shared keywords.
3. **Advice** — a short reasoned narrative on the overall fit and what to
   prioritize, generated from the actual match data (not generic).
4. **Tailoring** — for jobs scoring 50%+, a `.docx` resume is generated
   with JD-relevant skills reordered to the top and any already-vetted
   grounded bullet rewrites applied. It does not invent new experience —
   see `backend/app/resume_tailor.py` for why that boundary matters.

## License

Personal portfolio project — no license specified yet.
