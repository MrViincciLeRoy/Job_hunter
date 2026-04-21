import json
import base64
import os
import requests as http_requests
from pathlib import Path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST

CREDS_PATH = Path("credentials.json")
TOKEN_PATH = Path("token.json")
SCOPES = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def _redirect_uri(request):
    base = os.getenv("OAUTH_REDIRECT_URI", "")
    if base:
        return base
    scheme = "https" if request.is_secure() else "http"
    return f"{scheme}://{request.get_host()}/credentials/oauth-callback/"


def _load_client_secrets():
    data = json.loads(CREDS_PATH.read_text())
    info = data.get("web") or data.get("installed") or {}
    return {
        "client_id": info["client_id"],
        "client_secret": info["client_secret"],
    }


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
                messages.success(request, "✓ credentials.json saved! Now click 'Authorize Gmail' below.")
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
                messages.success(request, "✓ credentials.json saved! Now click 'Authorize Gmail' below.")
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
    """Build the Google OAuth URL manually — no PKCE, no Flow class."""
    if not CREDS_PATH.exists():
        return JsonResponse({"success": False, "error": "credentials.json not found. Upload it first."})

    try:
        secrets = _load_client_secrets()
        redirect_uri = _redirect_uri(request)

        params = {
            "client_id": secrets["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",
        }
        from urllib.parse import urlencode
        auth_url = GOOGLE_AUTH_URL + "?" + urlencode(params)

        return JsonResponse({"success": True, "auth_url": auth_url, "redirect_uri": redirect_uri})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


def oauth_callback(request):
    """Google redirects here. Exchange code for token manually — no PKCE."""
    error = request.GET.get("error")
    code = request.GET.get("code")

    if error:
        messages.error(request, f"OAuth error: {error}")
        return redirect("credentials")

    if not code:
        messages.error(request, "No authorization code received from Google.")
        return redirect("credentials")

    if not CREDS_PATH.exists():
        messages.error(request, "credentials.json missing — please re-upload it.")
        return redirect("credentials")

    try:
        secrets = _load_client_secrets()
        redirect_uri = _redirect_uri(request)

        # Direct POST to Google token endpoint — no PKCE involved
        resp = http_requests.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": secrets["client_id"],
            "client_secret": secrets["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        resp.raise_for_status()
        token_data = resp.json()

        if "error" in token_data:
            raise ValueError(token_data.get("error_description", token_data["error"]))

        # Build a token.json compatible with google-auth library
        token_json = {
            "token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "token_uri": GOOGLE_TOKEN_URL,
            "client_id": secrets["client_id"],
            "client_secret": secrets["client_secret"],
            "scopes": [SCOPES],
        }
        TOKEN_PATH.write_text(json.dumps(token_json, indent=2))
        token_b64 = base64.b64encode(TOKEN_PATH.read_bytes()).decode()

        return render(request, "credentials.html", {
            "creds_status": _creds_status(),
            "oauth_success": True,
            "token_b64": token_b64,
        })

    except Exception as e:
        messages.error(request, f"Token exchange failed: {e}")
        return redirect("credentials")


def debug_redirect_uri(request):
    uri = _redirect_uri(request)
    return HttpResponse(
        f"<pre style='font-family:monospace;padding:2rem'>"
        f"Redirect URI being used:\n\n  {uri}\n\n"
        f"Host: {request.get_host()}\n"
        f"Secure: {request.is_secure()}\n"
        f"OAUTH_REDIRECT_URI env: {os.getenv('OAUTH_REDIRECT_URI', 'NOT SET')}"
        f"</pre>"
    )