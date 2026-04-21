import pdfplumber
import json
import os
from groq import Groq

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def extract_cv_text(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def parse_cv(pdf_path: str) -> dict:
    text = extract_cv_text(pdf_path)
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
