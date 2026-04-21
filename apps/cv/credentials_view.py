import json
import base64
import os
import threading
from pathlib import Path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

CREDS_PATH = Path("credentials.json")
TOKEN_PATH = Path("token.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _creds_status():
    if CREDS_PATH.exists():
        try:
            data = json.loads(CREDS_PATH.read_text())
            info = data.get("installed") or data.get("web") or {}
            client_id = info.get("client_id", "")
            short = client_id[:20] + "..." if len(client_id) > 20 else client_id
            return {"cls": "ok", "icon": "✓", "title": "credentials.json found", "detail": f"Client ID: {short}"}
        except Exception:
            return {"cls": "fail", "icon": "✗", "title": "credentials.json found but invalid", "detail": "File could not be parsed as JSON."}
    if os.getenv("GMAIL_TOKEN_B64"):
        return {"cls": "ok", "icon": "✓", "title": "Token found in environment", "detail": "GMAIL_TOKEN_B64 env var is set."}
    return None


def credentials_view(request):
    if request.method == "POST":
        mode = request.POST.get("mode")

        if mode == "file":
            f = request.FILES.get("credentials_file")
            if not f:
                messages.error(request, "No file selected.")
                return redirect("credentials")
            try:
                content = f.read().decode("utf-8")
                parsed = json.loads(content)
                if "installed" not in parsed and "web" not in parsed:
                    raise ValueError("Not a valid credentials.json (missing 'installed' or 'web' key)")
                CREDS_PATH.write_text(content)
                messages.success(request, "✓ credentials.json saved! Now click 'Run Gmail Auth' to authorize.")
            except (json.JSONDecodeError, ValueError) as e:
                messages.error(request, f"Invalid JSON: {e}")
            except Exception as e:
                messages.error(request, f"Error saving file: {e}")

        elif mode == "paste":
            raw = request.POST.get("credentials_json", "").strip()
            if not raw:
                messages.error(request, "Nothing pasted.")
                return redirect("credentials")
            try:
                parsed = json.loads(raw)
                if "installed" not in parsed and "web" not in parsed:
                    raise ValueError("Not a valid credentials.json (missing 'installed' or 'web' key)")
                CREDS_PATH.write_text(json.dumps(parsed, indent=2))
                messages.success(request, "✓ credentials.json saved! Now click 'Run Gmail Auth' to authorize.")
            except (json.JSONDecodeError, ValueError) as e:
                messages.error(request, f"Invalid JSON: {e}")
            except Exception as e:
                messages.error(request, f"Error: {e}")

        elif mode == "token_b64":
            raw = request.POST.get("token_b64", "").strip()
            if not raw:
                messages.error(request, "Nothing pasted.")
                return redirect("credentials")
            try:
                decoded = base64.b64decode(raw).decode("utf-8")
                token_data = json.loads(decoded)
                if "token" not in token_data and "refresh_token" not in token_data:
                    raise ValueError("Doesn't look like a Gmail token")
                TOKEN_PATH.write_text(decoded)
                messages.success(request, "✓ token.json saved locally.")
            except Exception as e:
                messages.error(request, f"Invalid token: {e}")

        return redirect("credentials")

    return render(request, "credentials.html", {"creds_status": _creds_status()})


@require_POST
def run_gmail_auth(request):
    """Trigger the OAuth flow in a subprocess and return the token."""
    if not CREDS_PATH.exists():
        return JsonResponse({"success": False, "error": "credentials.json not found. Upload it first."})

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())
        token_b64 = base64.b64encode(TOKEN_PATH.read_bytes()).decode()

        return JsonResponse({"success": True, "token_b64": token_b64})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})
