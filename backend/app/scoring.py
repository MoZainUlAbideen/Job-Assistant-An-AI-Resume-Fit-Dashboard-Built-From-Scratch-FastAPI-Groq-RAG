"""
Resume x JD -> ATS-style match report.

Score = weighted blend of the things real ATS filters and recruiters check
(same component idea as Jobscan-style scanners), renormalised over the
components that apply to this JD:

  keywords    60  required hard skills weigh 1.0, preferred 0.5, soft skills
                  0.25 / 0.1; repeated-in-JD skills get a small bump.
                  literal match = full credit; implied-only = 0.4 credit
                  (an ATS won't see it -- but you can honestly add the term)
  title       10  does the JD's job title appear on the resume?
  experience  15  resume years (from date ranges) vs "N+ years" -- only if stated
  education    5  degree level vs requirement -- only if stated
  format      10  parseability checks (format_checks.py)

Every number in the report is traceable to a rule in this file -- no LLM is
involved in scoring, so the same inputs always give the same score.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.extract import Extracted
from app.format_checks import Check, format_score, run_checks, writing_tips
from app.jd_parser import ParsedJD, Requirement
from app.resume_parser import DEGREE_LEVELS, ParsedResume
from app.skills import find_skills, implied_evidence

WEIGHTS = {"keywords": 60, "title": 10, "experience": 15, "education": 5, "format": 10}
IMPLIED_CREDIT = 0.4
SENIORITY = re.compile(r"\b(senior|sr|junior|jr|lead|principal|staff|mid|mid-level|level|entry|entry-level|"
                       r"associate|head|chief|i|ii|iii|iv|1|2|3|remote|hybrid|onsite|contract|full-time|"
                       r"part-time|intern|internship|trainee|graduate)\b\.?", re.IGNORECASE)


@dataclass
class KeywordResult:
    keyword: str                 # display label ("PyTorch or TensorFlow")
    options: list[str]
    importance: str
    soft: bool
    jd_count: int
    status: str                  # "matched" | "implied" | "missing"
    resume_count: int = 0
    matched_as: str | None = None
    evidence: list[str] = field(default_factory=list)   # for implied: the skills that imply it
    in_skills_section: bool = False
    in_experience: bool = False
    weight: float = 0.0


@dataclass
class Report:
    score: float
    components: dict[str, dict]
    keywords: list[KeywordResult]
    knockouts: list[str]
    checks: list[Check]
    tips: dict
    jd_title: str
    resume_years: float
    jd_min_years: float | None
    resume_degree: str | None
    jd_degree: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _weight(r: Requirement) -> float:
    base = (0.25 if r.importance == "required" else 0.1) if r.soft else (1.0 if r.importance == "required" else 0.5)
    return base * (1 + 0.15 * min(max(r.count - 1, 0), 3))


def _norm_title(t: str) -> str:
    t = re.sub(r"\(.*?\)|\s[-–—|]\s.*$|,.*$", " ", t)   # drop "(Remote)", " - Team X", ", London" suffixes
    t = SENIORITY.sub(" ", t)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#. ]", " ", t.lower())).strip()


def title_match(jd_title: str, resume: ParsedResume) -> float | None:
    core = _norm_title(jd_title)
    if not core:
        return None
    hay = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#. ]", " ", resume.raw_text.lower()))
    if re.search(rf"(?<![a-z0-9]){re.escape(core)}(?![a-z0-9])", hay):
        return 1.0
    toks = [t for t in core.split() if len(t) > 1]
    # partial credit: most of the title's words on ONE headline/role line ("AI Engineer" for
    # "AI/ML Engineer"). Per-line, so "Data Science Intern" + "ML Engineer" != "Data Engineer".
    cand_lines = [l for l in resume.headline.splitlines()] + [b.entry for b in resume.bullets]
    best = 0.0
    for line in cand_lines:
        l = re.sub(r"[^a-z0-9+#. ]", " ", line.lower())
        hit = sum(1 for t in toks if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", l))
        best = max(best, hit / len(toks) if toks else 0)
    present_ratio = best
    return 0.5 if toks and present_ratio >= 0.6 else 0.0


def score(doc: Extracted, resume: ParsedResume, jd: ParsedJD) -> Report:
    all_hits = find_skills(resume.raw_text)
    present = set(all_hits)
    skills_hits = set(find_skills(resume.sections.get("skills", "")))
    work_text = "\n".join(b.text + " " + b.entry for b in resume.bullets if b.section in ("experience", "projects"))
    work_hits = set(find_skills(work_text))

    kws: list[KeywordResult] = []
    for req in jd.requirements:
        kr = KeywordResult(req.label, req.options, req.importance, req.soft, req.count, "missing",
                           weight=_weight(req))
        lit = [o for o in req.options if o in present]
        if lit:
            o = lit[0]
            kr.status, kr.matched_as, kr.resume_count = "matched", o, all_hits[o].count
            kr.in_skills_section, kr.in_experience = o in skills_hits, o in work_hits
        else:
            ev = sorted({e for o in req.options for e in implied_evidence(o, present)})
            if ev:
                kr.status, kr.evidence = "implied", ev
        kws.append(kr)

    comps: dict[str, dict] = {}
    total_w = sum(k.weight for k in kws)
    if total_w:
        got = sum(k.weight * (1 if k.status == "matched" else IMPLIED_CREDIT if k.status == "implied" else 0)
                  for k in kws)
        hard = [k for k in kws if not k.soft]
        comps["keywords"] = {
            "score": round(100 * got / total_w, 1),
            "detail": f"{sum(k.status == 'matched' for k in hard)}/{len(hard)} hard skills matched literally, "
                      f"{sum(k.status == 'implied' for k in hard)} implied by related skills",
        }

    tm = title_match(jd.title, resume) if jd.title else None
    if tm is not None:
        comps["title"] = {"score": round(100 * tm, 1),
                          "detail": {1.0: f"'{jd.title}' appears on your resume",
                                     0.5: f"Part of '{jd.title}' appears on your resume",
                                     0.0: f"'{jd.title}' doesn't appear on your resume"}[tm]}

    years = round(resume.experience_months / 12, 1)
    knockouts: list[str] = []
    if jd.min_years:
        ratio = min(1.0, years / jd.min_years)
        comps["experience"] = {"score": round(100 * ratio, 1),
                               "detail": f"~{years} yrs found in dated roles vs {jd.min_years:g}+ required"}
        if years < 0.75 * jd.min_years:
            knockouts.append(f"Experience: the JD asks for {jd.min_years:g}+ years; your dated roles add up to "
                             f"~{years}. Many ATS use this as a hard filter.")

    if jd.degree_required:
        ok = resume.degree_level is not None and DEGREE_LEVELS[resume.degree_level] >= DEGREE_LEVELS[jd.degree_required]
        comps["education"] = {"score": 100.0 if ok else 0.0,
                              "detail": f"JD {'prefers' if jd.degree_is_preferred else 'requires'} "
                                        f"{jd.degree_required}'s; resume shows "
                                        f"{(resume.degree_level + chr(39) + 's') if resume.degree_level else 'no degree'}"}
        if not ok and not jd.degree_is_preferred:
            knockouts.append(f"Education: requires a {jd.degree_required}'s degree, not detected on your resume.")

    checks = run_checks(doc, resume)
    comps["format"] = {"score": format_score(checks),
                       "detail": f"{sum(c.status != 'pass' for c in checks)} parseability issue(s)"}

    for k in kws:
        if k.status == "missing" and k.importance == "required" and not k.soft:
            knockouts.append(f"Missing required skill: {k.keyword}")

    applicable = {k: WEIGHTS[k] for k in comps}
    overall = sum(comps[k]["score"] * w for k, w in applicable.items()) / sum(applicable.values())
    for k in comps:
        comps[k]["weight"] = round(100 * applicable[k] / sum(applicable.values()), 1)

    return Report(
        score=round(overall, 1), components=comps, keywords=kws, knockouts=knockouts, checks=checks,
        tips=writing_tips(resume), jd_title=jd.title, resume_years=years, jd_min_years=jd.min_years,
        resume_degree=resume.degree_level, jd_degree=jd.degree_required,
    )
