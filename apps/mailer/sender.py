import base64
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from groq import Groq
from apps.mailer.gmail_api import get_gmail_service

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def generate_cover_letter(cv_data: dict, job: dict) -> str:
    r = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{
            "role": "user",
            "content": f"""Write a professional job application email body (200 words max).

Applicant: {cv_data.get('name')}
Skills: {', '.join(cv_data.get('skills', [])[:8])}
Summary: {cv_data.get('summary', '')}
Applying for: {job.get('title')} at {job.get('company')}
Job info: {str(job.get('description', ''))[:400]}

Write the email body only. No subject line. Professional and concise."""
        }]
    )
    return r.choices[0].message.content


def send_application(cv_data: dict, job: dict, pdf_bytes: bytes, pdf_filename: str = "CV.pdf"):
    email_to = job.get("apply_email", "").strip()
    if not email_to:
        return False, "No email address"
    if not pdf_bytes:
        return False, "CV file not available — please re-upload your CV"

    cover_letter = generate_cover_letter(cv_data, job)
    sender = os.getenv("GMAIL_ADDRESS")

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = email_to
    msg["Subject"] = f"Application: {job.get('title')} — {cv_data.get('name')}"
    msg.attach(MIMEText(cover_letter, "plain"))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    safe_name = cv_data.get("name", "Applicant").replace(" ", "_")
    part.add_header("Content-Disposition", f"attachment; filename=CV_{safe_name}.pdf")
    msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    try:
        service = get_gmail_service()
        service.users().messages().send(
            userId="me",
            body={"raw": raw}
        ).execute()
        return True, cover_letter
    except Exception as e:
        return False, str(e)
