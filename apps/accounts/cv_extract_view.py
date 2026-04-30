"""
Add this endpoint to apps/accounts/views.py
Also add to apps/accounts/urls.py:
    path("onboarding/extract-cv/", views.extract_cv_view, name="extract_cv"),
"""

# ── CV Extraction via Anthropic API ───────────────────────────────────────────

import json
import base64

@login_required
@require_POST
def extract_cv_view(request):
    """
    Receives a CV file upload, sends it to Anthropic Claude for extraction,
    returns structured JSON with pre-filled profile fields.
    """
    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"ok": False, "error": "No file provided."})

    file_bytes = f.read()
    mime_type  = f.content_type or "application/octet-stream"

    # Only PDFs and images can be sent directly; docx we convert to text via pdfminer fallback
    if "pdf" not in mime_type and "image" not in mime_type:
        # Try to extract text from docx
        try:
            import docx2txt, io
            text = docx2txt.process(io.BytesIO(file_bytes))
        except Exception:
            text = file_bytes.decode("utf-8", errors="ignore")
        content_block = {"type": "text", "text": f"The following is the text content of a CV/Resume:\n\n{text[:8000]}"}
    else:
        b64 = base64.standard_b64encode(file_bytes).decode("utf-8")
        if "pdf" in mime_type:
            content_block = {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64}
            }
        else:
            content_block = {
                "type": "image",
                "source": {"type": "base64", "media_type": mime_type, "data": b64}
            }

    PROMPT = """Extract all information from this CV/Resume and return ONLY a JSON object with exactly this structure. 
Do not include any text before or after the JSON. Do not use markdown code fences.

{
  "first_name": "",
  "last_name": "",
  "phone": "",
  "location": "",
  "occupation": "",
  "years_experience": "",
  "bio": "",
  "linkedin_url": "",
  "github_url": "",
  "portfolio_url": "",
  "work_experiences": [
    {
      "job_title": "",
      "company": "",
      "location": "",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD or null",
      "is_current": false,
      "description": ""
    }
  ],
  "educations": [
    {
      "institution": "",
      "qualification": "",
      "field_of_study": "",
      "nqf_level": "",
      "start_year": 0,
      "end_year": 0,
      "is_current": false,
      "description": ""
    }
  ],
  "skills": [
    {"name": "", "level": "beginner|intermediate|advanced|expert", "category": ""}
  ],
  "languages": [
    {"name": "", "proficiency": "basic|conversational|professional|native"}
  ],
  "references": [
    {"name": "", "company": "", "position": "", "email": "", "phone": ""}
  ]
}

Rules:
- years_experience must be one of: "0-1", "1-2", "3-5", "5-10", "10+" or empty string
- nqf_level must be one of: "4","5","6","7","8","9","10","other" or empty string
- For dates use YYYY-MM-DD format; if only year known use YYYY-01-01
- For skills, infer the level from context (tools used professionally = advanced, listed as familiar = intermediate)
- If a field cannot be determined, use empty string or null
- Return all work experiences, education entries, skills, languages, and references you can find
"""

    try:
        import httpx
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type":      "application/json",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model":      "claude-opus-4-6",
                "max_tokens": 4096,
                "messages": [
                    {
                        "role":    "user",
                        "content": [content_block, {"type": "text", "text": PROMPT}]
                    }
                ]
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_text = data["content"][0]["text"].strip()
        # Strip accidental markdown fences
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        extracted = json.loads(raw_text)
        return JsonResponse({"ok": True, "data": extracted})

    except json.JSONDecodeError as e:
        return JsonResponse({"ok": False, "error": f"Parse error: {e}"})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})
