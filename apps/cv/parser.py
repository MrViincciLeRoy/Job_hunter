import pdfplumber
import json
import io
import os
from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def extract_text_from_bytes(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def parse_cv_bytes(pdf_bytes: bytes) -> dict:
    text = extract_text_from_bytes(pdf_bytes)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
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


# backward compat for any code still using file path
def parse_cv(pdf_path: str) -> dict:
    with open(pdf_path, "rb") as f:
        return parse_cv_bytes(f.read())


def extract_cv_text(pdf_path: str) -> str:
    with open(pdf_path, "rb") as f:
        return extract_text_from_bytes(f.read())
