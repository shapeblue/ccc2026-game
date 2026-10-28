#!/usr/bin/env python3
"""CloudStack Card Clash - booth server.

Runs on a laptop with nothing but Python 3.9+. Stores players and matches in
SQLite, scores every match on the server, and serves the game, the
leaderboard screen and the admin page.

    python3 server.py                 # http://0.0.0.0:8080
    PORT=9000 ADMIN_PIN=4821 python3 server.py
"""
import csv
import io
import json
import os
import random
import re
import secrets
import socket
import sqlite3
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")
DB_PATH = os.environ.get("DB_PATH", os.path.join(ROOT, "data", "clash.db"))
PORT = int(os.environ.get("PORT", "8080"))
ADMIN_PIN = os.environ.get("ADMIN_PIN") or f"{secrets.randbelow(10**6):06d}"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "")
GRACE_SECONDS = 10

with open(os.path.join(WEB, "data", "game.json"), encoding="utf-8") as f:
    GAME = json.load(f)
CARDS = {c["id"]: c for c in GAME["cards"]}
SCENARIOS = {s["id"]: s for s in GAME["scenarios"]}
S = GAME["scoring"]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLES = {"Operator / SRE", "Developer", "Architect", "Manager / Executive", "Student", "Other"}

# ---------------------------------------------------------------- database
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.row_factory = sqlite3.Row
_lock = threading.Lock()
_db.executescript(
    """
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY,
        token TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        nickname TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        company TEXT,
        role TEXT,
        consent_rules INTEGER NOT NULL,
        consent_updates INTEGER NOT NULL,
        prize TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS matches (
        id TEXT PRIMARY KEY,
        player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
        scenario_id TEXT NOT NULL,
        started_at REAL NOT NULL,
        finished_at REAL,
        day TEXT NOT NULL,
        cards TEXT,
        score INTEGER,
        breakdown TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_matches_player ON matches(player_id);
    """
)


def _migrate():
    """Add columns that older databases don't have yet."""
    wanted = {
        "players": {"bonus_day": "TEXT", "bonus_rounds": "INTEGER NOT NULL DEFAULT 0"},
        "matches": {"clock_at": "REAL"},
    }
    for table, cols in wanted.items():
        have = {r[1] for r in _db.execute(f"PRAGMA table_info({table})")}
        for col, decl in cols.items():
            if col not in have:
                _db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    _db.commit()


_migrate()
ROUND_LIMIT = int(GAME.get("daily_round_limit", 5))


def q(sql, args=(), one=False, commit=False):
    with _lock:
        cur = _db.execute(sql, args)
        if commit:
            _db.commit()
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


# ---------------------------------------------------------------- scoring
def resolve(card_ids):
    """Return (active ids, inactive {id: missing tags}, provided tags)."""
    active = [c for c in card_ids if c in CARDS]
    while True:
        provided = {t for c in active for t in CARDS[c]["provides"]}
        still = [c for c in active if all(r in provided for r in CARDS[c]["requires"])]
        if len(still) == len(active):
            break
        active = still
    provided = {t for c in active for t in CARDS[c]["provides"]}
    inactive = {
        c: [r for r in CARDS[c]["requires"] if r not in provided]
        for c in card_ids
        if c in CARDS and c not in active
    }
    return active, inactive, provided


def score_match(scenario, card_ids, elapsed):
    card_ids = list(dict.fromkeys(c for c in card_ids if c in CARDS))
    active, inactive, provided = resolve(card_ids)
    cost = sum(CARDS[c]["cost"] for c in card_ids)
    met = [r for r in scenario["requires"] if r in provided]
    missing = [r for r in scenario["requires"] if r not in provided]
    over_budget = cost > scenario["budget"]
    all_met = not missing and not over_budget
    time_left = max(0, GAME["time_limit"] - int(elapsed))

    lines = [{"label": f"Requirements met ({len(met)} of {len(scenario['requires'])})",
              "points": len(met) * S["per_requirement"]}]
    if all_met:
        lines.append({"label": "Every requirement met", "points": S["all_met_bonus"]})
        lines.append({"label": f"Budget left ({scenario['budget'] - cost} credits)",
                      "points": (scenario["budget"] - cost) * S["per_budget_left"]})
        lines.append({"label": f"Time left ({time_left}s)", "points": time_left * S["per_second_left"]})
    if inactive:
        lines.append({"label": f"Cards that couldn't run ({len(inactive)})",
                      "points": -len(inactive) * S["inactive_card_penalty"]})
    if over_budget:
        lines = [{"label": "Over budget, build rejected", "points": 0}]

    incident_id = random.choice(scenario["incidents"])
    inc = GAME["incidents"][incident_id]
    counters = inc["counter"] if isinstance(inc["counter"], list) else [inc["counter"]]
    survived = (not over_budget) and any(c in provided for c in counters)
    if survived:
        lines.append({"label": "Survived the incident", "points": S["incident_bonus"]})

    total = max(0, sum(l["points"] for l in lines))
    return total, {
        "lines": lines,
        "missing": missing,
        "inactive": inactive,
        "cost": cost,
        "budget": scenario["budget"],
        "incident": {"id": incident_id, "title": inc["title"], "survived": survived,
                     "text": inc["win"] if survived else inc["lose"]},
    }


# ---------------------------------------------------------------- helpers
def today():
    return datetime.now().strftime("%Y-%m-%d")


def lan_urls():
    if PUBLIC_URL:
        return [PUBLIC_URL]
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips.discard("127.0.0.1")
    return [f"http://{ip}:{PORT}" for ip in sorted(ips)] or [f"http://localhost:{PORT}"]


def leaderboard(day=None, limit=10):
    where, args = "m.score IS NOT NULL", []
    if day:
        where += " AND m.day = ?"
        args.append(day)
    rows = q(
        f"""SELECT p.nickname, p.company, MAX(m.score) AS best, COUNT(m.id) AS games
            FROM matches m JOIN players p ON p.id = m.player_id
            WHERE {where} GROUP BY p.id ORDER BY best DESC, MIN(m.finished_at) ASC LIMIT ?""",
        (*args, limit),
    )
    return [dict(r) for r in rows]


def rounds_left(p):
    """Rounds the player can still start today."""
    used = q("SELECT COUNT(*) AS n FROM matches WHERE player_id=? AND day=?", (p["id"], today()), one=True)["n"]
    bonus = p["bonus_rounds"] if p["bonus_day"] == today() else 0
    return max(0, ROUND_LIMIT + bonus - used)


def rank_of(player_id):
    best = q("SELECT MAX(score) AS b FROM matches WHERE player_id=? AND score IS NOT NULL",
             (player_id,), one=True)["b"]
    if best is None:
        return None, None
    higher = q(
        """SELECT COUNT(*) AS n FROM (SELECT MAX(score) AS b FROM matches
           WHERE score IS NOT NULL GROUP BY player_id) WHERE b > ?""",
        (best,), one=True)["n"]
    return higher + 1, best


# ---------------------------------------------------------------- HTTP
class Handler(SimpleHTTPRequestHandler):
    server_version = "CardClash/1.0"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or "") and "leaderboard" not in self.path:
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # -- plumbing
    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def error(self, msg, status=400):
        self.send_json({"error": msg}, status)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64_000:
            return None
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return None

    def is_admin(self):
        return secrets.compare_digest(self.headers.get("X-Admin-Pin", ""), ADMIN_PIN)

    def player(self, token):
        return q("SELECT * FROM players WHERE token=?", (token or "",), one=True)

    # -- routing
    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/leaderboard", "/admin"):
            self.path = u.path + ".html"
            return super().do_GET()
        if not u.path.startswith("/api/"):
            return super().do_GET()
        qs = parse_qs(u.query)
        if u.path == "/api/config":
            return self.send_json({"event": GAME["event"], "join_urls": lan_urls()})
        if u.path == "/api/leaderboard":
            stats = q("SELECT COUNT(DISTINCT player_id) AS players, COUNT(*) AS games "
                      "FROM matches WHERE score IS NOT NULL", one=True)
            return self.send_json({"today": leaderboard(today()), "overall": leaderboard(),
                                   "players": stats["players"], "games": stats["games"]})
        if u.path == "/api/me":
            p = self.player(qs.get("token", [""])[0])
            if not p:
                return self.error("Unknown player", 404)
            return self.send_json(self.me(p))
        if u.path.startswith("/api/admin/"):
            if not self.is_admin():
                return self.error("Wrong PIN", 401)
            if u.path == "/api/admin/players":
                rows = q("""SELECT p.*, MAX(m.score) AS best, COUNT(m.score) AS games
                            FROM players p LEFT JOIN matches m ON m.player_id = p.id
                            GROUP BY p.id ORDER BY best IS NULL, best DESC""")
                out = []
                for r in rows:
                    d = {k: r[k] for k in ("id", "full_name", "nickname", "email", "company", "role",
                                           "consent_updates", "prize", "created_at", "best", "games")}
                    d["rounds_left"] = rounds_left(r)
                    out.append(d)
                return self.send_json(out)
            if u.path == "/api/admin/export.csv":
                return self.export_csv(qs.get("scope", ["all"])[0])
        return self.error("Not found", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        data = self.body()
        if data is None:
            return self.error("Request body must be JSON")
        routes = {
            "/api/register": self.register,
            "/api/match/start": self.match_start,
            "/api/match/clock": self.match_clock,
            "/api/admin/bonus": self.admin_bonus,
            "/api/match/finish": self.match_finish,
            "/api/admin/draw": self.admin_draw,
            "/api/admin/award": self.admin_award,
            "/api/admin/reset": self.admin_reset,
        }
        fn = routes.get(path)
        if not fn:
            return self.error("Not found", 404)
        if path.startswith("/api/admin/") and not self.is_admin():
            return self.error("Wrong PIN", 401)
        return fn(data)

    # -- player endpoints
    def register(self, d):
        name = str(d.get("full_name", "")).strip()[:80]
        nick = str(d.get("nickname", "")).strip()[:24] or name.split(" ")[0][:24]
        email = str(d.get("email", "")).strip().lower()[:120]
        company = str(d.get("company", "")).strip()[:80]
        role = d.get("role") if d.get("role") in ROLES else "Other"
        if not name:
            return self.error("Enter your name.")
        if not EMAIL_RE.match(email):
            return self.error("Enter a valid email address so we can reach you if you win.")
        if not d.get("consent_rules"):
            return self.error("Accept the game rules to play.")
        updates = 1 if d.get("consent_updates") else 0
        existing = q("SELECT token FROM players WHERE email=?", (email,), one=True)
        if existing:
            q("""UPDATE players SET full_name=?, nickname=?, company=?, role=?, consent_updates=?
                 WHERE email=?""", (name, nick, company, role, updates, email), commit=True)
            token = existing["token"]
        else:
            token = secrets.token_urlsafe(18)
            q("""INSERT INTO players (token, full_name, nickname, email, company, role,
                 consent_rules, consent_updates, created_at) VALUES (?,?,?,?,?,?,1,?,?)""",
              (token, name, nick, email, company, role, updates, datetime.now().isoformat(timespec="seconds")),
              commit=True)
        return self.send_json({"token": token, "nickname": nick})

    def me(self, p):
        rank, best = rank_of(p["id"])
        return {"nickname": p["nickname"], "rank": rank, "best": best,
                "rounds_left": rounds_left(p), "round_limit": ROUND_LIMIT}

    def match_start(self, d):
        p = self.player(d.get("token"))
        if not p:
            return self.error("Register before playing.", 401)
        if rounds_left(p) <= 0:
            return self.error(f"You've played all {ROUND_LIMIT} rounds for today. Your best score stays on "
                              "the leaderboard, so come back tomorrow for more.", 429)
        played = {r["scenario_id"] for r in q(
            "SELECT scenario_id FROM matches WHERE player_id=? AND score IS NOT NULL", (p["id"],))}
        fresh = [sc for sc in SCENARIOS if sc not in played] or list(SCENARIOS)
        scenario_id = random.choice(fresh)
        match_id = secrets.token_urlsafe(12)
        q("INSERT INTO matches (id, player_id, scenario_id, started_at, day) VALUES (?,?,?,?,?)",
          (match_id, p["id"], scenario_id, time.time(), today()), commit=True)
        # The scenario stays secret until the player starts the clock.
        return self.send_json({"match_id": match_id, "time_limit": GAME["time_limit"],
                               "rounds_left": rounds_left(p)})

    def match_clock(self, d):
        """Start the clock and reveal the scenario. Only the first call starts the clock."""
        p = self.player(d.get("token"))
        m = q("SELECT * FROM matches WHERE id=?", (str(d.get("match_id", "")),), one=True)
        if not p or not m or m["player_id"] != p["id"]:
            return self.error("Match not found.", 404)
        if m["score"] is not None:
            return self.error("This match is already scored.", 409)
        clock_at = m["clock_at"]
        if clock_at is None:
            clock_at = time.time()
            q("UPDATE matches SET clock_at=? WHERE id=?", (clock_at, m["id"]), commit=True)
        return self.send_json({"scenario_id": m["scenario_id"], "time_limit": GAME["time_limit"],
                               "seconds_left": max(0, GAME["time_limit"] - (time.time() - clock_at))})

    def finalize(self, m, cards, elapsed):
        if elapsed > GAME["time_limit"] + GRACE_SECONDS:
            cards = []  # abandoned round: counts as an empty build
        total, breakdown = score_match(SCENARIOS[m["scenario_id"]], [str(c) for c in cards], elapsed)
        q("UPDATE matches SET finished_at=?, cards=?, score=?, breakdown=? WHERE id=?",
          (time.time(), json.dumps(cards), total, json.dumps(breakdown), m["id"]), commit=True)
        return total, breakdown

    def match_finish(self, d):
        p = self.player(d.get("token"))
        m = q("SELECT * FROM matches WHERE id=?", (str(d.get("match_id", "")),), one=True)
        if not p or not m or m["player_id"] != p["id"]:
            return self.error("Match not found.", 404)
        if m["score"] is not None:
            return self.error("This match is already scored.", 409)
        cards = d.get("cards") if isinstance(d.get("cards"), list) else []
        elapsed = time.time() - (m["clock_at"] or m["started_at"])
        total, breakdown = self.finalize(m, cards, elapsed)
        return self.send_json({"score": total, "breakdown": breakdown, **self.me(p)})

    # -- admin endpoints
    def export_csv(self, scope):
        rows = q("""SELECT p.full_name, p.nickname, p.email, p.company, p.role, p.consent_updates,
                    p.prize, p.created_at, MAX(m.score) AS best, COUNT(m.score) AS games
                    FROM players p LEFT JOIN matches m ON m.player_id = p.id GROUP BY p.id""")
        if scope == "updates":
            rows = [r for r in rows if r["consent_updates"]]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["full_name", "nickname", "email", "company", "role", "agreed_to_updates",
                    "prize", "registered_at", "best_score", "rounds_played"])
        safe = lambda v: ("'" + v) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v
        for r in rows:
            w.writerow([safe(r["full_name"]), safe(r["nickname"]), r["email"], safe(r["company"]), r["role"],
                        "yes" if r["consent_updates"] else "no", safe(r["prize"] or ""),
                        r["created_at"], r["best"] if r["best"] is not None else "", r["games"]])
        body = buf.getvalue().encode("utf-8-sig")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="card-clash-{scope}-{today()}.csv"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def admin_draw(self, d):
        day = today() if d.get("today_only") else None
        sql = """SELECT DISTINCT p.id, p.full_name, p.nickname, p.email, p.company FROM players p
                 JOIN matches m ON m.player_id = p.id WHERE m.score IS NOT NULL AND p.prize IS NULL"""
        args = ()
        if day:
            sql += " AND m.day = ?"
            args = (day,)
        pool = q(sql, args)
        if not pool:
            return self.error("Nobody is eligible: every player has a prize or nobody has played yet.", 404)
        return self.send_json({"winner": dict(random.choice(pool)), "pool_size": len(pool)})

    def admin_award(self, d):
        prize = str(d.get("prize", "")).strip()[:80] or None
        q("UPDATE players SET prize=? WHERE id=?", (prize, int(d.get("player_id", 0))), commit=True)
        return self.send_json({"ok": True})

    def admin_bonus(self, d):
        pid = int(d.get("player_id", 0))
        p = q("SELECT * FROM players WHERE id=?", (pid,), one=True)
        if not p:
            return self.error("Player not found.", 404)
        extra = (p["bonus_rounds"] if p["bonus_day"] == today() else 0) + int(d.get("rounds", ROUND_LIMIT))
        q("UPDATE players SET bonus_day=?, bonus_rounds=? WHERE id=?", (today(), extra, pid), commit=True)
        return self.send_json({"ok": True, "rounds_left": rounds_left(q("SELECT * FROM players WHERE id=?", (pid,), one=True))})

    def admin_reset(self, d):
        if d.get("confirm") != "DELETE":
            return self.error('Type DELETE to confirm.')
        q("DELETE FROM matches", commit=True)
        q("DELETE FROM players", commit=True)
        return self.send_json({"ok": True})


def main():
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("\n  CloudStack Card Clash is running\n")
    for url in lan_urls():
        print(f"  Game:        {url}/")
        print(f"  Leaderboard: {url}/leaderboard")
        print(f"  Admin:       {url}/admin")
    print(f"\n  Admin PIN:   {ADMIN_PIN}")
    print(f"  Database:    {DB_PATH}\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
