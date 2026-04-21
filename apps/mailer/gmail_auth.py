import base64
from pathlib import Path
from django.core.management.base import BaseCommand
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


class Command(BaseCommand):
    help = "One-time OAuth2 flow to generate token.json for Gmail API"

    def handle(self, *args, **options):
        creds_path = Path("credentials.json")
        if not creds_path.exists():
            self.stderr.write(
                "credentials.json not found in project root.\n"
                "Download it from Google Cloud Console → APIs & Services → Credentials"
            )
            return

        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        creds = flow.run_local_server(port=0)

        token_path = Path("token.json")
        token_path.write_text(creds.to_json())

        b64 = base64.b64encode(token_path.read_bytes()).decode()

        self.stdout.write(self.style.SUCCESS("token.json saved."))
        self.stdout.write("\nFor Render — add this as env var GMAIL_TOKEN_B64:\n")
        self.stdout.write(b64)
