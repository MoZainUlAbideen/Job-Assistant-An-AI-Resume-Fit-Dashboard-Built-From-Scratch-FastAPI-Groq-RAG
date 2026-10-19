"""
Job description text -> requirements, deterministically.

For each taxonomy skill found in the JD we decide REQUIRED vs PREFERRED from
context, the same way a human skims a posting:
  * the section it sits under ("Requirements" vs "Nice to have")
  * cue words on the same line ("preferred", "a plus", "bonus", "ideally")
A skill that shows up in both contexts counts as required. Skills found only
in boilerplate ("About us", "Benefits", EEO text) are ignored -- a company
blurb saying "we're an AI-first startup" isn't a requirement.

Plus: years of experience ("3+ years", "minimum of 5 years"), degree level,
and a best-guess job title (the frontend lets the user override it).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.skills import BY_NAME, find_skills
from app.resume_parser import DEGREE_LEVELS, degree_level, degree_levels

REQ_HEAD = ["requirements", "required", "qualifications", "minimum qualifications", "basic qualifications",
            "what you'll need", "what you will need", "what you need", "must have", "must-have", "must haves",
            "what we're looking for", "what we are looking for", "who you are", "you have", "you bring",
            "skills", "required skills", "key skills", "your profile", "about you", "the ideal candidate",
            "experience", "technical skills", "requirements and qualifications", "job requirements", "skills required"]
PREF_HEAD = ["nice to have", "nice-to-have", "nice to haves", "preferred", "preferred qualifications",
             "bonus", "bonus points", "plus", "pluses", "good to have", "desired", "desirable",
             "it would be great if", "extra credit", "preferred skills", "additional qualifications"]
RESP_HEAD = ["responsibilities", "what you'll do", "what you will do", "the role", "your role", "duties",
             "key responsibilities", "role and responsibilities", "day to day", "your responsibilities",
             "job description", "about the role", "in this role", "your mission"]
IGNORE_HEAD = ["about us", "about the company", "who we are", "benefits", "perks", "what we offer",
               "compensation", "equal opportunity", "our values", "why join us", "life at", "salary", "eeo",
               "how to apply", "our culture"]

PREF_CUES = re.compile(r"\b(preferred|a plus|is a plus|are a plus|plus\b|bonus|nice to have|nice-to-have|ideally|"
                       r"desirable|desired|good to have|advantage|advantageous|familiarity with|exposure to)\b",
                       re.IGNORECASE)
# "3+ years of experience", "3-5 years in data engineering", "2+ years with React",
# "minimum of 4 years". A bare "5 years" needs a qualifier (+, range, minimum/at least) or the
# word "experience" nearby, so "we've grown for 5 years" doesn't count.
YEARS_RE = re.compile(
    r"(?:(?P<q>minimum\s+(?:of\s+)?|at\s+least\s+|over\s+))?(?P<n>\d{1,2})\s*(?P<plus>\+|plus)?\s*"
    r"(?:(?P<range>-|–|to)\s*\d{1,2}\s*)?\+?\s*(?:years?|yrs?)\b(?!\s+old)(?P<tail>(?:\s+\w+){0,5})",
    re.IGNORECASE)


def _years_in(clause: str) -> list[int]:
    out = []
    for m in YEARS_RE.finditer(clause):
        qualified = m.group("q") or m.group("plus") or m.group("range")
        if qualified or re.search(r"\b(experience|exp)\b", m.group("tail") or "", re.I):
            out.append(int(m.group("n")))
    return out
FIELD_RE = re.compile(r"\b(computer science|software engineering|computer engineering|electrical engineering|"
                      r"data science|mathematics|statistics|physics|information technology|engineering|"
                      r"related (?:technical )?field|quantitative field|stem)\b", re.IGNORECASE)


@dataclass
class Requirement:
    skill: str                                   # primary (first-mentioned) skill
    importance: str                              # "required" | "preferred"
    count: int
    soft: bool = False
    alternatives: list[str] = field(default_factory=list)   # "PyTorch or TensorFlow" -> either satisfies

    @property
    def options(self) -> list[str]:
        return [self.skill, *self.alternatives]

    @property
    def label(self) -> str:
        return " or ".join(self.options)


@dataclass
class ParsedJD:
    raw_text: str
    title: str
    requirements: list[Requirement]
    min_years: float | None
    degree_required: str | None          # "bachelor" | "master" | "phd" | None
    degree_fields: list[str] = field(default_factory=list)
    degree_is_preferred: bool = False


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z' &-]", " ", line.lower())).strip(" :-")


def _classify_heading(line: str) -> str | None:
    """A heading is either a short line that IS a known heading ("Requirements",
    "Nice to have"), or "Known heading: ..." with the content after the colon."""
    raw = line.strip().strip("*#").strip()
    if not raw:
        return None
    has_colon = ":" in raw
    cand = _norm(raw.split(":", 1)[0]) if has_colon else _norm(raw)
    if not cand or len(cand.split()) > 7 or (not has_colon and len(raw) > 60):
        return None
    for kind, heads in (("ignore", IGNORE_HEAD), ("preferred", PREF_HEAD), ("required", REQ_HEAD),
                        ("responsibilities", RESP_HEAD)):
        for h in heads:
            if cand == h or (cand.startswith(h + " ") and len(cand) <= len(h) + 14 and (has_colon or raw.isupper())):
                return kind
    return None


_OR_CONN = re.compile(r"^\s*(?:,?\s*(?:or|and/or)|/)\s*$", re.IGNORECASE)
_COMMA_CONN = re.compile(r"^\s*,\s*$")


def _skill_groups(clause: str) -> list[list[str]]:
    """Skills in a clause, grouped when they're alternatives.

    We look at what sits *between* consecutive skill mentions:
      "/" or "or"   -> or-connector
      ","           -> list comma
      anything else -> break
    A run of skills joined only by commas/or-connectors whose LAST connector is
    "or" is one either-of group ("AWS, GCP, or Azure", "PyTorch/TensorFlow").
    A run ending in "and" or plain commas is separate requirements.
    """
    hits = find_skills(clause)
    parens = [m.span() for m in re.finditer(r"\([^()]*\)", clause)]
    inside = lambda a: any(p0 < a < p1 for p0, p1 in parens)
    all_spans = sorted((sp[0], sp[1], name) for name, h in hits.items() for sp in h.spans)
    spans = [x for x in all_spans if not inside(x[0])]
    examples = [x for x in all_spans if inside(x[0])]
    flat = re.sub(r"\([^()]*\)", lambda m: " " * len(m.group(0)), clause)   # connectors read outside parens
    clause = flat
    runs: list[tuple[list[str], list[str]]] = []      # (skills, connectors)
    prev_end = None
    for a, b, name in spans:
        between = clause[prev_end:a] if prev_end is not None else ""
        conn = "or" if _OR_CONN.match(between) else "comma" if _COMMA_CONN.match(between) else None
        if runs and prev_end is not None and conn:
            runs[-1][0].append(name)
            runs[-1][1].append(conn)
        else:
            runs.append(([name], []))
        prev_end = b

    groups: list[list[str]] = []
    seen: set[str] = set()
    # attach each "(example)" skill to the skill right before its parenthesis
    for a, _, name in examples:
        before = [x for x in spans if x[1] <= a]
        if before:
            host = before[-1][2]
            for skills, _c in runs:
                if host in skills and name not in skills:
                    skills.append(name)
                    _c.append("or" if not _c or _c[-1] == "or" else "comma")
                    break
        else:
            runs.append(([name], []))

    def add(g: list[str]):
        g = [x for x in dict.fromkeys(g) if x not in seen]
        if g:
            groups.append(g)
            seen.update(g)

    for skills, conns in runs:
        if conns and conns[-1] == "or":
            add(skills)
        else:
            # "AWS/GCP, Python, Docker": split at list commas; each "/"/"or"-joined piece is a group
            piece = [skills[0]]
            for sk, c in zip(skills[1:], conns):
                if c == "or":
                    piece.append(sk)
                else:
                    add(piece)
                    piece = [sk]
            add(piece)
    return groups


def guess_title(text: str) -> str:
    for line in text.splitlines()[:8]:
        l = line.strip(" \t-–|:•")
        if not l or len(l.split()) > 9 or len(l) < 3:
            continue
        low = l.lower()
        if low.startswith(("about", "we are", "job description", "location", "company", "http")):
            continue
        m = re.match(r"(?:job title|title|position|role)\s*[:\-]\s*(.+)", l, re.I)
        if m:
            return m.group(1).strip()
        if re.search(r"\b(engineer|developer|scientist|analyst|manager|intern|architect|lead|specialist|"
                     r"consultant|designer|researcher|administrator|officer|associate)\b", low):
            return l
    return ""


def parse_jd(text: str, title_override: str | None = None) -> ParsedJD:
    context = "required"   # text before any heading is usually the summary/requirements
    req: dict[str, Requirement] = {}
    degree_lines: list[tuple[str, str]] = []
    years: list[int] = []

    in_group: dict[str, str] = {}   # skill -> primary skill of its "or" group

    for line in text.splitlines():
        h = _classify_heading(line)
        if h:
            context = h
            rest = line.split(":", 1)[1] if ":" in line else ""
            if not rest.strip():
                continue
            line = rest
        if context == "ignore":
            continue
        # clause-level, so "Bachelor's required; Master's preferred" splits correctly
        # "(Master's preferred)" is its own clause; "(LoRA) is a plus" / "AWS (S3, Redshift)" are not
        line = re.sub(r"\(([^()]*)\)", lambda m: f"; {m.group(1)};" if PREF_CUES.search(m.group(1)) else m.group(0), line)
        for clause in re.split(r";|\.\s+|\.$", line):
            if not clause.strip():
                continue
            imp = "preferred" if (context == "preferred" or PREF_CUES.search(clause)) else "required"
            if imp == "required":
                years.extend(_years_in(clause))
            skill_clause = clause
            if degree_level(clause):
                degree_lines.append((clause, imp))
                skill_clause = FIELD_RE.sub(" ", clause)     # "BS in Statistics" is a degree field, not a skill
            for group in _skill_groups(skill_clause):
                primary = next((in_group[g] for g in group if g in in_group), group[0])
                r = req.get(primary)
                if r is None:
                    r = req[primary] = Requirement(primary, imp, 0, BY_NAME[primary].soft)
                for g in group:
                    in_group.setdefault(g, primary)
                    if g != primary and g not in r.alternatives and g not in req:
                        r.alternatives.append(g)
                r.count += 1
                if imp == "required":
                    r.importance = "required"

    deg, deg_pref, fields = None, False, []
    if degree_lines:
        # the lowest degree level mentioned in a required context is the bar;
        # a higher one mentioned as preferred ("Master's preferred") doesn't raise it
        # JD side uses the LOWEST level in each clause: "MS or PhD" means an MS clears the bar
        req_levels = [lv for l, imp in degree_lines if imp == "required" for lv in degree_levels(l)]
        all_levels = [lv for l, _ in degree_lines for lv in degree_levels(l)]
        if req_levels:
            deg = min(req_levels, key=lambda x: DEGREE_LEVELS[x])
        else:
            deg, deg_pref = min(all_levels, key=lambda x: DEGREE_LEVELS[x]), True
        for l, _ in degree_lines:
            fields.extend(f.lower() for f in FIELD_RE.findall(l))

    return ParsedJD(
        raw_text=text,
        title=(title_override or "").strip() or guess_title(text),
        requirements=sorted(req.values(), key=lambda r: (r.importance != "required", -r.count, r.skill)),
        min_years=float(min(years)) if years else None,
        degree_required=deg, degree_fields=sorted(set(fields)), degree_is_preferred=deg_pref,
    )
