"""
Offline eval -- no API key needed, runs in ~1s.

    uv run python eval/run_eval.py

Measures, against hand labels in eval/data/:
  1. JD keyword extraction  precision / recall / required-vs-preferred accuracy
  2. JD years / degree / title extraction accuracy
  3. Fabrication verifier   on labelled honest vs bad rewrites
  4. Score stability        (same input scored repeatedly)

Writes eval/results/latest.md. Numbers are whatever they are -- the misses
are listed so they can be fixed or at least known.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from app.extract import Extracted  # noqa: E402
from app.jd_parser import parse_jd  # noqa: E402
from app.resume_parser import parse_resume  # noqa: E402
from app.scoring import score  # noqa: E402
from app.tailor import _entry_scope, verify_edit  # noqa: E402

DATA = ROOT / "data"
RESUME = (ROOT.parent / "tests" / "fixtures" / "resume_ayesha.txt").read_text(encoding="utf-8")


def jd_extraction(label_file: str = "jd_labels.json", folder: str = "jds"):
    labels = json.loads((DATA / label_file).read_text(encoding="utf-8"))
    tp = fp = fn = imp_ok = imp_n = 0
    rows, misses = [], []
    years_ok = deg_ok = title_ok = 0
    n = 0
    for fname, lab in labels.items():
        if fname.startswith("_"):
            continue
        n += 1
        jd = parse_jd((DATA / folder / fname).read_text(encoding="utf-8"))
        gold = [(set(g.split("|")), "required") for g in lab["required"]] + \
               [(set(g.split("|")), "preferred") for g in lab["preferred"]]
        got = [(set(r.options), r.importance, r.label) for r in jd.requirements]
        matched_gold = set()
        f_tp = f_fp = 0
        for opts, imp, label in got:
            gi = next((i for i, (g, _) in enumerate(gold) if g & opts), None)
            if gi is None:
                f_fp += 1
                misses.append(f"{fname}: extra '{label}' ({imp})")
                continue
            f_tp += 1
            if gi not in matched_gold:
                matched_gold.add(gi)
                imp_n += 1
                if gold[gi][1] == imp:
                    imp_ok += 1
                else:
                    misses.append(f"{fname}: '{label}' tagged {imp}, label says {gold[gi][1]}")
        f_fn = len(gold) - len(matched_gold)
        for i, (g, imp) in enumerate(gold):
            if i not in matched_gold:
                misses.append(f"{fname}: missed '{'|'.join(sorted(g))}' ({imp})")
        tp, fp, fn = tp + f_tp, fp + f_fp, fn + f_fn
        y_ok = jd.min_years == (float(lab["min_years"]) if lab["min_years"] is not None else None)
        d_ok = jd.degree_required == lab["degree"]
        t_ok = jd.title.strip().lower() == lab["title"].lower()
        years_ok, deg_ok, title_ok = years_ok + y_ok, deg_ok + d_ok, title_ok + t_ok
        if not y_ok:
            misses.append(f"{fname}: years {jd.min_years} vs label {lab['min_years']}")
        if not d_ok:
            misses.append(f"{fname}: degree {jd.degree_required} vs label {lab['degree']}")
        if not t_ok:
            misses.append(f"{fname}: title '{jd.title}' vs label '{lab['title']}'")
        rows.append((fname, f_tp, f_fp, f_fn))
    prec, rec = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    return {
        "precision": prec, "recall": rec, "importance_acc": imp_ok / max(imp_n, 1),
        "years_acc": years_ok / n, "degree_acc": deg_ok / n, "title_acc": title_ok / n,
        "rows": rows, "misses": misses, "n": n,
    }


def verifier():
    r = parse_resume(RESUME)
    cases = json.loads((DATA / "rewrites_labeled.json").read_text(encoding="utf-8"))["cases"]
    tp = fp = tn = fn = 0
    wrong = []
    for c in cases:
        b = next(x for x in r.bullets if x.text.startswith(c["bullet_startswith"]))
        _, reasons = verify_edit(b.text, c["rewritten"], set(c["targets"]), _entry_scope(r, b), r.raw_text)
        bad, blocked = c["label"] != "honest", bool(reasons)
        if bad and blocked:
            tp += 1
        elif bad and not blocked:
            fn += 1
            wrong.append(f"LET THROUGH ({c['label']}): {c['rewritten']}")
        elif not bad and blocked:
            fp += 1
            wrong.append(f"BLOCKED honest: {c['rewritten']}  <- {reasons}")
        else:
            tn += 1
    return {"bad_blocked": tp, "bad_total": tp + fn, "honest_accepted": tn, "honest_total": tn + fp, "wrong": wrong}


def stability(repeats: int = 5):
    r = parse_resume(RESUME)
    doc = Extracted(text=RESUME, file_type="txt")
    spreads = []
    for f in sorted((DATA / "jds").glob("*.txt")):
        scores = {score(doc, r, parse_jd(f.read_text(encoding="utf-8"))).score for _ in range(repeats)}
        spreads.append(max(scores) - min(scores))
    return max(spreads)


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows consoles default to cp1252
    jd, v, spread = jd_extraction(), verifier(), stability()
    ho = jd_extraction("heldout_labels.json", "heldout")
    out = [
        "# Offline eval results", "",
        "Generated by `uv run python eval/run_eval.py` (deterministic, no API key).", "",
        f"## JD keyword extraction — dev set ({jd['n']} postings; bugs were fixed against these)", "",
        "| metric | value |", "|---|---|",
        f"| precision (extracted skills that are real requirements) | {jd['precision']:.0%} |",
        f"| recall (labelled requirements found) | {jd['recall']:.0%} |",
        f"| required-vs-preferred correct | {jd['importance_acc']:.0%} |",
        f"| min-years correct | {jd['years_acc']:.0%} |",
        f"| degree requirement correct | {jd['degree_acc']:.0%} |",
        f"| title guess exact | {jd['title_acc']:.0%} |",
        "", "| posting | TP | FP | FN |", "|---|---|---|---|",
        *[f"| {a} | {b} | {c} | {d} |" for a, b, c, d in jd["rows"]],
        "", "**Misses** (known gaps, kept visible on purpose):", "",
        *([f"- {m}" for m in jd["misses"]] or ["- none"]),
        "", f"## Held-out postings ({ho['n']}, written after the code was frozen — the honest number)", "",
        "| metric | dev set | held-out |", "|---|---|---|",
        *[f"| {k} | {jd[key]:.0%} | {ho[key]:.0%} |" for k, key in [
            ("precision", "precision"), ("recall", "recall"), ("required-vs-preferred", "importance_acc"),
            ("min-years", "years_acc"), ("degree", "degree_acc"), ("title guess", "title_acc")]],
        "", "First run on the held-out set (before any change): precision 100%, recall 78%, required-vs-preferred 98%,",
        "years 100%, degree 75%, title 100%. One clear bug it exposed was then fixed ('MS or PhD' read as PhD), so the",
        "held-out set is no longer untouched; the table above is the current run.",
        "", "Held-out misses:", "", *([f"- {m}" for m in ho["misses"]] or ["- none"]),
        "", "## Fabrication verifier (labelled rewrites)", "",
        f"- bad rewrites blocked: **{v['bad_blocked']}/{v['bad_total']}**",
        f"- honest rewrites accepted: **{v['honest_accepted']}/{v['honest_total']}**",
        *[f"- {w}" for w in v["wrong"]],
        "", "## Stability", "",
        f"- max score spread over 5 repeated scans of each posting: **{spread}** points",
        "- (v1, measured from its saved database: the same 8 postings scanned 3× each swung by up to 33 points)",
    ]
    text = "\n".join(out) + "\n"
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "latest.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
