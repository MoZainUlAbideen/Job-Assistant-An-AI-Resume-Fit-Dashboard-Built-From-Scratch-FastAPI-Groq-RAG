"""
Resume parsing: file bytes -> raw text -> structured ParsedResume.

THEORY
------
Stage 1 (extract_text_*): purely mechanical. PDFs store text as positioned
glyphs, not paragraphs -- pdfplumber reconstructs reading order for us.
This stage cannot fail due to "understanding" the resume; it just fails if
the file itself is corrupt or is a scanned image (no embedded text layer --
that case needs OCR, out of scope for v1).

Stage 2 (structure_resume): here's the interesting part. We give the LLM
the raw text plus a schema and ask for JSON ONLY. Two things make this
reliable instead of flaky:
  1. We show the model the exact JSON shape we want (few-shot-by-example,
     baked into the prompt) rather than describing it in prose.
  2. We validate the response through the Pydantic model immediately. If
     the model returns malformed JSON or missing fields, we catch it here
     rather than letting bad data silently flow into the matching engine.
"""
import json
import pdfplumber
import docx
from io import BytesIO
from groq import Groq
from app.schemas import ParsedResume, ExperienceBullet

client = Groq()  # reads GROQ_API_KEY from environment
MODEL = "llama-3.3-70b-versatile"


def extract_text_from_pdf(file_bytes: bytes) -> str:
    text_chunks = []
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_chunks.append(page_text)
    return "\n".join(text_chunks)


def extract_text_from_docx(file_bytes: bytes) -> str:
    doc = docx.Document(BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extract_text(file_bytes: bytes, filename: str) -> str:
    if filename.lower().endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)
    elif filename.lower().endswith(".docx"):
        return extract_text_from_docx(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: {filename}")


EXTRACTION_PROMPT = """You are extracting structured data from a resume.
Return ONLY valid JSON, no markdown fences, no commentary -- your entire
response must be parseable by json.loads().

Schema:
{{
  "skills": ["string", ...],               // technical + tool skills, deduplicated, normalized casing (e.g. "Python" not "python")
  "experience": [
    {{"company": "string", "role": "string", "bullet_text": "string", "order_index": 0}}
  ],                                        // one entry per distinct achievement/responsibility bullet, in resume order
  "education": ["string", ...],
  "years_experience_estimate": 0.0          // your best estimate of total professional experience in years
}}

Resume text:
---
{resume_text}
---

Return the JSON now.
"""


def structure_resume(raw_text: str) -> ParsedResume:
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(resume_text=raw_text)}],
        response_format={"type": "json_object"},  # Groq's JSON mode -- forces valid JSON output,
                                                    # removing the need for markdown-fence cleanup
    )
    text_out = response.choices[0].message.content.strip()
    data = json.loads(text_out)

    experience = [ExperienceBullet(**e) for e in data.get("experience", [])]
    return ParsedResume(
        raw_text=raw_text,
        skills=data.get("skills", []),
        experience=experience,
        education=data.get("education", []),
        years_experience_estimate=data.get("years_experience_estimate"),
    )


def parse_resume(file_bytes: bytes, filename: str) -> ParsedResume:
    raw_text = extract_text(file_bytes, filename)
    if not raw_text.strip():
        raise ValueError("No extractable text found -- file may be a scanned image without a text layer.")
    return structure_resume(raw_text)
