"""
Data shapes used across the app.

Why Pydantic: it validates that data coming out of the LLM (which is just text,
even when we ask for JSON) actually matches the shape our code expects, and
rejects/errors loudly if the model returns something malformed. Never trust
LLM output as if it were a typed function return -- validate it first.
"""
from pydantic import BaseModel, Field
from typing import Optional


class ExperienceBullet(BaseModel):
    company: str
    role: str
    bullet_text: str          # the raw achievement/responsibility line
    order_index: int          # position in the resume, preserved for display


class ParsedResume(BaseModel):
    raw_text: str                          # full extracted text, kept for reference/debug
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceBullet] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    years_experience_estimate: Optional[float] = None


class ParsedJob(BaseModel):
    raw_text: str
    title: str
    company: Optional[str] = None
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class SkillGap(BaseModel):
    skill: str
    severity: str              # "missing" | "weak_match" (see matching_engine.py for definitions)
    closest_resume_bullet: Optional[str] = None
    closest_similarity: Optional[float] = None


class BulletSuggestion(BaseModel):
    original_bullet: str
    suggested_rewrite: str
    target_skill: str          # which JD requirement this rewrite targets


class MatchResult(BaseModel):
    fit_score: float                       # 0-100
    matched_skills: list[str]
    gaps: list[SkillGap]
    suggestions: list[BulletSuggestion]
