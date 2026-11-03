#!/usr/bin/env python3
"""The Vidiprinter+ website: build it, and refresh its feed from the weekend.

    python3 site.py pick [--weekend 2026-10-31] [--goals 4] [--fulltimes 2] [--dry-run]
    python3 site.py build
    python3 site.py publish

pick   reads the production feed for a weekend (Friday to Monday, up to today;
       --weekend is its Saturday, the latest one by default), chooses its best
       rows and writes them to highlights.json, then builds the page.
       Goals with a stat line, best line first, each row a different type of
       stat (similar rules count as one), at most two from one league and one
       from a match, with a nudge
       for the Premier League, the Champions League and the Europa League. Then
       the best full times, one a league. Lines the app no longer shows, and
       lines too long for a phone, are left out. A goal later ruled out is never
       picked. --dry-run prints the rows without writing anything.
build  makes docs/index.html from template.html, content.json (every word on
       the page) and highlights.json (the feed's rows), and docs/privacy.html
       from privacy-template.html and privacy.html (the policy's text). Run it after editing
       either file by hand, then publish.

publish builds, commits the page and its sources, and pushes; GitHub Pages
       serves the new page a minute or two later.

Read-only against the server. The token comes from $VIDI_TOKEN, else
~/.config/vidiprinter/token, else Commentator Pro's saved one.
"""
import argparse, datetime as dt, html, json, os, plistlib, re, subprocess, sys
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
CONTENT = os.path.join(HERE, "content.json")
HIGHLIGHTS = os.path.join(HERE, "highlights.json")
TEMPLATE = os.path.join(HERE, "template.html")
DOCS = os.path.join(HERE, "docs")                 # GitHub Pages serves docs/
OUT = os.path.join(DOCS, "index.html")
STYLE = os.path.join(HERE, "style.css")
PRIVACY = os.path.join(HERE, "privacy.html")
PRIVACY_TEMPLATE = os.path.join(HERE, "privacy-template.html")
PRIVACY_OUT = os.path.join(DOCS, "privacy.html")

COLOURS = {"yellow", "cyan", "green", "red", "magenta", "grey"}

# MARK: choosing

# Lines the app dropped (22 Oct rules doc), as in Tools/saturday.py.
GONE = {"late_equaliser", "late_lead", "club_milestone"}
LONGEST_LINE = 100           # characters; longer lines wrap badly on a phone
LINES_PER_ROW = 2
SECOND_LINE_MIN = 65     # a second line only when it is a strong one
# A nudge (added to a line's priority) for the names most visitors know.
FAVOURED = {8: 8, 2: 8, 5: 5, 501: 3, 9: 2}   # PL, UCL, UEL, SPL, Championship
PER_LEAGUE_GOALS = 2


class Server:
    """Read-only calls to the production server, as the app makes them.
    The session token comes from $VIDI_TOKEN, else ~/.config/vidiprinter/token,
    else Commentator Pro's saved token. It is never printed or written down."""
    BASE = "https://commentator-pro-server.onrender.com"
    # The app's launch leagues: England, Scotland and UEFA.
    LEAGUES = ("2,5,8,9,12,14,17,20,24,27,39,44,45,501,504,507,510,513,516,519,525,528,"
               "1092,1328,1506,1593,2286,2398")
    MAC_PREFS = os.path.expanduser("~/Library/Containers/com.commentator.FootballCommentator.public/Data/"
                                   "Library/Preferences/com.commentator.FootballCommentator.public.plist")

    @classmethod
    def token(cls):
        if os.environ.get("VIDI_TOKEN"):
            return os.environ["VIDI_TOKEN"].strip()
        path = os.path.expanduser("~/.config/vidiprinter/token")
        if os.path.exists(path):
            return open(path).read().strip()
        try:
            with open(cls.MAC_PREFS, "rb") as f:
                return plistlib.load(f)["sessionToken"]
        except (OSError, KeyError):
            sys.exit("No session token: set VIDI_TOKEN or write it to ~/.config/vidiprinter/token")

    @classmethod
    def get(cls, path, tok=""):
        req = urllib.request.Request(cls.BASE + path, headers={"Authorization": f"Bearer {tok}"} if tok else {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as err:
            if err.code in (401, 403):
                sys.exit("The server refused the token: it has expired or its subscription has lapsed. "
                         "Refresh it (see README) and run pick again.")
            raise


def broadcast_caps(surname):
    """McGree → McGREE, MacDonald → MacDONALD, Mackie → MACKIE (NameRules.swift)."""
    def word(w):
        for p in ("Mac", "Mc"):
            if w.startswith(p) and len(w) > len(p) and w[len(p)].isupper():
                return p + w[len(p):].upper()
        return w.upper()
    return re.sub(r"[^ -]+", lambda m: word(m.group(0)), surname)


PARTICLES = {"de", "da", "di", "do", "dos", "das", "du", "del", "della", "der", "den",
             "van", "von", "le", "la", "el", "al", "ter", "ten", "st", "st.", "mac", "bin", "ben"}
SURNAME_FIRST = {"KOR", "PRK", "CHN", "TPE", "HKG", "MAC"}


def display_name(first, last, full, nationality):
    if not last:
        words = (full or first or "").split()
        if len(words) < 2:
            first, last = "", " ".join(words)
        else:
            i = len(words) - 1
            while i > 1 and words[i - 1].lower() in PARTICLES:
                i -= 1
            first, last = " ".join(words[:i]), " ".join(words[i:])
    last = broadcast_caps(last)
    parts = [last, first] if (nationality or "").upper() in SURNAME_FIRST else [first or "", last]
    return " ".join(p for p in parts if p)


def scorer(e):
    name, tag = e.get("player") or "", ""
    m = re.search(r" \([^)]*\)$", name)
    if m:
        name, tag = name[:m.start()], m.group(0)
    return display_name(e.get("playerFirstName"), e.get("playerLastName"), name, e.get("playerNationality")) + tag


def usable(e):
    return sorted((i for i in e.get("insights") or []
                   if i["kind"] not in GONE and len(i["text"]) <= LONGEST_LINE),
                  key=lambda i: -i["priority"])


def minute_of(e):
    m = re.match(r"(\d+)(?:\+(\d+))?", e.get("minute") or "")
    if not m:
        return 0
    n = int(m.group(1)) + int(m.group(2) or 0)
    return n + (15 if n > 45 else 0)          # half time


def when(e):
    ko = dt.datetime.fromisoformat(e["kickoff"])
    return ko + dt.timedelta(minutes=115 if e["kind"] == "fullTime" else minute_of(e))


# Rules that read as the same kind of stat count as one type, so the page
# never shows, say, a comeback and an away comeback.
SAME_TYPE = {
    "ft_hat_trick": "hat_trick",
    "away_comeback": "comeback", "comeback_draw": "comeback", "turnaround": "comeback",
    "table_knock_on": "table",
    "league_drought": "drought",
    "scoring_streak": "scoring_run",
    "first_away_win": "first_win_in", "h2h_first_win": "first_win_in", "h2h_first_away_win": "first_win_in",
    "venue_win_run": "win_run", "h2h_win_run": "win_run",
    "venue_unbeaten_run": "unbeaten_run", "h2h_unbeaten_run": "unbeaten_run",
    "venue_losing_run": "losing_run", "form_losses": "losing_run",
    "venue_winless_run": "winless_run",
    "form_one_win": "form",
    "clean_sheet_drought_over": "clean_sheet", "clean_sheet_milestone": "clean_sheet",
    "clean_sheet_top": "clean_sheet", "first_clean_sheet": "clean_sheet",
}


def stat_type(line):
    return SAME_TYPE.get(line["kind"], line["kind"])


def choose(entries, n, per_league, types, per_match=1):
    """Each row led by a stat type no other row has (`types`, shared across
    calls and added to), the strongest first. A row's lead is its best line
    of a type still free."""
    def lead(e):
        return next((i for i in e["_lines"] if stat_type(i) not in types), None)

    picked, leagues, matches = [], {}, {}
    pool = list(entries)
    while len(picked) < n:
        options = [(l["priority"] + FAVOURED.get(e.get("leagueId"), 0), e, l) for e in pool
                   if leagues.get(e.get("leagueId"), 0) < per_league
                   and matches.get(e["fixtureId"], 0) < per_match
                   and (l := lead(e))]
        if not options:
            break
        _, e, l = max(options, key=lambda o: o[0])
        pool.remove(e)
        picked.append(e)
        e["_lead"] = l
        types.add(stat_type(l))
        leagues[e.get("leagueId")] = leagues.get(e.get("leagueId"), 0) + 1
        matches[e["fixtureId"]] = matches.get(e["fixtureId"], 0) + 1
    return picked


def shown_lines(rows, types):
    """The lead line, then a strong second line whose type isn't on the page."""
    for e in rows:
        e["_shown"] = [e["_lead"]]
        for i in e["_lines"]:
            if len(e["_shown"]) >= LINES_PER_ROW:
                break
            if i is not e["_lead"] and i["priority"] >= SECOND_LINE_MIN and stat_type(i) not in types:
                e["_shown"].append(i)
                types.add(stat_type(i))


def weekend_days(saturday, today):
    days = [saturday + dt.timedelta(days=k) for k in (-1, 0, 1, 2)]
    return [d for d in days if d <= today]


def dates_text(days):
    fmt = lambda d, year: f"{d.day} {d:%B}" + (f" {d.year}" if year else "")
    if len(days) == 1:
        return f"{days[0]:%A} {fmt(days[0], True)}"
    a, b = days[0], days[-1]
    return f"{fmt(a, a.year != b.year)} to {fmt(b, True)}"


def pick(weekend, goals_n, fts_n, dry):
    api = Server
    tok = api.token()
    today = dt.date.today()
    if weekend:
        saturday = dt.date.fromisoformat(weekend)
    else:
        saturday = today - dt.timedelta(days=(today.weekday() - 5) % 7)
    days = weekend_days(saturday, today)
    if not days:
        sys.exit(f"The weekend of {saturday} hasn't started yet.")

    codes = {l["leagueId"]: l.get("code") or "" for l in api.get("/v1/leagues/catalog", "")["leagues"]}
    short = {c["id"]: c["short"] for c in api.get("/v1/clubs/short-names", "")}

    entries, played = [], []
    for d in days:
        es = api.get(f"/v1/vidiprinter?date={d}&leagues={api.LEAGUES}", tok)["entries"]
        print(f"{d:%a %d %b}: {len(es)} entries, {sum(1 for e in es if e.get('insights'))} with lines")
        if es:
            played.append(d)
        entries += es

    ruled_out = {(e["fixtureId"], e.get("playerId") or e.get("player")) for e in entries if e["kind"] == "noGoal"}
    for e in entries:
        e["_lines"] = usable(e)
    goals = [e for e in entries if e["kind"] == "goal" and e.get("player") and e["_lines"]
             and (e["fixtureId"], e.get("playerId") or e.get("player")) not in ruled_out]
    fts = [e for e in entries if e["kind"] == "fullTime" and e["_lines"]]

    types = set()
    chosen = choose(goals, goals_n, PER_LEAGUE_GOALS, types)
    used = {e["fixtureId"] for e in chosen}
    chosen += choose([e for e in fts if e["fixtureId"] not in used], fts_n, 1, types)
    if not chosen:
        sys.exit("No rows with stat lines that weekend; highlights.json is unchanged.")
    if len(chosen) < goals_n + fts_n:
        print(f"Only {len(chosen)} different stat types that weekend, so {len(chosen)} rows.")
    shown_lines(chosen, types)
    chosen.sort(key=when)

    def club(name, cid, side, e):
        n = short.get(cid, name)
        return n.upper() if e.get("emphasis") == side else n

    rows, row_types = [], []
    for e in chosen:
        row = {
            "code": codes.get(e.get("leagueId"), ""),
            "label": "GOAL" if e["kind"] == "goal" else "FT",
            "colour": "yellow" if e["kind"] == "goal" else "cyan",
            "score": f"{club(e['homeTeam'], e['homeTeamId'], 'home', e)} {e['homeScore']}-{e['awayScore']} "
                     f"{club(e['awayTeam'], e['awayTeamId'], 'away', e)}",
        }
        if e["kind"] == "goal":
            row["player"] = f"{scorer(e)} {e.get('minute') or ''}".strip()
            if e.get("assist"):
                row["assist"] = display_name(None, None, e["assist"], None)
        row["lines"] = [i["text"] for i in e["_shown"]]
        row_types.append(", ".join(stat_type(i) for i in e["_shown"]))
        rows.append(row)

    print(f"\nPicked {len(rows)} of {len(goals)} goals and {len(fts)} full times with lines (in print order):\n")
    for r, t in zip(rows, row_types):
        print(f"  {r['code']:4} {r['label']:4} {r['score']}" + (f"  {r['player']}" if r.get("player") else "") + f"   [{t}]")
        for l in r["lines"]:
            print(f"            › {l}")
    if dry:
        print("\n--dry-run: nothing written.")
        return
    data = {
        "_help": "The feed on the website, in the order it prints (the last row ends up at the top). "
                 "Written by `site.py pick`; edit by hand if you like, then run `site.py build`. "
                 "Colours: yellow, cyan, green, red, magenta, grey.",
        "dates": dates_text(played),
        "rows": rows,
    }
    with open(HIGHLIGHTS, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nWrote {os.path.relpath(HIGHLIGHTS, ROOT)}")
    build()


# MARK: building

def load(path):
    text = open(path).read()
    # A comma left before a closing ] or } (deleting the last line of a list,
    # say) is forgiven; it's the easiest slip when editing by hand. Strings
    # are matched first so a comma inside one is never touched.
    text = re.sub(r'("(?:[^"\\]|\\.)*")|,(\s*[\]}])', lambda m: m.group(1) or m.group(2), text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        sys.exit(f"{os.path.relpath(path, ROOT)}, line {err.lineno}: {err.msg}. Look there for a missing "
                 "comma between items, or a missing or unescaped \" (write \\\" inside text).")


def esc(s):
    return html.escape(str(s), quote=True)


def rich(s):
    """Escaped, with ~~words~~ struck through."""
    return re.sub(r"~~(.+?)~~", r'<span class="strike">\1</span>', esc(s))


def colour(c, where):
    if c not in COLOURS:
        sys.exit(f"{where}: colour {c!r} isn't one of {', '.join(sorted(COLOURS))}.")
    return f"c-{c}"


def row_html(code, label, col, title, player=None, assist=None, lines=(), where=""):
    out = [f'<div class="row"><span class="code">{esc(code)}</span><div>',
           f'<div class="head"><span class="lab {colour(col, where)}">{esc(label)}</span>'
           f'<span class="score">{rich(title)}</span></div>']
    if player:
        out.append(f'<div class="player">{esc(player)}</div>')
    if assist:
        out.append(f'<div class="assist">Assist: {esc(assist)}</div>')
    for l in lines:
        out.append(f'<div class="ins"><span class="chev">›</span><span>{rich(l)}</span></div>')
    out.append("</div></div>")
    return "".join(out)


STORE_ICON = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M16.4 12.6c0-2.5 2-3.6 '
              '2.1-3.7-1.2-1.7-3-1.9-3.6-2-1.5-.2-3 .9-3.8.9s-2-.9-3.3-.9c-1.7 0-3.3 1-4.2 2.5-1.8 3.1-.5 7.7 1.3 '
              '10.2.9 1.2 1.9 2.6 3.2 2.6 1.3-.1 1.8-.8 3.3-.8s2 .8 3.3.8c1.4 0 2.3-1.3 3.1-2.5 1-1.4 1.4-2.8 '
              '1.4-2.9 0 0-2.8-1.1-2.8-4.2zM13.9 5.1c.7-.8 1.2-2 1-3.1-1 0-2.2.7-2.9 1.5-.6.7-1.2 1.9-1 3 1.1.1 '
              '2.2-.6 2.9-1.4z"/></svg>')


def build():
    c = load(CONTENT)
    h = load(HIGHLIGHTS) if os.path.exists(HIGHLIGHTS) else {"dates": "", "rows": []}
    url = (c.get("appStoreUrl") or "").strip()
    typing = c.get("typing") or {}
    speeds = {}
    for k, default in (("feed", 36), ("features", 70)):
        v = typing.get(k, default)
        if not isinstance(v, (int, float)) or not 5 <= v <= 1000:
            sys.exit(f"content.json: typing.{k} should be a number of characters a second, 5 to 1000, not {v!r}.")
        speeds[k] = v

    feed = [row_html(r.get("code", ""), r["label"], r.get("colour", "yellow"), r["score"],
                     r.get("player"), r.get("assist"), r.get("lines", []), where=f"highlights row {n}")
            for n, r in enumerate(h["rows"], 1)]
    feats = [row_html(f["code"], f["label"], f.get("colour", "cyan"), f["title"], lines=f.get("lines", []),
                      where=f"features item {n}")
             for n, f in enumerate(c["features"], 1)]

    if url:
        get_link = f'<a class="get" href="{esc(url)}">{esc(c["header"]["getApp"])}</a>'
        store = f'<a class="store" href="{esc(url)}">{STORE_ICON} {esc(c["download"]["button"])}</a>'
    else:
        get_link = f'<a class="get" href="#get">{esc(c["header"]["comingSoon"])}</a>'
        store = f'<a class="store soon" aria-disabled="true">{STORE_ICON} {esc(c["download"]["comingSoon"])}</a>'

    computed = {
        "feed_rows": "\n".join(reversed(feed)),     # newest at the top
        "feature_rows": "\n".join(feats),
        "get_link": get_link,
        "store_button": store,
        "typing_speeds": json.dumps(speeds),
    }
    plain = {"feed_note": c["feedNote"].replace("{dates}", h.get("dates", ""))}

    def lookup(key):
        v = c
        for part in key.split("."):
            if not isinstance(v, dict) or part not in v:
                sys.exit(f"template.html asks for {key!r}, which content.json doesn't have.")
            v = v[part]
        return v

    # On the privacy page the button leads to the home page's button.
    computed["get_link_home"] = get_link.replace('href="#get"', 'href="./#get"')
    computed["policy"] = open(PRIVACY).read()

    def fill(template):
        page = open(template).read()
        page = re.sub(r"\{\{\{([\w.]+)\}\}\}", lambda m: computed[m.group(1)] if m.group(1) in computed
                      else rich(lookup(m.group(1))), page)
        return re.sub(r"\{\{([\w.]+)\}\}", lambda m: esc(plain[m.group(1)]) if m.group(1) in plain
                      else esc(lookup(m.group(1))), page)

    os.makedirs(DOCS, exist_ok=True)
    for template, out in ((TEMPLATE, OUT), (PRIVACY_TEMPLATE, PRIVACY_OUT)):
        with open(out, "w") as f:
            f.write(fill(template))
    with open(STYLE) as src, open(os.path.join(DOCS, "style.css"), "w") as f:
        f.write(src.read())
    print(f"Built {os.path.relpath(OUT, ROOT)}: {len(feed)} feed rows, {len(feats)} features, "
          + ("App Store link set." if url else "no App Store link yet (shows coming soon)."))


# MARK: publishing

def publish():
    """Commit the built page and its sources, and push: GitHub Pages then
    serves the new page within a minute or two."""
    build()
    git = lambda *a: subprocess.run(["git", "-C", HERE, *a], check=True)
    git("add", "content.json", "highlights.json", "template.html", "privacy-template.html", "privacy.html",
        "style.css", "docs")
    if subprocess.run(["git", "-C", HERE, "diff", "--cached", "--quiet"]).returncode == 0:
        print("Nothing has changed since the last publish.")
        return
    dates = load(HIGHLIGHTS).get("dates", "")
    git("commit", "-q", "-m", f"Update the website: {dates}" if dates else "Update the website")
    git("push", "-q")
    print("Pushed. The live site updates in a minute or two.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["pick", "build", "publish"])
    p.add_argument("--weekend", help="pick: the weekend's Saturday, yyyy-MM-dd (default: the latest)")
    p.add_argument("--goals", type=int, default=4, help="pick: how many goals (default 4)")
    p.add_argument("--fulltimes", type=int, default=2, help="pick: how many full times (default 2)")
    p.add_argument("--dry-run", action="store_true", help="pick: print the rows, write nothing")
    a = p.parse_args()
    if a.command == "pick":
        pick(a.weekend, a.goals, a.fulltimes, a.dry_run)
    elif a.command == "publish":
        publish()
    else:
        build()
