"""
The core matching pipeline: ParsedResume + ParsedJob -> MatchResult.

THEORY: the gap-detection algorithm
------------------------------------
For every skill the JD requires, we need one of three verdicts:
  MATCHED      - resume clearly demonstrates this (exact skill-list hit,
                 OR a resume bullet is semantically very close to it)
  WEAK_MATCH   - resume has *something* related, but not a strong signal
  MISSING      - nothing in the resume is close to this at all

We use two signals together rather than just one, because each has a
different failure mode:
  - Exact/substring match on the parsed `skills` list catches the common
    case cheaply (JD says "Python", resume skills list says "Python").
  - Embedding similarity against resume BULLETS catches the case exact
    match misses entirely -- e.g. JD wants "CI/CD experience" and the
    resume never uses that phrase but has a bullet describing exactly that
    work. This is the whole reason we don't just do keyword matching.

Thresholds (0.55 / 0.40) are a starting point tuned by feel, not a proof --
in a real system you'd validate/tune these against a labeled sample of
resume/JD pairs where you know the "correct" verdict.

THEORY: why the rewrite step is GROUNDED, not free generation
----------------------------------------------------------------
If you just ask an LLM "rewrite this resume to match this job," it will
happily invent tools and achievements the person never had -- because its
only goal is producing text that looks like a good match, and it has no
built-in mechanism to distinguish "true" from "sounds right." That's a
real problem for a resume tool: shipping a system that quietly encourages
users to lie on their resume is bad output, not a growth feature.

We prevent this by constraining what the model is ALLOWED to work with:
we give it ONE real resume bullet (verbatim, from the user's actual
resume) and ONE target skill, and instruct it to rephrase using only
what's already implied by that bullet -- closer to "editing for emphasis"
than "writing fiction." It's not a perfect guarantee (LLMs can still
embellish), but constraining the input space is the standard mitigation,
and we additionally ask the model to flag if it *can't* honestly connect
the bullet to the skill -- which we then just skip.
"""
import json
from groq import Groq
from app.schemas import ParsedResume, ParsedJob, MatchResult, SkillGap, BulletSuggestion
from app.embeddings import BulletIndex

client = Groq()
MODEL = "llama-3.3-70b-versatile"

MATCH_THRESHOLD = 0.55   # semantic similarity above this -> treat as matched
WEAK_THRESHOLD = 0.40    # between weak and match thresholds -> weak_match; below -> missing


def _skill_in_list(skill: str, skills_list: list[str]) -> bool:
    skill_l = skill.lower()
    return any(skill_l in s.lower() or s.lower() in skill_l for s in skills_list)


def score_and_find_gaps(resume: ParsedResume, job: ParsedJob) -> tuple[float, list[str], list[SkillGap]]:
    bullet_texts = [b.bullet_text for b in resume.experience]
    index = BulletIndex(bullet_texts) if bullet_texts else None

    matched: list[str] = []
    gaps: list[SkillGap] = []

    all_required = job.required_skills  # weight required skills only into the score; nice-to-haves are informational
    for skill in all_required:
        if _skill_in_list(skill, resume.skills):
            matched.append(skill)
            continue

        if index:
            closest = index.closest(skill, k=1)
        else:
            closest = []

        if closest and closest[0][1] >= MATCH_THRESHOLD:
            matched.append(skill)
        elif closest and closest[0][1] >= WEAK_THRESHOLD:
            gaps.append(SkillGap(
                skill=skill, severity="weak_match",
                closest_resume_bullet=closest[0][0], closest_similarity=closest[0][1],
            ))
        else:
            gaps.append(SkillGap(
                skill=skill, severity="missing",
                closest_resume_bullet=closest[0][0] if closest else None,
                closest_similarity=closest[0][1] if closest else None,
            ))

    fit_score = round(100 * len(matched) / max(len(all_required), 1), 1)
    return fit_score, matched, gaps


REWRITE_PROMPT = """You are helping a job applicant surface relevant experience they
ALREADY have -- you are not writing new claims for them.

Target skill the job wants: "{skill}"
Their actual resume bullet (verbatim, do not fabricate beyond this): "{bullet}"

If this bullet genuinely relates to the target skill, rewrite it to surface
that connection more clearly, using only what the bullet already implies.
Do not add tools, metrics, or outcomes that aren't in the original.

If the bullet does NOT genuinely relate to the target skill, respond with
exactly: NO_HONEST_CONNECTION

Respond with ONLY the rewritten bullet text, or NO_HONEST_CONNECTION. No other text.
"""


def generate_suggestions(gaps: list[SkillGap], max_suggestions: int = 3) -> list[BulletSuggestion]:
    suggestions = []
    # Only attempt rewrites for weak_match gaps -- for a true "missing" gap there's
    # no honest bullet to ground a rewrite in, so we don't try to paper over it.
    candidates = [g for g in gaps if g.severity == "weak_match" and g.closest_resume_bullet]
    for gap in candidates[:max_suggestions]:
        prompt = REWRITE_PROMPT.format(skill=gap.skill, bullet=gap.closest_resume_bullet)
        response = client.chat.completions.create(
            model=MODEL, max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        result = response.choices[0].message.content.strip()
        if result != "NO_HONEST_CONNECTION":
            suggestions.append(BulletSuggestion(
                original_bullet=gap.closest_resume_bullet,
                suggested_rewrite=result,
                target_skill=gap.skill,
            ))
    return suggestions


def match(resume: ParsedResume, job: ParsedJob) -> MatchResult:
    fit_score, matched, gaps = score_and_find_gaps(resume, job)
    suggestions = generate_suggestions(gaps)
    return MatchResult(
        fit_score=fit_score,
        matched_skills=matched,
        gaps=gaps,
        suggestions=suggestions,
    )
