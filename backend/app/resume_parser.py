"""
Resume text -> structured resume, deterministically (no LLM).

v1 sent the whole resume to an LLM and asked for JSON. On the author's real resume
that silently dropped the entire Projects section (7 bullets kept, all from
the two jobs) -- and the projects are where most of the AI keywords live.
A rule-based parser is less "smart" but it's predictable, testable, and
never quietly loses a section. It's also what most ATS parsers are: rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

SECTION_ALIASES: dict[str, list[str]] = {
    "summary": ["summary", "profile", "professional summary", "objective", "about me", "career objective",
                "professional profile", "career summary"],
    "experience": ["experience", "work experience", "professional experience", "employment", "employment history",
                   "work history", "internships", "internship experience", "relevant experience",
                   "experience and internships", "industry experience"],
    "projects": ["projects", "personal projects", "academic projects", "key projects", "selected projects",
                 "project experience", "technical projects", "notable projects"],
    "education": ["education", "academic background", "academics", "education and training"],
    "skills": ["skills", "technical skills", "core skills", "skills and tools", "tools", "technologies",
               "tech stack", "core competencies", "competencies", "skills and technologies", "key skills",
               "skills and expertise", "technical expertise", "tools and technologies"],
    "certifications": ["certifications", "certificates", "licenses", "courses", "training",
                       "licenses and certifications", "certifications and courses", "relevant coursework",
                       "coursework"],
    "awards": ["awards", "honors", "honours", "achievements", "accomplishments", "awards and honors"],
    "leadership": ["leadership", "volunteer", "volunteering", "extracurricular", "extracurricular activities",
                   "activities", "community", "leadership and activities", "volunteer experience",
                   "community involvement"],
    "publications": ["publications", "research", "research experience"],
}
_HEADING_LOOKUP = {a: k for k, v in SECTION_ALIASES.items() for a in v}
BULLET_SECTIONS = {"experience", "projects", "leadership", "publications", "summary"}
BULLET_RE = re.compile(r"^\s*(?:(?:[•\-\*▪●◦‣∙·–—►➢✓]|\(cid:\d+\))\s*|\d{1,2}[.)]\s+)(?=\S)")
SEASON_RE = re.compile(r"\b(spring|summer|fall|autumn|winter)\s+(\d{4})\b", re.IGNORECASE)
_SEASON_START = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 12}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE = rf"(?:{_MON}\.?\s*['’]?\d{{2,4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE})\s*(?:-|–|—|to|until)\s*(?P<end>{_DATE}|present|current|now|ongoing|date)", re.IGNORECASE)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)\d{3,4}[\s.-]?\d{3,4}")
LINKEDIN_RE = re.compile(r"linkedin\.com/in/[\w-]+|\blinkedin\b", re.IGNORECASE)
GITHUB_RE = re.compile(r"github\.com/[\w-]+|\bgithub\b", re.IGNORECASE)

DEGREE_LEVELS = {"associate": 1, "bachelor": 2, "master": 3, "phd": 4}
_DEGREE_PATTERNS = [
    ("phd", re.compile(r"\bph\.?\s?d\b|\bdoctorate\b|\bdoctor of philosophy\b", re.I)),
    ("master", re.compile(r"\bmaster'?s?\b|\bm\.?sc\b|\bm\.?eng\b|\bmba\b|\bm\.?tech\b|\bms in\b", re.I)),
    ("master", re.compile(r"\b(?:MS|M\.S\.|MSc|ME)\b")),
    ("bachelor", re.compile(r"\bbachelor'?s?\b|\bb\.?sc\b|\bb\.?eng\b|\bb\.?tech\b|\bbs in\b|\bundergraduate degree\b", re.I)),
    ("bachelor", re.compile(r"\b(?:BS|B\.S\.|BSc|BE|B\.E\.|BEE|BSCS|BSEE|BA|B\.A\.)\b")),
    ("associate", re.compile(r"\bassociate'?s? degree\b", re.I)),
]


@dataclass
class Bullet:
    id: int
    section: str
    text: str
    entry: str = ""                 # the role/company/project header it sits under
    line_indices: list[int] = field(default_factory=list)


@dataclass
class ParsedResume:
    raw_text: str
    lines: list[str]
    sections: dict[str, str]                    # section -> text
    section_order: list[str]
    bullets: list[Bullet]
    skills_lines: list[str]                     # raw lines of the skills section
    email: str | None
    phone: str | None
    has_linkedin: bool
    has_github: bool
    experience_months: int
    degree_level: str | None
    headline: str                               # first lines (name + title), used for title matching


def _norm_heading(line: str) -> str:
    s = re.sub(r"[^a-z& ]", " ", line.lower()).replace("&", "and")
    return re.sub(r"\s+", " ", s).strip()


def detect_heading(line: str) -> str | None:
    raw = line.strip()
    if not raw or len(raw) > 45 or raw.endswith("."):
        return None
    n = _norm_heading(raw)
    if not n or len(n.split()) > 5:
        return None
    if n in _HEADING_LOOKUP:
        return _HEADING_LOOKUP[n]
    # compound headings: "Certifications and Coursework", "Skills and Interests", "Awards / Honors"
    for part in re.split(r"\band\b", n):
        part = part.strip()
        if part in _HEADING_LOOKUP:
            return _HEADING_LOOKUP[part]
    return None


def _parse_date(s: str, is_end: bool) -> tuple[int, int] | None:
    s = s.strip().lower().replace("’", "'")
    if s in {"present", "current", "now", "ongoing", "date"}:
        t = date.today()
        return t.year, t.month
    m = re.match(rf"({_MON})\.?\s*'?(\d{{2,4}})", s, re.I)
    if m:
        yr = int(m.group(2))
        yr = yr + 2000 if yr < 100 else yr
        return yr, MONTHS[m.group(1)[:3].lower()]
    m = re.match(r"(\d{1,2})/(\d{4})", s)
    if m:
        return int(m.group(2)), int(m.group(1))
    m = re.match(r"(\d{4})", s)
    if m:
        return int(m.group(1)), 1   # year-only: Jan..Jan, so "2022 - 2024" = 24 months
    return None


def months_in_ranges(text: str) -> int:
    """Total months covered by date ranges, with overlaps merged (two
    concurrent jobs don't double-count)."""
    intervals = []
    for m in DATE_RANGE_RE.finditer(text):
        a, b = _parse_date(m.group("start"), False), _parse_date(m.group("end"), True)
        if not a or not b:
            continue
        start, end = a[0] * 12 + a[1], b[0] * 12 + b[1]
        if b == a:
            end += 1
        if 1980 * 12 < start <= end < 2100 * 12:
            intervals.append((start, end))
    # "Summer 2025" style single periods (internships) = 3 months, unless part of a range
    for m in SEASON_RE.finditer(DATE_RANGE_RE.sub(" ", text)):
        start = int(m.group(2)) * 12 + _SEASON_START[m.group(1).lower()]
        intervals.append((start, start + 3))
    intervals.sort()
    total, cur = 0, None
    for s, e in intervals:
        if cur and s <= cur[1]:
            cur = (cur[0], max(cur[1], e))
        else:
            if cur:
                total += cur[1] - cur[0]
            cur = (s, e)
    if cur:
        total += cur[1] - cur[0]
    return total


def degree_levels(text: str) -> set[str]:
    return {level for level, pat in _DEGREE_PATTERNS if pat.search(text)}


def degree_level(text: str) -> str | None:
    """Highest degree mentioned (resume side: your best degree)."""
    best = None
    for level, pat in _DEGREE_PATTERNS:
        if pat.search(text) and (best is None or DEGREE_LEVELS[level] > DEGREE_LEVELS[best]):
            best = level
    return best


def parse_resume(text: str) -> ParsedResume:
    lines = [l.rstrip() for l in text.splitlines()]
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    current = "header"
    line_section: list[str] = []
    for line in lines:
        h = detect_heading(line)
        if h:
            current = h
            if h not in order:
                order.append(h)
            line_section.append("_heading")
            continue
        sections.setdefault(current, []).append(line)
        line_section.append(current)

    bullets = _extract_bullets(lines, line_section)
    sec_text = {k: "\n".join(v).strip() for k, v in sections.items()}

    email = EMAIL_RE.search(text)
    phone = None
    for m in PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 10 <= len(digits) <= 15 and not DATE_RANGE_RE.search(m.group()):
            phone = m.group().strip()
            break

    exp_text = sec_text.get("experience", "")
    edu_text = sec_text.get("education", "") or text
    headline = "\n".join(l for l in lines[:4] if l.strip())

    return ParsedResume(
        raw_text=text, lines=lines, sections=sec_text, section_order=order, bullets=bullets,
        skills_lines=[l for l in sections.get("skills", []) if l.strip()],
        email=email.group() if email else None, phone=phone,
        has_linkedin=bool(LINKEDIN_RE.search(text)), has_github=bool(GITHUB_RE.search(text)),
        experience_months=months_in_ranges(exp_text),
        degree_level=degree_level(edu_text),
        headline=headline,
    )


def _extract_bullets(lines: list[str], line_section: list[str]) -> list[Bullet]:
    bullets: list[Bullet] = []
    entry = ""
    open_b: Bullet | None = None
    sections_with_glyphs = {s for l, s in zip(lines, line_section) if BULLET_RE.match(l)}

    for i, (line, sec) in enumerate(zip(lines, line_section)):
        if sec == "_heading":
            open_b, entry = None, ""
            continue
        if sec not in BULLET_SECTIONS or not line.strip():
            open_b = None if not line.strip() else open_b
            continue
        stripped = line.strip()
        if BULLET_RE.match(line):
            open_b = Bullet(len(bullets), sec, BULLET_RE.sub("", line).strip(), entry, [i])
            bullets.append(open_b)
            continue
        is_header_like = bool(DATE_RANGE_RE.search(stripped)) or ("|" in stripped and len(stripped) < 120)
        if open_b and not is_header_like and (stripped[0].islower() or not open_b.text.rstrip().endswith((".", "!", "?"))) \
                and sec in sections_with_glyphs:
            open_b.text = f"{open_b.text} {stripped}"   # wrapped continuation line from the PDF
            open_b.line_indices.append(i)
            continue
        if sec in sections_with_glyphs or is_header_like or len(stripped.split()) < 6 or sec == "summary":
            entry = stripped if (is_header_like or len(stripped.split()) < 12) else entry
            open_b = None
            if sec == "summary" and len(stripped.split()) >= 6:
                open_b = Bullet(len(bullets), sec, stripped, "Summary", [i])
                bullets.append(open_b)
            continue
        # section without bullet glyphs: treat each substantial sentence-line as a bullet
        open_b = Bullet(len(bullets), sec, stripped, entry, [i])
        bullets.append(open_b)
    return bullets
