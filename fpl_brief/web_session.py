"""Signed session cookies and the sign-in page for a password-protected hosted dashboard.

Tokens are ``<expiry>.<hmac>``: stateless, so they survive free-tier restarts, and keyed on
the configured password, so changing it signs every browser out.
"""

import hashlib
import hmac
import html
import time

COOKIE = "fpl_session"
REMEMBER_SECONDS = 30 * 24 * 3600
SESSION_SECONDS = 12 * 3600


def _key(password):
    return hmac.new(password.encode("utf-8"), b"fpl-brief-session-v1", hashlib.sha256).digest()


def make_token(password, remember, now=None):
    expiry = int((now if now is not None else time.time()) + (REMEMBER_SECONDS if remember else SESSION_SECONDS))
    signature = hmac.new(_key(password), f"v1.{expiry}".encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{signature}"


def token_valid(password, token, now=None):
    if not password or not isinstance(token, str) or token.count(".") != 1:
        return False
    expiry, signature = token.split(".")
    if not expiry.isdigit() or len(signature) != 64:
        return False
    expected = hmac.new(_key(password), f"v1.{expiry}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected) and int(expiry) > (now if now is not None else time.time())


def cookie_token(header):
    """Return the session token from a Cookie header, or None."""
    if not header:
        return None
    # Split by hand: SimpleCookie discards the whole header if any unrelated cookie is malformed.
    token = None
    for part in header.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name.strip() == COOKIE:
            token = value.strip().strip('"')
    return token


def set_cookie(token, remember, secure):
    parts = [f"{COOKIE}={token}", "Path=/", "HttpOnly", "SameSite=Lax"]
    if remember:
        parts.append(f"Max-Age={REMEMBER_SECONDS}")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie(secure):
    return f"{COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" + ("; Secure" if secure else "")


def safe_next(value):
    """Only allow same-site absolute paths as a post-sign-in destination."""
    if not isinstance(value, str) or not value.startswith("/") or value.startswith(("//", "/\\")):
        return "/"
    if any(ch in value for ch in "\r\n\t\\") or len(value) > 512 or not value.isascii():
        return "/"
    return value


LOGIN_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
    "Referrer-Policy": "same-origin",
}


def login_page(next_path="/", error=""):
    """A self-contained sign-in page in the Tactics Board style (no scripts, no external requests)."""
    message = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · FPL Brief</title>
<style>
:root {{ --wall:#D9DEDB; --enamel:#F7F8F5; --frame-hi:#E3E6E7; --frame:#B9BFC2; --ink:#14213D; --ink-soft:#4A5670; --rule:#C6CDCA; --red:#C9302C; --green:#1C7C45; --blue:#1C55C7; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px 16px; background: var(--wall); color: var(--ink); font: 16px/1.5 Barlow, "Segoe UI", system-ui, sans-serif; }}
.frame {{ width: min(420px, 100%); padding: 12px; border-radius: 18px; background: linear-gradient(180deg, var(--frame-hi), var(--frame)); box-shadow: 0 12px 28px rgb(0 0 0 / 16%), inset 0 1px 0 #fff; }}
main {{ padding: 28px 26px 24px; border-radius: 8px; background: radial-gradient(120% 80% at 30% 0%, #fff, var(--enamel) 60%); }}
.brand {{ margin: 0 0 18px; font: 800 20px/1 "Barlow Condensed", "Arial Narrow", sans-serif; letter-spacing: .03em; }}
.brand span {{ color: var(--green); }}
h1 {{ margin: 0 0 6px; font: 800 32px/1.05 "Barlow Condensed", "Arial Narrow", sans-serif; }}
.lead {{ margin: 0 0 20px; color: var(--ink-soft); font-size: 15px; }}
label {{ display: block; margin: 0 0 6px; font-weight: 700; font-size: 14px; }}
input[type=password] {{ width: 100%; min-height: 48px; padding: 10px 12px; border: 1.5px solid var(--rule); border-radius: 10px; background: #fff; color: var(--ink); font: inherit; }}
input[type=password]:focus-visible, button:focus-visible, input[type=checkbox]:focus-visible {{ outline: 3px solid var(--blue); outline-offset: 2px; }}
.remember {{ display: flex; align-items: center; gap: 10px; margin: 14px 0 20px; font-weight: 600; font-size: 15px; }}
.remember input {{ width: 20px; height: 20px; accent-color: var(--ink); }}
button {{ width: 100%; min-height: 48px; border: 0; border-radius: 10px; background: var(--ink); color: #fff; font: 700 17px/1 "Barlow Condensed", "Arial Narrow", sans-serif; letter-spacing: .06em; text-transform: uppercase; cursor: pointer; box-shadow: 0 3px 8px rgb(0 0 0 / 18%); }}
button:hover {{ background: #22325A; }}
.error {{ margin: 0 0 16px; padding: 10px 12px; border-radius: 10px; background: #F8E7E5; color: #7A1C17; font-weight: 600; font-size: 15px; }}
.note {{ margin: 18px 0 0; color: var(--ink-soft); font-size: 13px; }}
</style></head>
<body><div class="frame"><main>
<p class="brand">FPL<span>·</span>BRIEF</p>
<h1>Sign in</h1>
<p class="lead">This dashboard is private. Enter the password you set in Render.</p>
{message}
<form method="post" action="/login">
<input type="hidden" name="next" value="{html.escape(safe_next(next_path), quote=True)}">
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
<label class="remember"><input type="checkbox" name="remember" value="1" checked> Keep me signed in for 30 days</label>
<button type="submit">Sign in</button>
</form>
<p class="note">Read-only FPL dashboard. It never makes changes to your FPL team.</p>
</main></div></body></html>"""
