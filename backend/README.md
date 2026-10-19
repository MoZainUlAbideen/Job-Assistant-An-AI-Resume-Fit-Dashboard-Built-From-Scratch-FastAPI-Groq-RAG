# Backend (FastAPI)

| module | job |
|---|---|
| `app/extract.py` | PDF/DOCX/TXT → text + layout signals (tables, columns, header text, unmapped glyphs) |
| `app/skills.py` | skill dictionary, aliases, "related skills" evidence, boundary-safe matching |
| `app/resume_parser.py` | sections, bullets, contact info, years from date ranges, degree |
| `app/jd_parser.py` | required vs preferred, either-or groups, years, degree, title |
| `app/format_checks.py` | ATS parseability checks |
| `app/scoring.py` | weighted, explainable score (no LLM) |
| `app/tailor.py` | evidenced Skills additions, LLM bullet proposals, `verify_edit()` |
| `app/docx_out.py` | edit the DOCX in place, or rebuild a clean DOCX from PDF/TXT |
| `app/llm.py` | Groq wrapper (temperature 0, JSON mode, memoized) |
| `app/ratelimit.py` | per-IP limits so a public URL can't drain your Groq quota |
| `app/main.py` | `/api/health`, `/api/scan`, `/api/tailor` |

```bash
uv sync && cp .env.example .env
uv run uvicorn app.main:app --reload --port 8000   # http://localhost:8000/docs
uv run pytest -q
uv run python eval/run_eval.py          # offline eval -> eval/results/latest.md
uv run python eval/run_llm_eval.py      # live LLM eval (needs GROQ_API_KEY)
```

`requirements.txt` is generated for Render with `uv export --no-dev --no-hashes --no-emit-project -o requirements.txt`. Re-run it after changing dependencies.
