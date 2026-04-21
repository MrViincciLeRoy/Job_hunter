import json
import base64
import os
from pathlib import Path
from django.shortcuts import render, redirect
from django.contrib import messages

CREDS_PATH = Path("credentials.json")
TOKEN_PATH = Path("token.json")


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
    # Check env var as fallback
    if os.getenv("GMAIL_TOKEN_B64"):
        return {"cls": "ok", "icon": "✓", "title": "Token found in environment", "detail": "GMAIL_TOKEN_B64 env var is set. Gmail sending should work."}
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
                messages.success(request, "✓ credentials.json saved successfully! Now run: python manage.py gmail_auth")
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
                messages.success(request, "✓ credentials.json saved! Now run: python manage.py gmail_auth")
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
                # Validate it decodes to valid JSON
                decoded = base64.b64decode(raw).decode("utf-8")
                token_data = json.loads(decoded)
                if "token" not in token_data and "refresh_token" not in token_data:
                    raise ValueError("Doesn't look like a Gmail token (missing 'token' or 'refresh_token')")
                # Save token.json locally
                TOKEN_PATH.write_text(decoded)
                messages.success(
                    request,
                    "✓ token.json saved locally. Add GMAIL_TOKEN_B64 to your Render environment variables for production."
                )
            except Exception as e:
                messages.error(request, f"Invalid token: {e}")

        return redirect("credentials")

    return render(request, "credentials.html", {
        "creds_status": _creds_status(),
    })
