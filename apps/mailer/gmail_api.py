import os
import base64
import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TOKEN_PATH = Path("token.json")
CREDS_PATH = Path("credentials.json")


def get_gmail_service():
    creds = None

    # Render / production: token stored as base64 env var
    token_b64 = os.getenv("GMAIL_TOKEN_B64")
    if token_b64:
        token_data = json.loads(base64.b64decode(token_b64).decode())
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)

    # Local dev: read token.json
    elif TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Persist refreshed token locally
        if not token_b64 and TOKEN_PATH.exists():
            TOKEN_PATH.write_text(creds.to_json())

    if not creds or not creds.valid:
        raise RuntimeError(
            "Gmail credentials not found or invalid. "
            "Run: python manage.py gmail_auth"
        )

    return build("gmail", "v1", credentials=creds)
