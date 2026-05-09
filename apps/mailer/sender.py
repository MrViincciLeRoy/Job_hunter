import base64
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from utils.llm import groq_call
from apps.mailer.gmail_api import get_gmail_service
from apps.mailer.doc_resolver import resolve_documents, check_size_limit
from apps.mailer.qualification_check import run_qualification_check

GOV_PLATFORMS = {"dpsa", "sayouth", "essa", "govza"}

# Pulled from application_policy.md — injected verbatim into cover letter prompt
_COVER_LETTER_POLICY = """
COVER LETTER RULES (follow strictly):
- Personalise with: applicant name, exact job title, reference number (if any), department/company name.
- Reference specific skills and experience that match the job requirements.
- For government posts: mention NQF level, years of relevant experience, and any required software/systems.
- For SMS-level posts (salary level 11+): include a line confirming completion or enrolment in the Nyukela SMS Pre-entry Programme.
- Length: exactly 3-4 paragraphs. Professional tone. No filler or fluff.
- Close with full contact details: name, email, phone.
- Output the email body ONLY. No subject line. No markdown.
""".strip()


def _is_gov(job) -> bool:
    return (job.platform or "").lower() in GOV_PLATFORMS


def _is_sms_level(job) -> bool:
    import re
    m = re.search(r"level\s+(1[1-9]|[2-9]\d)", (job.description or "").lower())
    return bool(m)


def generate_cover_letter(cv_data: dict, job) -> str:
    is_government = _is_gov(job)
    ref_no        = getattr(job, "reference_no", "") or ""
    ref_line      = f"Reference Number: {ref_no}" if ref_no else "No reference number provided"
    sms_note      = (
        "\nNote: This appears to be an SMS-level post. Include a line about Nyukela SMS Pre-entry Programme."
        if _is_sms_level(job) else ""
    )

    prompt = f"""{_COVER_LETTER_POLICY}
{sms_note}

APPLICANT:
Name: {cv_data.get('name', '')}
Email: {cv_data.get('email', '')}
Phone: {cv_data.get('phone', '')}
Skills: {', '.join(cv_data.get('skills', [])[:10])}
Summary: {cv_data.get('summary', '')}
Experience: {str(cv_data.get('experience', []))[:400]}
Education: {str(cv_data.get('education', []))[:300]}

JOB:
Title: {job.title}
{'Department' if is_government else 'Company'}: {job.company}
{ref_line}
Platform: {job.platform}
Description (first 600 chars): {str(job.description or '')[:600]}
"""

    r = groq_call(messages=[{"role": "user", "content": prompt}])
    return r.choices[0].message.content.strip()


def build_application_summary(user, job) -> dict:
    """
    Pre-flight check. Call this from the view to show the user what will happen before sending.
    Returns a dict with qualification results, doc list, size, and whether it can proceed.
    """
    qual   = run_qualification_check(user, job)
    docs   = resolve_documents(user, job)
    ok, mb = check_size_limit(docs["attachments"])

    mandatory_missing = [d for d in docs["missing"] if d[2]]

    return {
        "qualification":  qual,
        "documents":      docs,
        "size_mb":        mb,
        "size_ok":        ok,
        "can_proceed":    (
            not qual["disqualified"]
            and not mandatory_missing
            and ok
        ),
        "blocking_reasons": (
            (["Disqualified — see qualification check"] if qual["disqualified"] else [])
            + [f"Missing mandatory doc: {label}" for _, label, _ in mandatory_missing]
            + ([f"Attachments too large: {mb:.1f} MB (limit 10 MB)"] if not ok else [])
        ),
    }


def send_application(user, cv_data: dict, job, force: bool = False) -> tuple[bool, str]:
    """
    Full application pipeline:
      1. Guard checks (email, duplicate handled upstream)
      2. Qualification check
      3. Document resolution
      4. Size check
      5. Cover letter generation (policy-aware)
      6. Multi-attachment Gmail send

    force=True bypasses DISQUALIFY gate (use only after user explicitly confirms).
    Returns (success: bool, message: str).
    """
    # ── Email address guard ───────────────────────────────────────────────────
    email_to = (job.apply_email or "").strip()
    if not email_to:
        return False, "No apply email on this job."

    # ── Qualification check ───────────────────────────────────────────────────
    qual = run_qualification_check(user, job)
    if qual["disqualified"] and not force:
        reasons = []
        if qual["education"]["status"] == "❌":
            reasons.append(qual["education"]["reason"])
        if qual["experience"]["status"] == "❌":
            reasons.append(qual["experience"]["reason"])
        if qual["skills"]["status"] == "❌":
            reasons.append(f"Skills match {qual['skills']['score']}% (minimum 40%)")
        return False, "DISQUALIFIED: " + "; ".join(reasons)

    # ── Document resolution ───────────────────────────────────────────────────
    docs = resolve_documents(user, job)
    mandatory_missing = [(dt, label) for dt, label, mandatory in docs["missing"] if mandatory]
    if mandatory_missing:
        lines = [f"  • {label}" for _, label in mandatory_missing]
        return False, "Missing mandatory documents:\n" + "\n".join(lines)

    attachments = docs["attachments"]
    if not attachments:
        return False, "No CV found — please upload one first."

    # ── Size check ────────────────────────────────────────────────────────────
    ok, mb = check_size_limit(attachments)
    if not ok:
        return False, f"Attachments too large: {mb:.1f} MB (limit 10 MB). Remove some documents."

    # ── Cover letter ──────────────────────────────────────────────────────────
    cover_letter = generate_cover_letter(cv_data, job)
    sender       = os.getenv("GMAIL_ADDRESS")
    applicant    = cv_data.get("name", "Applicant")

    # ── Subject line — include reference number for gov posts ─────────────────
    ref_no = getattr(job, "reference_no", "") or ""
    if ref_no:
        subject = f"Application: {job.title} ({ref_no}) — {applicant}"
    else:
        subject = f"Application: {job.title} — {applicant}"

    # ── Build MIME email ──────────────────────────────────────────────────────
    msg = MIMEMultipart()
    msg["From"]    = sender
    msg["To"]      = email_to
    msg["Subject"] = subject
    msg.attach(MIMEText(cover_letter, "plain"))

    for doc, safe_name in attachments:
        mime_type  = doc.mime_type or "application/octet-stream"
        mime_parts = mime_type.split("/", 1)
        mime_main  = mime_parts[0]
        mime_sub   = mime_parts[1] if len(mime_parts) > 1 else "octet-stream"
        part = MIMEBase(mime_main, mime_sub)
        part.set_payload(bytes(doc.file_data))
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{safe_name}"')
        msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    # ── Send via Gmail API ────────────────────────────────────────────────────
    try:
        service = get_gmail_service()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        attached_names = ", ".join(name for _, name in attachments)
        return True, cover_letter + f"\n\n[Attached: {attached_names}]"
    except Exception as e:
        return False, str(e)
