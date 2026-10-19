"""Resume parser, JD parser and scorer on the synthetic fixtures."""
from pathlib import Path

import pytest

from app.extract import Extracted
from app.jd_parser import parse_jd
from app.resume_parser import months_in_ranges, parse_resume
from app.scoring import score

FIX = Path(__file__).parent / "fixtures"
RESUME = (FIX / "resume_ayesha.txt").read_text(encoding="utf-8")
JD = (FIX / "jd_mle.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def resume():
    return parse_resume(RESUME)


@pytest.fixture(scope="module")
def jd():
    return parse_jd(JD)


def test_resume_sections_and_bullets(resume):
    assert resume.section_order == ["summary", "experience", "projects", "education", "skills"]
    work = [b for b in resume.bullets if b.section in ("experience", "projects")]
    assert len(work) == 7
    assert work[-1].text.startswith("Containerized the API")
    assert work[0].entry.startswith("ML Engineer | DataWorks")


def test_resume_contact_degree_years(resume):
    assert resume.email == "ayesha.khan@example.com"
    assert resume.phone and resume.has_linkedin and resume.has_github
    assert resume.degree_level == "bachelor"
    # Jan 2022–Dec 2023 (23 months) + Jun–Aug 2021 (2 months); education years NOT counted
    assert resume.experience_months == 25


@pytest.mark.parametrize("text,months", [
    ("Jan 2020 - Jan 2021", 12),
    ("2019 – 2021", 24),
    ("Mar 2020 – Present", None),            # depends on today; just must be > 0
    ("Jan 2020 - Dec 2020\nJun 2020 - Mar 2021", 14),   # overlap merged
    ("Summer 2024", 3),
    ("06/2023 - 09/2023", 3),
])
def test_date_ranges(text, months):
    got = months_in_ranges(text)
    assert got > 0 if months is None else got == months


def test_jd_requirements(jd):
    req = {r.label: r.importance for r in jd.requirements}
    assert req["PyTorch or TensorFlow"] == "required"     # either satisfies
    assert req["AWS or GCP or Azure"] == "preferred"
    assert req["Kubernetes"] == "preferred"               # "About us" mention ignored
    assert req["Airflow"] == "preferred"                  # "is a plus"
    assert req["Docker"] == req["SQL"] == req["RAG"] == "required"
    assert "Spark" not in req                             # benefits boilerplate ignored
    assert jd.min_years == 3
    assert jd.degree_required == "bachelor" and not jd.degree_is_preferred   # Master's is only preferred
    assert jd.title.startswith("Senior Machine Learning Engineer")


def test_score_is_deterministic_and_explained(resume, jd):
    doc = Extracted(text=RESUME, file_type="txt")
    a, b = score(doc, resume, jd), score(doc, resume, jd)
    assert a.score == b.score
    kw = {k.keyword: k for k in a.keywords}
    assert kw["PyTorch or TensorFlow"].status == "matched"
    assert kw["Deep Learning"].status == "implied" and kw["Deep Learning"].evidence == ["PyTorch"]
    assert kw["LLMs"].status == "implied"                 # Groq/Hugging Face/FAISS project, no literal "LLM"
    assert kw["Kubernetes"].status == "missing"
    assert kw["Docker"].in_skills_section and kw["Docker"].in_experience
    assert a.components["title"]["score"] == 1.0 * 100    # "Machine Learning Engineer" after dropping "Senior"
    assert a.components["experience"]["score"] < 100      # ~2.1 yrs vs 3+
    assert any("Experience" in k for k in a.knockouts)
    assert 40 < a.score < 95


def test_more_keywords_never_lowers_score(resume, jd):
    """Monotonicity: adding a missing JD keyword to the resume must not reduce the score."""
    doc = Extracted(text=RESUME, file_type="txt")
    base = score(doc, resume, jd).score
    better_text = RESUME.replace("Tools: Docker", "Tools: Kubernetes, Docker")
    better = score(Extracted(text=better_text, file_type="txt"), parse_resume(better_text), jd).score
    assert better > base


def test_unrelated_resume_scores_low(jd):
    text = ("Sara Ali\nsara@example.com\nExperience\nChef | Cafe 2019 - 2023\n• Cooked meals for 200 guests daily.\n"
            "Education\nDiploma in Culinary Arts\nSkills\nCooking, menu planning")
    rep = score(Extracted(text=text, file_type="txt"), parse_resume(text), jd)
    assert rep.score < 30


@pytest.mark.parametrize("jd_title,expected", [
    ("AI/ML Engineer", 0.5),                      # v1-era bug: was cut to "ai" and matched everything
    ("Machine Learning Engineer (Remote)", 1.0),
    ("Senior Machine Learning Engineer - Platform Team", 1.0),
    ("Data Engineer", 0.0),
    ("Frontend Developer, Lahore", 0.0),
])
def test_title_match(resume, jd_title, expected):
    from app.scoring import title_match
    assert title_match(jd_title, resume) == expected
