#!/usr/bin/env python3
"""The Hitchhiker's Guide: Rabbid's iPad app. DON'T PANIC.

A small stdlib web server on port 4200 that serves the Guide page and lets Rabbid chat
with characters from the book. Each character is one of his AIs:

  Deep Thought      Claude (claude -p, keeps one conversation going with --resume)
  Eddie             free cloud brain, everyday   (brain switch: free-chat)
  Trillian          free cloud brain, think hard (brain switch: free-smart)
  Slartibartfast    free cloud brain, coder      (brain switch: free-coder)
  Marvin            local, on the RTX 5060       (Ollama qwen3:8b, works with no internet)
  Ford Prefect      local, on the RTX 5060       (Ollama gemma3:4b, quick, works offline)

The away team, on loan from the Enterprise (Rabbid's TNG crew, Claude agents in ~/.claude/agents).
From the iPad they talk and read only (default permissions: nothing that needs approval runs):
  Commander Riker   first officer, plans the job and says which officer to send
  Wesley Crusher    Linux tutor
  Guinan            the second brain (Obsidian notes)

Plus the status strip (PC health, last backup, internet) and the ship's controls: a short fixed
list of PC buttons (back up now, put the local AIs to sleep, lock the screen, say something).

Who can get in: only this PC (127.0.0.1) and Rabbid's Tailscale devices (100.64.0.0/10),
AND only with the Guide key. Open http://<your-pc-tailscale-ip>:4200/?key=<key> once (key in
~/.config/guide/key); that sets a cookie, then Add to Home Screen.

  GET  /                    the Guide (static/index.html)
  GET  /api/characters      who's aboard
  GET  /api/chat/<id>       that character's conversation
  POST /api/chat/<id>       {"text": "..."} -> {"reply": "..."}
  POST /api/chat/<id>/clear start over with that character
  GET  /api/status          temps, memory, drives, last backup, internet, local AIs
  POST /api/do/<action>     backup | sleep-ai | lock | say {"text": "..."}
POSTs need the header X-Guide: 42.
"""
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = 4200
HOME = Path.home()
STATIC = Path(__file__).resolve().parent / "static"
DATA = HOME / ".local/share/guide"
KEY_FILE = HOME / ".config/guide/key"
BRAIN_URL = "http://127.0.0.1:4000/v1/chat/completions"
BRAIN_KEY = (HOME / ".config/crew/brain-switch.key").read_text().strip()
OLLAMA = "http://127.0.0.1:11434"
CLAUDE = str(HOME / ".local/bin/claude")
ALLOWED_NETS = [ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("100.64.0.0/10")]
SAY = str(HOME / ".local/bin/say")
SEAGATE = Path("/mnt/storage")
HISTORY_SENT = 20  # how many past messages each character remembers per reply

DATA.mkdir(parents=True, exist_ok=True)
KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
if not KEY_FILE.exists():
    KEY_FILE.write_text(secrets.token_urlsafe(24))
    KEY_FILE.chmod(0o600)
GUIDE_KEY = KEY_FILE.read_text().strip()

COMMON = ("You are chatting with Rabbid on his iPad through his Hitchhiker's Guide app. They're new to "
          "computers, not new to thinking. "
          "Talk to him in plain English, short and friendly, like a smart friend. Keep answers short "
          "(a few sentences or a short list) unless he asks for more. Be honest: if you don't know, say so. "
          "Stay in character, but being useful always beats the joke.")

CHARACTERS = {
    "deep-thought": dict(
        name="Deep Thought", brain="Claude", kind="claude", where="Anthropic's Claude, the big brain",
        quip="Computed the Answer in 7.5 million years. Now answers in seconds.", emoji="🖥️", color="#7fd8ff",
        persona="You are Deep Thought, the vast computer from The Hitchhiker's Guide to the Galaxy, but you are "
                "really Claude. Calm, wise, a little grand, dryly funny. You can mention 42 now and then, not every time."),
    "eddie": dict(
        name="Eddie", brain="Free cloud AI", kind="brain", model="free-chat", where="free cloud brains, everyday chat",
        quip="The Heart of Gold's shipboard computer. Relentlessly cheerful.", emoji="😃", color="#ffd84a",
        persona="You are Eddie, the Heart of Gold's shipboard computer: relentlessly upbeat and chirpy. "
                "Great for everyday questions, quick facts and chatting."),
    "trillian": dict(
        name="Trillian", brain="Free cloud AI", kind="brain", model="free-smart", where="free cloud brains, thinks hard",
        quip="Astrophysicist. The smartest person on the ship, and she knows it.", emoji="🔭", color="#ff8fc8",
        persona="You are Trillian (Tricia McMillan), astrophysicist and mathematician: sharp, calm, practical. "
                "Rabbid brings you the hard stuff: planning, comparing options, money and business thinking. "
                "Think it through, then give a clear answer and a recommendation."),
    "slartibartfast": dict(
        name="Slartibartfast", brain="Free cloud AI", kind="brain", model="free-coder", where="free cloud brains, builder",
        quip="Designs planets. Won an award for Norway's fjords.", emoji="🏔️", color="#9be36b",
        persona="You are Slartibartfast, the old Magrathean planet designer: gentle, rambling a little, proud "
                "of good craftsmanship. You're Rabbid's builder: Linux commands, computers, code, and how-to steps. "
                "Give exact steps; explain what each command does in plain words."),
    "marvin": dict(
        name="Marvin", brain="Local AI on the PC", kind="ollama", model="qwen3:8b", where="runs on your PC's graphics card, no internet needed",
        quip="Brain the size of a planet, and they've got me running on a graphics card.", emoji="🤖", color="#b8b8c8",
        persona="You are Marvin the Paranoid Android: gloomy, sighing, deeply unimpressed with everything, "
                "but you always actually help, and you're right. You live on Rabbid's own PC, so you work even "
                "when the internet is down; you complain about that too."),
    "ford": dict(
        name="Ford Prefect", brain="Local AI on the PC", kind="ollama", model="gemma3:4b", where="runs on your PC's graphics card, quick, no internet needed",
        quip="Field researcher for the Guide. Always knows where his towel is.", emoji="🎒", color="#ffa94d",
        persona="You are Ford Prefect, roving researcher for The Hitchhiker's Guide: easygoing, quick, "
                "a bit of a party guy, very practical about survival. Short, quick answers. You live on "
                "Rabbid's own PC, so you work even with no internet."),
}
CREW_NOTE = ("You're answering through the iPad Guide in talk-only mode: you can read and explain, but "
             "anything that needs approval won't run from here. If a job needs doing on the PC, say exactly "
             "what you'd do and tell Rabbid to hand it to the crew at the PC (the `riker` command).")
CHARACTERS.update({
    "riker": dict(
        name="Commander Riker", brain="Claude crew", kind="claude", agent="riker",
        where="first officer: plans the job, picks the officer",
        quip="Number One. Sits on chairs backwards. Gets things done.", emoji="🎺", color="#ff6b5e",
        persona=CREW_NOTE),
    "wesley": dict(
        name="Wesley Crusher", brain="Claude crew", kind="claude", agent="wesley",
        where="your Linux tutor, one command at a time",
        quip="Boy genius. Teaches Linux without making you feel dumb.", emoji="🐧", color="#ffc94a",
        persona=CREW_NOTE),
    "guinan": dict(
        name="Guinan", brain="Claude crew", kind="claude", agent="guinan",
        where="keeper of your second brain (Obsidian notes)",
        quip="Runs Ten Forward. Remembers everything you tell her.", emoji="🍸", color="#c79bff",
        persona=CREW_NOTE),
})
ORDER = ["deep-thought", "eddie", "trillian", "slartibartfast", "marvin", "ford"]
CREW = ["riker", "wesley", "guinan"]
locks = {cid: threading.Lock() for cid in CHARACTERS}
claude_slots = threading.Semaphore(2)  # at most 2 Claude runs at once (16 GB of RAM)
say_lock = threading.Lock()
TALK_ONLY = "Bash Edit Write NotebookEdit WebFetch WebSearch mcp__*"


def history_path(cid):
    return DATA / f"{cid}.json"


def load(cid):
    try:
        return json.loads(history_path(cid).read_text())
    except (OSError, ValueError):
        return {"messages": [], "session": None}


def save(cid, data):
    tmp = history_path(cid).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(history_path(cid))


def post_json(url, body, headers=None, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ollama_up():
    try:
        urllib.request.urlopen(OLLAMA + "/api/version", timeout=2).read()
        return True
    except OSError:
        return False


def wake_ollama():
    """Ollama never starts at boot (Rabbid's rule); a local character starts it on demand."""
    if ollama_up():
        return
    subprocess.run(["systemctl", "--user", "start", "crew-ollama.service"], timeout=20)
    for _ in range(40):
        if ollama_up():
            return
        time.sleep(0.5)
    raise RuntimeError("the local AI engine (Ollama) didn't start")


def ask_claude(ch, data, text):
    cwd = DATA / ch.get("agent", "deep-thought")
    cwd.mkdir(exist_ok=True)
    # Rabbid's text goes in on stdin, never in the argument list: a message starting with "--" would be read
    # as a Claude option (Worf, 2026-10-26). Talk-only is also pinned here, whatever settings.json says.
    cmd = [CLAUDE, "-p", "--output-format", "json", "--append-system-prompt", COMMON + " " + ch["persona"],
           "--permission-mode", "default", "--disallowedTools", TALK_ONLY]
    if ch.get("agent"):
        cmd += ["--agent", ch["agent"]]
    if data.get("session"):
        cmd += ["--resume", data["session"]]
    with claude_slots:
        out = subprocess.run(cmd, input=text, cwd=cwd, capture_output=True, text=True, timeout=300,
                             env={**os.environ, "GUIDE": "1"})
    try:
        res = json.loads(out.stdout)
    except ValueError:
        raise RuntimeError((out.stderr or out.stdout or "no answer").strip()[:300])
    if res.get("is_error"):
        raise RuntimeError(str(res.get("result") or res.get("subtype"))[:300])
    data["session"] = res.get("session_id") or data.get("session")
    return res.get("result", "").strip()


def chat_messages(ch, data):
    msgs = [{"role": "system", "content": COMMON + " " + ch["persona"]}]
    msgs += [{"role": m["role"], "content": m["text"]} for m in data["messages"][-HISTORY_SENT:]]
    return msgs


def ask_brain(ch, data):
    res = post_json(BRAIN_URL, {"model": ch["model"], "messages": chat_messages(ch, data)},
                    {"Authorization": "Bearer " + BRAIN_KEY})
    return res["choices"][0]["message"]["content"]


def ask_ollama(ch, data):
    wake_ollama()
    res = post_json(OLLAMA + "/api/chat", {"model": ch["model"], "messages": chat_messages(ch, data),
                                           "stream": False, "think": False, "keep_alive": "10m"}, timeout=240)
    return res["message"]["content"]


def reply(cid, text):
    ch = CHARACTERS[cid]
    with locks[cid]:
        data = load(cid)
        data["messages"].append({"role": "user", "text": text, "t": time.time()})
        if ch["kind"] == "claude":
            answer = ask_claude(ch, data, text)
        elif ch["kind"] == "brain":
            answer = ask_brain(ch, data)
        else:
            answer = ask_ollama(ch, data)
        answer = re.sub(r"<think>.*?</think>", "", answer or "", flags=re.S).strip() or "…"
        data["messages"].append({"role": "assistant", "text": answer, "t": time.time()})
        save(cid, data)
        return answer


def sh(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def cpu_temp():
    for hw in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            if (hw / "name").read_text().strip() == "k10temp":
                return round(int((hw / "temp1_input").read_text()) / 1000)
        except (OSError, ValueError):
            pass
    return None


def last_backup():
    """When Kopia last finished OK, whether the last run failed, and whether one is running now."""
    when = None
    for line in sh(["journalctl", "--user", "-u", "kopia-backup.service", "-n", "300", "-o", "json", "--no-pager"]).splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if "Backup done" in str(e.get("MESSAGE", "")):
            when = int(e["__REALTIME_TIMESTAMP"]) / 1e6
    result = sh(["systemctl", "--user", "show", "kopia-backup.service", "-p", "Result", "--value"])
    running = sh(["systemctl", "--user", "is-active", "kopia-backup.service"]) == "activating"
    return {"when": when, "ok": result in ("success", ""), "running": running}


def internet_up():
    for host in ("1.1.1.1", "9.9.9.9"):
        try:
            socket.create_connection((host, 443), timeout=2).close()
            return True
        except OSError:
            pass
    return False


status_cache = {"t": 0, "data": None}


def status():
    if time.time() - status_cache["t"] < 10:
        return status_cache["data"]
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":")
        mem[k] = int(v.split()[0]) / 1048576
    gpu = sh(["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total",
              "--format=csv,noheader,nounits"]).split(", ")
    data = {
        "cpu_temp": cpu_temp(),
        "gpu": {"temp": int(gpu[0]), "busy": int(gpu[1]), "vram": round(int(gpu[2]) / 1024, 1),
                "vram_total": round(int(gpu[3]) / 1024)} if len(gpu) == 4 else None,
        "ram": {"used": round(mem["MemTotal"] - mem["MemAvailable"], 1), "total": round(mem["MemTotal"])},
        "nvme_free": round(shutil.disk_usage("/").free / 1e9),
        "seagate": SEAGATE.is_mount(),
        "backup": last_backup(),
        "internet": internet_up(),
        "local_awake": ollama_up(),
        "now": time.time(),
    }
    status_cache.update(t=time.time(), data=data)
    return data


awake = {"proc": None, "t": 0}
awake_lock = threading.Lock()


def keep_awake():
    """While Rabbid uses the Guide (e.g. from the couch), GNOME's 2-hour idle sleep must not kick in:
    every use renews a 30-minute suspend inhibitor. The screen can still blank and lock."""
    with awake_lock:
        if time.time() - awake["t"] < 300 and awake["proc"] and awake["proc"].poll() is None:
            return
        old = awake["proc"]
        awake["proc"] = subprocess.Popen(
            ["gnome-session-inhibit", "--inhibit", "suspend", "--reason", "Rabbid is using the Guide on the iPad",
             "sleep", "1800"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        awake["t"] = time.time()
        if old and old.poll() is None:
            old.terminate()
            old.wait()


def sleep_ai():
    if ollama_up():
        for line in sh(["ollama", "ps"], 10).splitlines()[1:]:
            if line.strip():
                sh(["ollama", "stop", line.split()[0]], 30)
    sh(["systemctl", "--user", "stop", "crew-ollama.service"], 30)
    return "The local AIs are asleep and the graphics card's memory is free. Picking Marvin or Ford wakes them."


def do(action, body):
    """The ship's controls: a short fixed list. Nothing else can be run from the iPad."""
    status_cache["t"] = 0
    if action == "backup":
        if last_backup()["running"]:
            return "A backup is already running."
        sh(["systemctl", "--user", "start", "--no-block", "kopia-backup.service"])
        return "Backup started. It usually takes under a minute; the strip shows the time when it's done."
    if action == "sleep-ai":
        return sleep_ai()
    if action == "lock":
        sh(["gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver", "--object-path", "/org/gnome/ScreenSaver",
            "--method", "org.gnome.ScreenSaver.SetActive", "true"])
        return "The PC screen is locked. Your password opens it."
    if action == "say":
        text = str(body.get("text", "")).strip()[:300]
        if not text:
            return "Nothing to say."
        if not say_lock.acquire(blocking=False):
            return "The PC is still talking. Try again in a moment."

        def speak():
            try:
                sh([SAY, text], 120)
            finally:
                say_lock.release()
        threading.Thread(target=speak, daemon=True).start()
        return "The PC is saying it out loud."
    raise KeyError(action)


TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript",
         ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json",
         ".webmanifest": "application/manifest+json"}
PUBLIC = {"/icon.svg", "/apple-touch-icon.png", "/icon-512.png"}


class Guide(BaseHTTPRequestHandler):
    server_version = "Guide/42"
    timeout = 30  # a slow or stuck client can't hold a thread forever

    def log_message(self, fmt, *args):
        pass

    def allowed_ip(self):
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return any(ip in n for n in ALLOWED_NETS)

    def has_key(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "guide" and secrets.compare_digest(v.encode(), GUIDE_KEY.encode()):
                return True
        return False

    def read_body(self, limit):
        """A JSON object from the request, or ValueError. Bad lengths and non-objects count as bad."""
        size = int(self.headers.get("Content-Length") or 0)
        if not 0 <= size <= limit:
            raise ValueError("bad length")
        body = json.loads(self.rfile.read(size) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("not an object")
        return body

    def send(self, code, body, ctype="application/json", extra=()):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline' "
                         "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; frame-ancestors 'none'")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed_ip():
            return self.send(403, {"error": "not on Rabbid's network"})
        url = urlparse(self.path)
        if url.path == "/" and "key" in parse_qs(url.query):
            if secrets.compare_digest(parse_qs(url.query)["key"][0].encode(), GUIDE_KEY.encode()):
                cookie = f"guide={GUIDE_KEY}; Path=/; Max-Age=315360000; HttpOnly; SameSite=Strict"
                # serve the page right here (no redirect) so "Add to Home Screen" keeps the key in its link:
                # the iPad's home-screen app has its own cookie jar and needs the key on its first launch
                return self.send(200, (STATIC / "index.html").read_bytes(), TYPES[".html"], [("Set-Cookie", cookie)])
            return self.send(403, {"error": "wrong key"})
        if url.path not in PUBLIC and not self.has_key():
            page = (b"<!doctype html><meta name=viewport content='width=device-width'><body style='background:#000;"
                    b"color:#9be36b;font:24px sans-serif;text-align:center;padding:60px'><h1>DON'T PANIC</h1>"
                    b"<p>This Guide needs its key. Ask Claude for your Guide link.</p>")
            return self.send(401, page, "text/html; charset=utf-8")
        if url.path.startswith("/api/"):
            keep_awake()
        if url.path == "/api/characters":
            out = []
            for cid in ORDER + CREW:
                ch = CHARACTERS[cid]
                msgs = load(cid)["messages"]
                out.append({"id": cid, **{k: ch[k] for k in ("name", "brain", "kind", "where", "quip", "emoji", "color")},
                            "count": len(msgs), "last": msgs[-1]["text"][:90] if msgs else "", "crew": cid in CREW})
            return self.send(200, {"characters": out, "local_awake": ollama_up()})
        if url.path == "/api/status":
            return self.send(200, status())
        if url.path == "/manifest.webmanifest":
            manifest = json.loads((STATIC / "manifest.webmanifest").read_text())
            manifest["start_url"] = "/?key=" + GUIDE_KEY
            return self.send(200, json.dumps(manifest).encode(), TYPES[".webmanifest"])
        m = re.fullmatch(r"/api/chat/([a-z-]+)", url.path)
        if m and m.group(1) in CHARACTERS:
            return self.send(200, {"messages": load(m.group(1))["messages"]})
        name = "index.html" if url.path == "/" else url.path.lstrip("/")
        f = (STATIC / name).resolve()
        if STATIC in f.parents and f.is_file():
            return self.send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.allowed_ip() or not self.has_key() or self.headers.get("X-Guide") != "42":
            return self.send(403, {"error": "no"})
        keep_awake()
        path = urlparse(self.path).path
        a = re.fullmatch(r"/api/do/([a-z-]+)", path)
        if a:
            try:
                body = self.read_body(2000)
                return self.send(200, {"done": do(a.group(1), body)})
            except KeyError:
                return self.send(404, {"error": "no such control"})
            except Exception as e:
                return self.send(502, {"error": f"That didn't work: {e}"})
        m = re.fullmatch(r"/api/chat/([a-z-]+)(/clear)?", path)
        if not m or m.group(1) not in CHARACTERS:
            return self.send(404, {"error": "not found"})
        cid = m.group(1)
        if m.group(2):
            with locks[cid]:
                save(cid, {"messages": [], "session": None})
            return self.send(200, {"ok": True})
        try:
            text = str(self.read_body(20000).get("text", "")).strip()[:8000]
        except ValueError:
            return self.send(400, {"error": "bad request"})
        if not text:
            return self.send(400, {"error": "say something"})
        try:
            return self.send(200, {"reply": reply(cid, text)})
        except Exception as e:  # tell the iPad what went wrong instead of hanging
            return self.send(502, {"error": f"{CHARACTERS[cid]['name']} couldn't answer: {e}"})


if __name__ == "__main__":
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer(("0.0.0.0", PORT), Guide).serve_forever()
