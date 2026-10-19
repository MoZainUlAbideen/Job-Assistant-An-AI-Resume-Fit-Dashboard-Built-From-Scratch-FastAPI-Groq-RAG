"""
Live LLM eval -- needs GROQ_API_KEY (in backend/.env). Run locally:

    uv run python eval/run_llm_eval.py                     # synthetic resume x all eval postings
    uv run python eval/run_llm_eval.py --resume my_cv.pdf  # your own resume (output goes to eval/private/, gitignored)

For every (resume, posting) pair it runs the real tailoring pipeline and reports:
  * how many rewrites the LLM proposed, how many the verifier accepted / blocked, and why
  * ATS score before -> after (re-scored by the same deterministic scorer)
  * every accepted rewrite next to its original, so a human can judge them

The verifier's acceptance rate is the honest metric for "does the LLM follow
the no-fabrication rules"; reading the accepted pairs is the honest check
that the verifier isn't letting junk through.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env", override=True)   # .env wins over a stale system env var

from app import llm  # noqa: E402
from app.extract import extract  # noqa: E402
from app.jd_parser import parse_jd  # noqa: E402
from app.resume_parser import parse_resume  # noqa: E402
from app.scoring import score  # noqa: E402
from app.tailor import apply_to_text, tailor  # noqa: E402
from app.extract import Extracted  # noqa: E402


def check_key():
    """Fail fast with a useful message instead of 10 silent 401s."""
    import os
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        sys.exit("GROQ_API_KEY is not set. Add a line  GROQ_API_KEY=gsk_...  to backend/.env")
    problems = []
    if key != key.strip():
        problems.append("it has leading/trailing spaces")
    if key[:1] in "\"'" or key[-1:] in "\"'":
        problems.append("it is wrapped in quotes")
    if not key.strip().strip("\"'").startswith("gsk_"):
        problems.append("it doesn't start with 'gsk_' (Groq keys do)")
    print(f"Using GROQ_API_KEY: {key.strip()[:4]}…{key.strip()[-4:]} ({len(key.strip())} chars), model {llm.model_name()}")
    if problems:
        sys.exit("Your GROQ_API_KEY looks wrong: " + "; ".join(problems) + ". Fix backend/.env and retry.")
    try:
        from groq import Groq
        Groq().models.list()
    except Exception as e:
        msg = str(e)
        if "401" in msg or "invalid_api_key" in msg.lower():
            sys.exit("Groq rejected the key (401 Invalid API Key). It was probably revoked or mistyped.\n"
                     "Create a new one at https://console.groq.com/keys, paste it into backend/.env as\n"
                     "GROQ_API_KEY=gsk_...   (no quotes, no spaces), then rerun.")
        sys.exit(f"Couldn't reach Groq: {msg[:200]}")
    models = None
    try:
        models = {m.id for m in Groq().models.list().data}
    except Exception:
        pass
    if models and llm.model_name() not in models:
        sys.exit(f"Model '{llm.model_name()}' isn't available on your Groq account. Available: {', '.join(sorted(models))}.\n"
                 "Set GROQ_MODEL in backend/.env to one of these.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", help="path to a .pdf/.docx/.txt resume (default: synthetic fixture)")
    args = ap.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows consoles default to cp1252
    check_key()

    if args.resume:
        p = Path(args.resume)
        doc = extract(p.read_bytes(), p.name)
        out_dir = ROOT / "private"
    else:
        p = ROOT.parent / "tests" / "fixtures" / "resume_ayesha.txt"
        doc = extract(p.read_bytes(), p.name)
        out_dir = ROOT / "results"
    resume = parse_resume(doc.text)
    postings = sorted((ROOT / "data" / "jds").glob("*.txt")) + sorted((ROOT / "data" / "heldout").glob("*.txt"))

    totals, reasons = Counter(), Counter()
    lines = [f"# Live LLM eval — model `{llm.model_name()}`", "", f"Resume: `{p.name}`", ""]
    deltas = []
    for f in postings:
        jd = parse_jd(f.read_text(encoding="utf-8"))
        before = score(doc, resume, jd)
        t0 = time.time()
        res = tailor(resume, jd, before)
        secs = time.time() - t0
        new_text = apply_to_text(resume, [e for e in res.edits if e.status == "accepted"], res.skills_added)
        after = score(Extracted(text=new_text, file_type=doc.file_type, cid_glyphs=doc.cid_glyphs),
                      parse_resume(new_text), jd)
        if res.llm_note and "LLM call failed" in res.llm_note:
            sys.exit(f"Stopping: {res.llm_note}")
        acc = [e for e in res.edits if e.status == "accepted"]
        rej = [e for e in res.edits if e.status == "rejected"]
        totals.update(proposed=len(res.edits), accepted=len(acc), rejected=len(rej))
        for e in rej:
            for r in e.reasons:
                reasons["adds a skill the role doesn't show" if r.startswith("adds ")
                        else " ".join(r.split("(")[0].split()[:5])] += 1
        deltas.append(after.score - before.score)
        lines += [f"## {f.name}", "",
                  f"score {before.score} → {after.score} · proposed {len(res.edits)}, accepted {len(acc)}, "
                  f"blocked {len(rej)} · skills added: {', '.join(s['keyword'] for s in res.skills_added) or '—'} "
                  f"· {secs:.1f}s" + (f" · note: {res.llm_note}" if res.llm_note else ""), ""]
        for e in acc:
            lines += [f"- ✅ **before:** {e.original}", f"  **after:** {e.rewritten}  _(+{', '.join(e.keywords_added)})_"]
        for e in rej:
            lines += [f"- ⛔ {e.rewritten}", f"  _blocked: {'; '.join(e.reasons)}_"]
        lines.append("")
        print(f"{f.name:32s} {before.score:5} → {after.score:5}  proposed={len(res.edits)} accepted={len(acc)} blocked={len(rej)}")

    summary = [
        "## Summary", "",
        f"- proposals: {totals['proposed']}, accepted: {totals['accepted']}, blocked: {totals['rejected']} "
        f"({totals['accepted'] / max(totals['proposed'], 1):.0%} acceptance)",
        f"- mean score change: {sum(deltas) / len(deltas):+.1f} points",
        "- block reasons: " + (", ".join(f"{k} ×{v}" for k, v in reasons.most_common()) or "none"), "",
        "Read the ✅ pairs above: any accepted rewrite that overstates the original is a verifier miss — "
        "add it to eval/data/rewrites_labeled.json as a new bad case.", "",
    ]
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"llm_eval_{llm.model_name().replace('/', '_')}.md"
    out.write_text("\n".join(lines[:4] + summary + lines[4:]), encoding="utf-8")
    print("\n".join(summary))
    print(f"Full report: {out}")


if __name__ == "__main__":
    main()
