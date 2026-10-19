"""
Grounded resume tailoring: improve ATS keyword coverage WITHOUT inventing anything.

What v1 got wrong (from its own saved output): the rewrite prompt said "don't
fabricate", but nothing checked. It produced lines like
    "...leveraging AI agents in a cloud-based environment"
    "...implying autonomous or agent-like capabilities"
for an Azure deployment bullet that had nothing to do with agents. Prompt
instructions are a request, not a guarantee.

v2 splits the work:
  1. Deterministic edits (no LLM): add JD keywords to the Skills section ONLY
     when the resume already has concrete evidence (PyTorch -> "Deep Learning").
  2. LLM proposes bullet rewrites for those same evidenced keywords.
  3. verify_edit() checks every proposal in code, and rejects it if it:
       - introduces a skill/tool the role or project doesn't show
       - introduces any number not in the original bullet (fake metrics)
       - introduces new proper nouns / technical tokens (fake clients, tools)
       - uses filler/hedging ("implying", "agent-like", "expertise")
       - drifts too far from the original (it must be an edit, not a new bullet)
       - doesn't actually add a target keyword (no point making the change)
     Rejected proposals are returned with the reason -- shown in the UI, so
     the user sees what was blocked and why.
  4. Missing skills with no evidence are listed as gaps, never added.
  5. Re-score the edited resume with the same deterministic scorer, so the
     before/after improvement is measured, not claimed.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from app import llm
from app.jd_parser import ParsedJD
from app.resume_parser import Bullet, ParsedResume
from app.scoring import Report
from app.skills import BY_NAME, find_skills, implied_evidence

MAX_EDITS = 6
FILLER = re.compile(r"\b(implying|implies|implied|\w+-like|demonstrating|showcasing|expertise|proficiency|"
                    r"passionate|synergy|cutting-edge|state-of-the-art|world-class|various|leveraging\s+\w+\s+capabilities)\b",
                    re.IGNORECASE)
WEAK_OPENERS = re.compile(r"^(utilized|worked on|responsible for|helped|assisted|was involved|participated in)\b",
                          re.IGNORECASE)
STOP = set("""a an the and or of for to in on with by from at as into using use used via that this these those
is are was were be been it its their our your over across through within while including such per""".split())


@dataclass
class Edit:
    bullet_id: int
    section: str
    entry: str
    original: str
    rewritten: str
    keywords_added: list[str]
    status: str = "accepted"          # "accepted" | "rejected"
    reasons: list[str] = field(default_factory=list)


@dataclass
class TailorResult:
    skills_added: list[dict]          # [{"keyword", "evidence": [...]}]
    edits: list[Edit]                 # accepted + rejected, for transparency
    gaps: list[str]                   # required/preferred skills with no evidence -> not added
    title_suggestion: str | None
    llm_used: bool
    llm_note: str | None
    new_text: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("new_text")
        return d


# ------------------------------------------------------------------ helpers
def _content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9+#.]+", text.lower())
    return {w.rstrip(".")[:6] for w in words if w not in STOP and len(w) > 2}


def _entry_scope(resume: ParsedResume, b: Bullet) -> str:
    """Evidence scope for a bullet: its role/project header + all sibling bullets."""
    sib = [x.text for x in resume.bullets if x.entry == b.entry and x.section == b.section]
    return b.entry + "\n" + "\n".join(sib)


def _novel_tokens(new: str, original_resume: str, allowed_spans_text: str) -> list[str]:
    """Technical-looking or capitalised tokens in `new` that appear nowhere in the
    original resume (fake tools, clients, certifications...). Tokens inside
    allowed skill names are excluded -- those are handled by the skill rule."""
    def toks(t: str) -> list[str]:
        return [x.rstrip(".") for x in re.findall(r"[A-Za-z0-9][A-Za-z0-9+#.]*", t)]

    vocab = {x.lower() for x in toks(original_resume)}
    allowed = {x.lower() for x in toks(allowed_spans_text)}
    out = []
    for i, core in enumerate(toks(new)):
        low = core.lower()
        if not core or low in vocab or low in allowed or low in STOP:
            continue
        technical = bool(re.search(r"[A-Z].*[A-Z]|\d|[+#]|\.\w", core[1:] if i == 0 else core))
        capitalised = i > 0 and core[0].isupper()
        if technical or capitalised:
            out.append(core)
    return out


def verify_edit(original: str, rewritten: str, targets: set[str], scope: str, resume_text: str) -> tuple[list[str], list[str]]:
    """Returns (keywords_added, rejection_reasons). Empty reasons == accepted."""
    reasons: list[str] = []
    orig_sk, new_sk = set(find_skills(original)), find_skills(rewritten)
    scope_sk = set(find_skills(scope))

    added = sorted(set(new_sk) - orig_sk)
    for s in added:
        if s in scope_sk or implied_evidence(s, scope_sk):
            continue
        reasons.append(f"adds '{s}', which this role/project doesn't show")
    kw_gain = [s for s in added if s in targets]

    new_nums = set(re.findall(r"\d+(?:[.,]\d+)?", rewritten)) - set(re.findall(r"\d+(?:[.,]\d+)?", original))
    if new_nums:
        reasons.append(f"introduces numbers not in the original ({', '.join(sorted(new_nums))})")

    skill_text = " ".join(rewritten[a:b] for h in new_sk.values() for a, b in h.spans)
    novel = _novel_tokens(rewritten, resume_text, skill_text)
    if novel:
        reasons.append(f"introduces terms not on your resume ({', '.join(novel[:4])})")

    m = FILLER.search(rewritten)
    if m:
        reasons.append(f"filler/hedging language ('{m.group(0)}')")

    ow, nw = _content_words(original), _content_words(rewritten)
    if ow and len(ow & nw) / len(ow) < 0.6:
        reasons.append("changes too much of the original — not an edit anymore")
    n_orig, n_new = len(original.split()), len(rewritten.split())
    if n_new > n_orig + 18 or n_new > 1.7 * n_orig + 4:
        reasons.append(f"too long ({n_orig} → {n_new} words)")
    if not kw_gain and not reasons:
        reasons.append("doesn't add any of the job's keywords")   # harmless but pointless churn
    return kw_gain, reasons


# ------------------------------------------------------------------ main
SYSTEM = """You edit resume bullet points so they use a job description's exact keywords, WITHOUT inventing anything.
You will be given bullets (with ids) and target keywords, each with the evidence that already exists on the resume.

Rules:
1. Only rewrite a bullet if the work it ALREADY describes genuinely is an instance of a target keyword
   (e.g. a bullet about training PyTorch models is Deep Learning). If not, leave it out.
2. Use the target keyword's exact spelling.
3. Keep every fact. Do NOT add tools, libraries, numbers, metrics, clients, team sizes, outcomes or claims
   that are not in the original bullet.
4. Start with a strong past-tense action verb. Replace weak openers like "Utilized", "Worked on", "Responsible for".
5. Keep it concise: at most 15 words longer than the original. No filler ("leveraging", "expertise", "cutting-edge").
6. At most {max_edits} edits, best first. Fewer is fine. Zero is fine.

Return JSON: {{"edits": [{{"id": <bullet id>, "text": "<rewritten bullet>", "keywords": ["<target keyword used>"]}}]}}"""


def tailor(resume: ParsedResume, jd: ParsedJD, report: Report) -> TailorResult:
    present = set(find_skills(resume.raw_text))

    # 1) evidenced keywords -> Skills section (deterministic)
    skills_added, targets, gaps = [], set(), []
    for k in report.keywords:
        if k.soft:
            continue
        if k.status == "implied":
            name = next((o for o in k.options if implied_evidence(o, present)), k.options[0])
            skills_added.append({"keyword": name, "evidence": implied_evidence(name, present)})
            targets.add(name)
        elif k.status == "matched" and not k.in_experience:
            targets.add(k.matched_as)          # listed in Skills but never shown in a bullet
        elif k.status == "missing":
            gaps.append(k.keyword)

    # 2) LLM proposals for bullets
    edits: list[Edit] = []
    llm_used, llm_note = False, None
    work = [b for b in resume.bullets if b.section in ("experience", "projects", "summary")]
    if targets and work:
        if not llm.available():
            llm_note = "Bullet rewrites need a GROQ_API_KEY on the server; showing Skills-section edits only."
        else:
            payload = {
                "job_title": jd.title,
                "target_keywords": [{"keyword": t, "evidence_on_resume": implied_evidence(t, present) or [t]}
                                    for t in sorted(targets)],
                "bullets": [{"id": b.id, "context": b.entry[:80], "text": b.text} for b in work],
            }
            try:
                data = llm.chat_json(SYSTEM.format(max_edits=MAX_EDITS), json.dumps(payload, ensure_ascii=False))
                llm_used = True
                edits = _check_proposals(data, resume, targets)
            except llm.LLMUnavailable as e:
                llm_note = f"Bullet rewrites unavailable right now ({e}). Skills-section edits still applied."

    # 3) title suggestion (never auto-applied -- your headline is your call)
    title_suggestion = None
    if report.components.get("title", {}).get("score", 100) < 100 and jd.title:
        title_suggestion = (f"If it's accurate for you, consider using the job's exact title "
                            f"'{jd.title}' in your headline/summary — ATS and recruiters search by title.")

    new_text = apply_to_text(resume, [e for e in edits if e.status == "accepted"], skills_added)
    return TailorResult(skills_added, edits, gaps, title_suggestion, llm_used, llm_note, new_text)


def _check_proposals(data: dict, resume: ParsedResume, targets: set[str]) -> list[Edit]:
    by_id = {b.id: b for b in resume.bullets}
    out: list[Edit] = []
    used: set[int] = set()
    for p in (data.get("edits") or [])[: MAX_EDITS + 2]:
        try:
            bid, text = int(p.get("id")), str(p.get("text", "")).strip().lstrip("•-* ").strip()
        except (TypeError, ValueError):
            continue
        b = by_id.get(bid)
        if not b or not text or bid in used or text == b.text:
            continue
        used.add(bid)
        kw, reasons = verify_edit(b.text, text, targets, _entry_scope(resume, b), resume.raw_text)
        out.append(Edit(bid, b.section, b.entry, b.text, text, kw,
                        "rejected" if reasons else "accepted", reasons))
    accepted = [e for e in out if e.status == "accepted"][:MAX_EDITS]
    return accepted + [e for e in out if e.status == "rejected"]


def apply_to_text(resume: ParsedResume, accepted: list[Edit], skills_added: list[dict]) -> str:
    """Plain-text version of the tailored resume (used for re-scoring and for PDF/TXT inputs)."""
    lines: list[str | None] = list(resume.lines)
    new_text = {e.bullet_id: e.rewritten for e in accepted}
    # every bullet becomes ONE line (PDFs hard-wrap long bullets; rebuilding from those
    # fragments produced broken lines like "...underground sensor / measurements.")
    for b in resume.bullets:
        first = b.line_indices[0]
        is_bullet = bool(re.match(r"^\s*(?:[•\-\*▪●◦‣∙·–—►➢✓]|\(cid:\d+\))", lines[first] or ""))
        lines[first] = ("• " if is_bullet else "") + new_text.get(b.id, b.text)
        for i in b.line_indices[1:]:
            lines[i] = None
    # skills lines that wrapped mid-list ("..., MediaPipe," / "Ultralytics YOLO, Tesseract")
    for i in range(len(lines) - 1):
        if lines[i] is not None and lines[i].rstrip().endswith(",") and lines[i + 1]:
            lines[i + 1] = lines[i].rstrip() + " " + lines[i + 1].strip()
            lines[i] = None
    lines = [l for l in lines if l is not None]
    if skills_added:
        line = "Core Competencies: " + ", ".join(s["keyword"] for s in skills_added)
        idx = _skills_heading_index(lines)
        if idx is None:
            lines += ["", "Skills", line]
        else:
            lines.insert(idx + 1, line)
    return "\n".join(lines)


def _skills_heading_index(lines: list[str]) -> int | None:
    from app.resume_parser import detect_heading
    for i, l in enumerate(lines):
        if detect_heading(l) == "skills":
            return i
    return None
