try:
    import pdfplumber
except ImportError:
    pdfplumber = None

import json
import io
from utils.llm import groq_call


def extract_text_from_bytes(pdf_bytes):
    if pdfplumber is None:
        return ""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def parse_cv_bytes(pdf_bytes):
    text = extract_text_from_bytes(pdf_bytes)
    response = groq_call(
        messages=[{
            "role": "user",
            "content": f"""Extract info from this CV and return ONLY valid JSON:
{{
  "name": "",
  "email": "",
  "phone": "",
  "skills": [],
  "experience": [],
  "education": [],
  "summary": ""
}}

CV text:
{text}"""
        }],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def parse_cv(pdf_path):
    with open(pdf_path, "rb") as f:
        return parse_cv_bytes(f.read())


def extract_cv_text(pdf_path):
    with open(pdf_path, "rb") as f:
        return extract_text_from_bytes(f.read())