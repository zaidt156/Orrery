"""Browser session handshake for the web-delivered app.

The Electron/pywebview shell used to hand the session token to a window only Orrery controlled,
so `?token=` in the URL was contained. A real browser is different: a query token persists in
history, is bookmarkable, and is readable by extensions. Instead the launcher opens a single-use
launch code, the page trades it for an httpOnly cookie, and the code is stripped from the URL.

Cookies ignore port, so `http://127.0.0.1:<other>` is same-site with the app and SameSite=Strict
alone would NOT stop another local process from driving the API. Cookie-authenticated requests
therefore carry an Origin check; header-authenticated ones do not need one, because a cross-origin
page cannot set a custom header without a CORS preflight Orrery never grants.
"""
from __future__ import annotations

import hmac
import secrets
import time

COOKIE_NAME = "orrery_session"
CODE_TTL_SECONDS = 600  # a launch code is meant to be redeemed by the browser we just opened


class BrowserSession:
    """Owns the session token, the current single-use launch code, and cookie/Origin decisions."""

    def __init__(self, session_token: str) -> None:
        self._token = session_token
        self._code = ""
        self._code_minted_at = 0.0
        self.mint_code()

    @property
    def token(self) -> str:
        return self._token

    @property
    def code(self) -> str:
        """The currently redeemable launch code. Never log this — it is a credential."""
        return self._code

    def mint_code(self) -> str:
        """Replace the outstanding code with a fresh one, invalidating the old one."""
        self._code = secrets.token_urlsafe(32)
        self._code_minted_at = time.monotonic()
        return self._code

    def claim(self, code: str | None) -> str | None:
        """Redeem a launch code for the session token, then immediately rotate the code.

        Rotating on success makes the code single-use while keeping a valid one available, so a
        user who loses their cookie can still be handed a working URL by the launcher.
        """
        if not code or not self._code:
            return None
        if time.monotonic() - self._code_minted_at > CODE_TTL_SECONDS:
            return None
        if not hmac.compare_digest(code, self._code):
            return None
        self.mint_code()
        return self._token

    def token_matches(self, candidate: str | None) -> bool:
        # constant-time so the token can't be guessed via response timing
        return bool(candidate) and hmac.compare_digest(candidate, self._token)

    def origin_allowed(self, origin: str | None, host: str | None, dev_origin: str | None) -> bool:
        """Cross-origin guard for cookie-authenticated requests.

        A missing Origin means a same-origin navigation or a non-browser client; the cookie itself
        is the credential there. A present Origin must match the host the browser actually used,
        which is what rejects another loopback port.
        """
        if origin is None:
            return True
        if not host:
            return False
        allowed = {f"http://{host}", f"https://{host}"}
        if dev_origin:
            allowed.add(dev_origin.rstrip("/"))
        return origin.rstrip("/") in allowed
