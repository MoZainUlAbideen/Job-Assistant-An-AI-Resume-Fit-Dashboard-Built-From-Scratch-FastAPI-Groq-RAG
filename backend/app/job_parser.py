"""
Job description parsing: raw JD text (captured by the browser extension)
-> structured ParsedJob.

Same "constrained JSON extraction" pattern as resume_parser.py. The one
domain-specific judgment call: separating required vs nice-to-have skills.
JDs rarely label these cleanly, so we ask the model to use signal words
("must have", "required", "3+ years" -> required; "bonus", "plus",
"preferred" -> nice-to-have) and default to required when genuinely
ambiguous, since under-crediting a gap is safer than hiding one from the user.
"""
import json
from groq import Groq
from app.schemas import ParsedJob

client = Groq()
MODEL = "llama-3.3-70b-versatile"

EXTRACTION_PROMPT = """Extract structured data from this job posting.
Return ONLY valid JSON, no markdown fences, no commentary.

Schema:
{{
  "title": "string",
  "company": "string or null",
  "required_skills": ["string", ...],       // explicitly required or clearly implied as mandatory
  "nice_to_have_skills": ["string", ...],    // explicitly optional/bonus/preferred
  "responsibilities": ["string", ...]
}}

When a skill's status is ambiguous, classify it as required rather than nice-to-have.

Job posting text:
---
{jd_text}
---

Return the JSON now.
"""


def parse_job(raw_text: str) -> ParsedJob:
    response = client.chat.completions.create(
        model=MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(jd_text=raw_text)}],
        response_format={"type": "json_object"},
    )
    text_out = response.choices[0].message.content.strip()
    data = json.loads(text_out)

    return ParsedJob(
        raw_text=raw_text,
        title=data.get("title", "Unknown Title"),
        company=data.get("company"),
        required_skills=data.get("required_skills", []),
        nice_to_have_skills=data.get("nice_to_have_skills", []),
        responsibilities=data.get("responsibilities", []),
    )
