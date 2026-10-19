"""Keyword matcher: the boundary bugs v1 had, and the English-word traps."""
import pytest

from app.skills import find_skills, implied_evidence


def names(text):
    return set(find_skills(text))


@pytest.mark.parametrize("text,expected,forbidden", [
    # v1 bug: substring matching ("r" in "pytorch", "java" in "javascript")
    ("PyTorch and JavaScript", {"PyTorch", "JavaScript"}, {"R", "Java"}),
    ("C/C++ and C#", {"C", "C++", "C#"}, set()),
    ("Node.js, Next.js", {"Node.js", "Next.js"}, set()),
    ("React Native apps", {"React Native"}, {"React"}),
    ("GitHub Actions pipelines", {"GitHub Actions"}, {"Git"}),
    # single-letter / common-word languages only in list context
    ("Python, R, SQL and Go", {"Python", "R", "SQL", "Go"}, set()),
    ("Our R&D team will go to market", set(), {"R", "Go"}),
    # English words that are also skills
    ("react quickly, excel at work, the rest of the team, spring 2024", set(),
     {"React", "Excel", "REST APIs", "Spring Boot"}),
    ("Please upload your CV", set(), {"Computer Vision"}),
    ("Built REST APIs with React", {"REST APIs", "React"}, set()),
    # aliases normalise to one canonical name
    ("ML with sklearn and k8s", {"Machine Learning", "Scikit-learn", "Kubernetes"}, set()),
    ("large language models and retrieval-augmented generation", {"LLMs", "RAG"}, set()),
])
def test_matching(text, expected, forbidden):
    found = names(text)
    assert expected <= found, f"missing {expected - found}"
    assert not (forbidden & found), f"false positive {forbidden & found}"


def test_counts_and_sentence_end():
    hits = find_skills("Python. More python here, and Python3!")
    assert hits["Python"].count == 3


def test_implied_evidence_is_transitive_and_specific():
    present = {"PyTorch", "LangChain"}
    assert implied_evidence("Deep Learning", present) == ["PyTorch"]
    assert implied_evidence("LLMs", present) == ["LangChain"]
    # Generative AI <- LLMs <- LangChain (two hops)
    assert implied_evidence("Generative AI", present) == ["LangChain"]
    # nothing implies "AI Agents" from just LangChain -- that's the v1 fabrication
    assert implied_evidence("AI Agents", present) == []
