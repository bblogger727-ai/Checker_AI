"""Login gate for the CheckerAI site (checker, setter and mentor APIs).

The website's nginx asks /auth-gate/verify before passing any /api/ request on. A browser is
let through with the signed session cookie it gets from /auth-gate/login; a server-to-server
client with `Authorization: Bearer <GATE_SERVICE_TOKEN>`. Grading jobs run inside the backends
and never pass through here. Standard library only.

Settings (gate.env): GATE_USERNAME, GATE_PASSWORD_HASH ("pbkdf2_sha256:<iter>:<salt hex>:<hash
hex>"), GATE_SECRET (cookie signing; changing it logs everyone out), GATE_SERVICE_TOKEN.
"""

import hashlib
import hmac
import json
import os
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USERNAME = os.environ["GATE_USERNAME"]
PASSWORD_HASH = os.environ["GATE_PASSWORD_HASH"]
SECRET = os.environ["GATE_SECRET"].encode()
SERVICE_TOKEN = os.environ.get("GATE_SERVICE_TOKEN", "")
COOKIE = "ca_session"
TTL = 7 * 24 * 3600


def password_ok(password: str) -> bool:
    _, iterations, salt, expected = PASSWORD_HASH.split(":")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(digest.hex(), expected)


def sign(expires: int) -> str:
    return f"{expires}.{hmac.new(SECRET, str(expires).encode(), 'sha256').hexdigest()}"


def session_ok(value: str) -> bool:
    try:
        expires, _ = value.split(".", 1)
        return hmac.compare_digest(sign(int(expires)), value) and int(expires) > time.time()
    except ValueError:
        return False


class Gate(BaseHTTPRequestHandler):
    server_version = "gate"
    sys_version = ""

    def _reply(self, status: int, body: dict | None = None, cookie: str | None = None) -> None:
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if data:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorised(self) -> bool:
        bearer = self.headers.get("Authorization", "")
        if SERVICE_TOKEN and bearer.startswith("Bearer ") and hmac.compare_digest(
                bearer[7:].strip(), SERVICE_TOKEN):
            return True
        jar = SimpleCookie(self.headers.get("Cookie", ""))
        return COOKIE in jar and session_ok(jar[COOKIE].value)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/auth-gate/verify":
            self._reply(204 if self._authorised() else 401)
        else:
            self._reply(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/auth-gate/logout":
            self._reply(204, cookie=f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict")
            return
        if self.path != "/auth-gate/login":
            self._reply(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4096:
                raise ValueError
            data = json.loads(self.rfile.read(length) or b"{}")
            user, password = str(data.get("username", "")), str(data.get("password", ""))
        except (ValueError, json.JSONDecodeError):
            self._reply(400, {"detail": "Bad request"})
            return
        ok_user = hmac.compare_digest(user.encode(), USERNAME.encode())
        if not (password_ok(password) and ok_user):
            time.sleep(0.5)  # slows guessing; nginx also rate-limits this path
            self._reply(401, {"detail": "Invalid username or password"})
            return
        value = sign(int(time.time()) + TTL)
        self._reply(200, {"name": "Rucha Sarda", "role": "admin"},
                    cookie=f"{COOKIE}={value}; Path=/; Max-Age={TTL}; HttpOnly; Secure; SameSite=Strict")

    def log_message(self, fmt: str, *args: object) -> None:  # request lines only, never bodies
        if "/auth-gate/verify" not in (args[0] if args else ""):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9000), Gate).serve_forever()
