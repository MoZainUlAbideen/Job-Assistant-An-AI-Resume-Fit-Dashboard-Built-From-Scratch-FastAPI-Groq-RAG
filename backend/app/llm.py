"""
Thin Groq wrapper. The LLM is used for ONE thing in v2: proposing bullet
rewrites. Scoring never touches it (see scoring.py), and every proposal is
checked by tailor.verify_edit() before it's allowed into the resume.

Model note: v1 hard-coded `llama-3.3-70b-versatile`, which Groq shut down on
2026-08-16 -- so v1 can no longer make LLM calls at all. The model is now an
env var (GROQ_MODEL) so the next deprecation is a config change, not a code change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

log = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-oss-120b"
_client = None
_cache: dict[str, dict] = {}


class LLMUnavailable(RuntimeError):
    pass


def available() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def model_name() -> str:
    return os.getenv("GROQ_MODEL", DEFAULT_MODEL)


def _get_client():
    global _client
    if _client is None:
        if not available():
            raise LLMUnavailable("GROQ_API_KEY is not set")
        from groq import Groq
        _client = Groq(timeout=45.0, max_retries=1)
    return _client


def chat_json(system: str, user: str, max_tokens: int = 3000) -> dict:
    """JSON-mode completion, temperature 0, memoised per process so the same
    request returns the same answer (re-tailoring the same resume+JD is stable)."""
    model = model_name()
    key = hashlib.sha256(f"{model}\n{system}\n{user}".encode()).hexdigest()
    if key in _cache:
        return _cache[key]

    kwargs = dict(
        model=model, temperature=0, max_completion_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    if model.startswith("openai/gpt-oss"):
        kwargs["reasoning_effort"] = "low"     # rewrite task doesn't need long reasoning; keeps latency down
    try:
        resp = _get_client().chat.completions.create(**kwargs)
    except LLMUnavailable:
        raise
    except Exception as e:  # network, rate limit, bad model id...
        log.warning("Groq call failed: %s", e)
        raise LLMUnavailable(f"LLM call failed: {type(e).__name__}: {str(e)[:200]}") from e

    content = (resp.choices[0].message.content or "").strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise LLMUnavailable("LLM returned invalid JSON") from e
    if len(_cache) > 256:
        _cache.clear()
    _cache[key] = data
    return data
