#!/usr/bin/python3
"""Nexus panel: a web page to run commands on the board without a terminal.

After logging in with a system account, users can
  - press buttons for predefined commands (root-owned /etc/nexus/actions.json,
    run as root), and
  - paste a command, e.g. an install line copied from a vendor's website
    (run as the logged-in user, in their home directory, with bash).

Endpoints (all /api/* except login need a session; POSTs need the
X-Nexus-Panel header, which other websites cannot send without a CORS
preflight that this server never answers)
  GET  /                  the page (static/index.html)
  GET  /css/…, /img/…     static files
  POST /api/login         {"user", "password"} -> session cookie
  POST /api/logout
  GET  /api/session       {"user"}
  GET  /api/actions       [{id, title, description, confirm}] — no commands
  POST /api/run/<id>      runs a predefined action as root
  POST /api/exec          {"command"} runs it as the logged-in user
  GET  /api/autodarts     Autodarts status for the logged-in user
  GET  /api/autodarts/logs  last lines of its service log
  POST /api/autodarts/<op>  start|stop|restart|enable|disable|remove-app-service
                          (JSON), update (streamed)
The streamed endpoints send the output as text/plain, then
"\\x1e" + {"exit": <code>} as the last record.

Only one command runs at a time. Python standard library only.
"""

import argparse
import ctypes
import ctypes.util
import grp
import hmac
import json
import mimetypes
import os
import pwd
import secrets
import signal
import subprocess
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RECORD_SEP = b"\x1e"
DEFAULT_TIMEOUT = 30 * 60          # seconds; installs can take a while
LOGIN_GROUP = "sudo"               # only admins: the buttons run as root
SESSION_IDLE = 30 * 60             # log out after 30 min without requests
SESSION_MAX = 12 * 3600
MAX_FAILURES, FAILURE_WINDOW = 5, 5 * 60   # per client IP
COOKIE = "nexus_session"
MAX_BODY = 64 * 1024

run_lock = threading.Lock()
login_lock = threading.Lock()      # crypt() is not thread-safe
sessions = {}                      # token -> {"user", "created", "seen"}
sessions_lock = threading.Lock()
failures = {}                      # ip -> [timestamps]

_libcrypt = ctypes.CDLL(ctypes.util.find_library("crypt") or "libcrypt.so.1")
_libcrypt.crypt.restype = ctypes.c_char_p
_libcrypt.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]


# -- authentication --------------------------------------------------------

def check_password(user, password):
    """True if `password` matches the user's /etc/shadow hash (any scheme
    libxcrypt knows, e.g. yescrypt). Locked accounts never match."""
    try:
        with open("/etc/shadow", encoding="utf-8") as f:
            entry = next((l.split(":") for l in f if l.split(":", 1)[0] == user), None)
    except OSError:
        return False
    if not entry or len(entry) < 2 or not entry[1] or entry[1][0] in "!*":
        return False
    stored = entry[1].encode()
    out = _libcrypt.crypt(password.encode(), stored)
    return out is not None and hmac.compare_digest(out, stored)


def may_log_in(user):
    try:
        pw = pwd.getpwnam(user)
    except KeyError:
        return False
    if pw.pw_uid == 0:
        return False  # pasted commands would run as root
    try:
        g = grp.getgrnam(LOGIN_GROUP)
    except KeyError:
        return False
    return user in g.gr_mem or pw.pw_gid == g.gr_gid


def too_many_failures(ip):
    now = time.monotonic()
    recent = [t for t in failures.get(ip, []) if now - t < FAILURE_WINDOW]
    failures[ip] = recent
    return len(recent) >= MAX_FAILURES


def new_session(user):
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with sessions_lock:
        sessions[token] = {"user": user, "created": now, "seen": now}
    return token


def session_user(token):
    if not token:
        return None
    now = time.monotonic()
    with sessions_lock:
        s = sessions.get(token)
        if not s:
            return None
        if now - s["seen"] > SESSION_IDLE or now - s["created"] > SESSION_MAX:
            del sessions[token]
            return None
        s["seen"] = now
        return s["user"]


# -- actions ---------------------------------------------------------------

def load_actions(path):
    """Read and validate the action list. Errors go to the page, not a crash."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    actions = {}
    for a in data:
        if not all(isinstance(a.get(k), str) and a[k] for k in ("id", "title", "command")):
            raise ValueError(f"action needs id, title and command: {a!r}")
        actions[a["id"]] = a
    return actions


BASE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def root_popen_args():
    return {
        "cwd": "/",
        "env": {"PATH": BASE_PATH, "LANG": "C.UTF-8", "HOME": "/root",
                "USER": "root", "LOGNAME": "root",
                "DEBIAN_FRONTEND": "noninteractive", "TERM": "dumb"},
    }


def user_popen_args(user):
    pw = pwd.getpwnam(user)
    home = pw.pw_dir if os.path.isdir(pw.pw_dir) else "/"
    return {
        "cwd": home,
        "user": pw.pw_uid,
        "group": pw.pw_gid,
        "extra_groups": os.getgrouplist(user, pw.pw_gid),
        "env": {"PATH": f"{pw.pw_dir}/.local/bin:{BASE_PATH}", "LANG": "C.UTF-8",
                "HOME": pw.pw_dir, "USER": user, "LOGNAME": user,
                "SHELL": pw.pw_shell or "/bin/bash", "TERM": "dumb"},
    }


# -- Autodarts --------------------------------------------------------------
#
# The official installer puts Autodarts into ~/.local of the user who ran it
# and sets up no service. nexus-autodarts@<user>.service (installed next to
# this panel) runs `autodarts run` for that user.

_version_cache = {}


def ad_unit(user):
    return f"nexus-autodarts@{user}.service"


def ad_binary(user):
    return f"/home/{user}/.local/bin/autodarts"   # fixed by the unit's ExecStart


def systemctl(*args):
    r = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=90)
    return r.returncode, (r.stdout + r.stderr).strip()


def app_service_file(user):
    """The user unit Autodarts' own Service section writes, if any."""
    home = pwd.getpwnam(user).pw_dir
    path = f"{home}/.config/systemd/user/autodarts.service"
    return path if os.path.exists(path) else None


def ad_version(user):
    path = ad_binary(user)
    try:
        key = (path, os.stat(path).st_mtime)
    except OSError:
        return None
    if key not in _version_cache:
        try:
            r = subprocess.run([path, "--version"], stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, timeout=15, **user_popen_args(user))
            lines = (r.stdout or r.stderr).strip().splitlines()
            _version_cache[key] = lines[0][:80] if lines else "?"
        except (OSError, subprocess.SubprocessError):
            _version_cache[key] = "?"
    return _version_cache[key]


def ad_status(user):
    unit = ad_unit(user)
    installed = os.path.exists(ad_binary(user))
    return {
        "installed": installed,
        "version": ad_version(user) if installed else None,
        "enabled": systemctl("is-enabled", unit)[1] == "enabled",
        "active": systemctl("is-active", unit)[1],   # active, activating, failed, inactive …
        "app_service": bool(app_service_file(user)),
        "busy": run_lock.locked(),
    }


def ad_remove_app_service(user):
    """Remove the user unit set up from Autodarts' own Service section, so the
    board does not run twice. Stops it first if the user's manager is up."""
    path = app_service_file(user)
    if not path:
        return 0, ""
    subprocess.run(["systemctl", f"--machine={user}@.host", "--user", "disable", "--now",
                    "autodarts.service"], capture_output=True, timeout=60)
    base = os.path.dirname(path)
    for entry in [path] + [os.path.join(base, d, "autodarts.service")
                           for d in os.listdir(base) if d.endswith(".wants")]:
        if os.path.lexists(entry):
            os.remove(entry)
    return 0, "Dienst aus der Autodarts-App entfernt."



# -- HTTP ------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "nexus-panel"
    static_dir: Path
    actions_file: str

    def send_body(self, code, body, ctype="text/plain; charset=utf-8", headers=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, obj, headers=()):
        self.send_body(code, json.dumps(obj, ensure_ascii=False),
                       "application/json; charset=utf-8", headers)

    def log_message(self, fmt, *args):  # journald adds the timestamp
        print(f"{self.client_address[0]} {fmt % args}", flush=True)

    def token(self):
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        return c[COOKIE].value if COOKIE in c else None

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= MAX_BODY:
            return None
        try:
            obj = json.loads(self.rfile.read(n))
        except ValueError:
            return None
        return obj if isinstance(obj, dict) else None

    # -- GET --------------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            user = session_user(self.token())
            if not user:
                return self.send_json(401, {"error": "Bitte anmelden."})
            if path == "/api/session":
                return self.send_json(200, {"user": user})
            if path == "/api/autodarts":
                return self.send_json(200, ad_status(user))
            if path == "/api/autodarts/logs":
                r = subprocess.run(["journalctl", "-u", ad_unit(user), "-n", "60", "--no-pager",
                                    "-o", "short-iso"], capture_output=True, text=True, timeout=30)
                return self.send_body(200, r.stdout.strip() or "(noch keine Einträge)")
            if path == "/api/actions":
                try:
                    actions = load_actions(self.actions_file)
                except (OSError, ValueError) as e:
                    return self.send_json(500, {"error": f"{self.actions_file}: {e}"})
                return self.send_json(200, [
                    {k: a.get(k, "") for k in ("id", "title", "description", "confirm")}
                    for a in actions.values()
                ])
            return self.send_json(404, {"error": "Nicht gefunden"})

        rel = "index.html" if path == "/" else path.lstrip("/")
        target = (self.static_dir / rel).resolve()
        if self.static_dir not in target.parents or not target.is_file():
            return self.send_body(404, "Nicht gefunden")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/"):
            ctype += "; charset=utf-8"
        self.send_body(200, target.read_bytes(), ctype)

    # -- POST -------------------------------------------------------------

    def do_POST(self):
        if self.headers.get("X-Nexus-Panel") != "1":
            return self.send_body(403, "Verboten")
        path = self.path.split("?", 1)[0]

        if path == "/api/login":
            return self.login()
        if path == "/api/logout":
            with sessions_lock:
                sessions.pop(self.token(), None)
            return self.send_json(200, {}, [("Set-Cookie", f"{COOKIE}=; Path=/; Max-Age=0")])

        user = session_user(self.token())
        if not user:
            return self.send_body(401, "Bitte melde dich erneut an.")

        if path == "/api/exec":
            body = self.read_json()
            command = body.get("command") if body else None
            command = command.strip() if isinstance(command, str) else ""
            if not command:
                return self.send_body(400, "Kein Befehl angegeben.")
            label = f"exec by {user}: {command!r}"
            return self.run(["/bin/bash", "-c", command], user_popen_args(user), label, DEFAULT_TIMEOUT)

        if path.startswith("/api/autodarts/"):
            return self.autodarts_op(user, path[len("/api/autodarts/"):])

        if path.startswith("/api/run/"):
            try:
                action = load_actions(self.actions_file).get(path[len("/api/run/"):])
            except (OSError, ValueError) as e:
                return self.send_body(500, f"{self.actions_file}: {e}")
            if action is None:
                return self.send_body(404, "Unbekannte Aktion")
            label = f"action {action['id']} by {user}"
            return self.run(["/bin/sh", "-c", action["command"]], root_popen_args(), label,
                            float(action.get("timeout", DEFAULT_TIMEOUT)))

        return self.send_body(404, "Nicht gefunden")

    def autodarts_op(self, user, op):
        unit = ad_unit(user)

        if op == "update":
            def restart_if_running():
                if systemctl("is-active", unit)[1] != "active":
                    return ""
                code, out = systemctl("restart", unit)
                return "\nAutodarts neu gestartet.\n" if code == 0 else f"\nNeustart fehlgeschlagen: {out}\n"
            if not os.path.exists(ad_binary(user)):
                return self.send_body(409, "Autodarts ist nicht installiert.")
            return self.run(["/bin/bash", "-c", '"$HOME/.local/bin/autodarts" update'],
                            user_popen_args(user), f"autodarts update by {user}", DEFAULT_TIMEOUT,
                            after=restart_if_running)

        actions = {
            "start": ("start", unit), "stop": ("stop", unit), "restart": ("restart", unit),
            "enable": ("enable", "--now", unit), "disable": ("disable", unit),
        }
        if op not in actions and op != "remove-app-service":
            return self.send_json(404, {"error": "Unbekannte Aktion"})
        if run_lock.locked():
            return self.send_json(409, {"error": "Es läuft gerade ein Befehl. Bitte warte, bis er fertig ist."})
        if op in ("start", "restart", "enable"):
            if not os.path.exists(ad_binary(user)):
                return self.send_json(409, {"error": "Autodarts ist nicht installiert."})
            if app_service_file(user):
                return self.send_json(409, {"error": "Autodarts hat schon einen eigenen Dienst aus der App. "
                                                     "Entferne ihn zuerst, sonst läuft es doppelt."})
        self.log_message("autodarts %s by %s", op, user)
        code, out = ad_remove_app_service(user) if op == "remove-app-service" else systemctl(*actions[op])
        if code != 0:
            return self.send_json(500, {"error": out or f"systemctl {op} fehlgeschlagen"})
        return self.send_json(200, {"ok": True, "message": out})

    def login(self):
        ip = self.client_address[0]
        body = self.read_json() or {}
        user, password = body.get("user"), body.get("password")
        if not isinstance(user, str) or not isinstance(password, str):
            return self.send_json(400, {"error": "Benutzername und Passwort angeben."})
        user = user.strip()
        with login_lock:
            if too_many_failures(ip):
                return self.send_json(429, {"error": "Zu viele Fehlversuche. Bitte warte ein paar Minuten."})
            ok = may_log_in(user) and check_password(user, password)
            if not ok:
                failures.setdefault(ip, []).append(time.monotonic())
                time.sleep(1)  # under the lock: slows guessing for everyone
        if not ok:
            self.log_message("login failed for %r", user)
            return self.send_json(403, {"error": "Benutzername oder Passwort falsch."})
        self.log_message("login %s", user)
        failures.pop(ip, None)
        token = new_session(user)
        cookie = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_MAX}"
        return self.send_json(200, {"user": user}, [("Set-Cookie", cookie)])

    def run(self, argv, popen_args, label, timeout, after=None):
        if not run_lock.acquire(blocking=False):
            return self.send_body(409, "Es läuft gerade schon ein Befehl. Bitte warte, bis er fertig ist.")
        try:
            self.stream(argv, popen_args, label, timeout, after)
        finally:
            run_lock.release()

    def stream(self, argv, popen_args, label, timeout, after=None):
        """Run argv, stream its output, then the exit record. `after` runs
        once the command succeeded; its return text is appended."""
        self.log_message("run %s", label)
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, start_new_session=True, **popen_args)
        except OSError as e:
            return self.send_body(500, f"Konnte nicht gestartet werden: {e}")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()  # HTTP/1.0: the body ends when the connection closes

        timed_out = threading.Event()

        def kill():
            timed_out.set()
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        timer = threading.Timer(timeout, kill)
        timer.start()
        client_gone = False
        try:
            while chunk := os.read(proc.stdout.fileno(), 4096):
                if client_gone:
                    continue  # keep draining so the command is not blocked
                try:
                    self.wfile.write(chunk)
                except OSError:
                    client_gone = True  # tab closed: let the command finish anyway
            code = proc.wait()
        finally:
            timer.cancel()
            proc.stdout.close()
        msg = ""
        if timed_out.is_set():
            msg, code = "\n[Abgebrochen: Zeitlimit überschritten]\n", 124
        elif code == 0 and after:
            msg = after()
        self.log_message("done %s exit=%s", label, code)
        if not client_gone:
            try:
                self.wfile.write(msg.encode() + RECORD_SEP + json.dumps({"exit": code}).encode())
            except OSError:
                pass


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--actions", default="/etc/nexus/actions.json")
    p.add_argument("--static", default=str(Path(__file__).resolve().parent / "static"))
    args = p.parse_args()

    Handler.static_dir = Path(args.static).resolve()
    Handler.actions_file = args.actions
    server = ThreadingHTTPServer(("", args.port), Handler)
    server.daemon_threads = True
    print(f"nexus-panel on port {args.port}, actions from {args.actions}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
