#!/usr/bin/env python3
"""The Vidiprinter+ website: build it, and refresh its feed from the weekend.

    python3 site.py pick [--weekend 2026-10-31] [--goals 7] [--fulltimes 3] [--dry-run]
    python3 site.py top [3 1 7 2 9 5]
    python3 site.py build
    python3 site.py publish

pick   reads the production feed for a weekend (Friday to Monday, up to today;
       --weekend is its Saturday, the latest one by default) and writes its
       top 10 rows, strongest first, to shortlist.json: goals with a stat
       line, then full times, each led by a different type of stat (similar
       rules count as one), at most two goals from one league and one row
       from a match, with a nudge for the Premier League, the Champions
       League and the Europa League. Lines the app no longer shows, and lines
       too long for a phone, are left out. A goal later ruled out is never
       picked. Then it asks for your six, in order. --dry-run prints the
       shortlist without writing anything.
top    writes the shortlist rows you name to highlights.json, top of the page
       first, adds a strong second line where its type isn't already on the
       page, then builds. With no numbers it shows the shortlist and asks.
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
SHORTLIST = os.path.join(HERE, "shortlist.json")     # pick's top 10; not published
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
TOP = 6                      # rows on the page


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
            sys.exit("No session token. Terminal may not be allowed to read Commentator Pro's saved one "
                     "(macOS protects other apps' data). Write the token to ~/.config/vidiprinter/token, "
                     "or set VIDI_TOKEN.")

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


def shown_lines(rows):
    """Each row's lead line, then a strong second line whose type isn't
    already on the page. `rows` are shortlist rows, top of the page first."""
    types = {r["lead"]["type"] for r in rows}
    out = []
    for r in rows:
        shown = [r["lead"]["text"]]
        for i in r["others"]:
            if len(shown) >= LINES_PER_ROW:
                break
            if i["priority"] >= SECOND_LINE_MIN and i["type"] not in types:
                shown.append(i["text"])
                types.add(i["type"])
        out.append(shown)
    return out


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
    """Fetch the weekend, write its top rows to shortlist.json, then ask
    which to show (when run in a terminal)."""
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
        sys.exit("No rows with stat lines that weekend; nothing is written.")
    if len(chosen) < goals_n + fts_n:
        print(f"Only {len(chosen)} different stat types that weekend, so {len(chosen)} rows.")
    # The strongest first, goals and full times together.
    chosen.sort(key=lambda e: -(e["_lead"]["priority"] + FAVOURED.get(e.get("leagueId"), 0)))

    def club(name, cid, side, e):
        n = short.get(cid, name)
        return n.upper() if e.get("emphasis") == side else n

    rows = []
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
        row["lead"] = {"text": e["_lead"]["text"], "type": stat_type(e["_lead"])}
        row["others"] = [{"text": i["text"], "type": stat_type(i), "priority": i["priority"]}
                         for i in e["_lines"] if i is not e["_lead"]]
        rows.append(row)

    print(f"\nThe top {len(rows)} of {len(goals)} goals and {len(fts)} full times with lines, "
          "strongest first, each a different type of stat:\n")
    show_shortlist(rows)
    if dry:
        print("\n--dry-run: nothing written.")
        return
    with open(SHORTLIST, "w") as f:
        json.dump({"_help": "Written by `site.py pick`. Choose from it with `site.py top`.",
                   "dates": dates_text(played), "rows": rows}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nWrote {os.path.relpath(SHORTLIST, ROOT)}")
    if sys.stdin.isatty():
        top(ask(len(rows)))
    else:
        print(f"Now choose your {TOP}, top of the page first: python3 site.py top 3 1 7 2 9 5")


def show_shortlist(rows):
    for n, r in enumerate(rows, 1):
        print(f"{n:>3}  {r['code']:4} {r['label']:4} {r['score']}" + (f"  {r['player']}" if r.get("player") else ""))
        print(f"           › {r['lead']['text']}   [{r['lead']['type']}]")
        second = next((i for i in r["others"] if i["priority"] >= SECOND_LINE_MIN), None)
        if second:
            print(f"           + {second['text']}   [{second['type']}, if no other row has it]")


def ask(n):
    while True:
        reply = input(f"\nYour {min(TOP, n)}, in order, top of the page first (e.g. 3 1 7 2 9 5): ")
        try:
            return parse_choice(reply.replace(",", " ").split(), n)
        except ValueError as err:
            print(err)


def parse_choice(args, n):
    try:
        picks = [int(a) for a in args]
    except ValueError:
        raise ValueError("Give the rows' numbers, separated by spaces.")
    if not picks:
        raise ValueError("Give at least one number.")
    if bad := [p for p in picks if not 1 <= p <= n]:
        raise ValueError(f"The shortlist runs from 1 to {n}; {', '.join(map(str, bad))} isn't on it.")
    if len(set(picks)) < len(picks):
        raise ValueError("Each row once only.")
    return picks


def top(picks):
    """Write the chosen shortlist rows to highlights.json, top of the page
    first, then build. The page prints from the bottom up, so the first row
    chosen types last and finishes on top."""
    if not os.path.exists(SHORTLIST):
        sys.exit("No shortlist yet: run python3 site.py pick first.")
    sl = load(SHORTLIST)
    try:
        picks = parse_choice(picks, len(sl["rows"])) if picks and isinstance(picks[0], str) else picks
    except ValueError as err:
        sys.exit(str(err))
    if len(picks) != min(TOP, len(sl["rows"])):
        print(f"Note: {len(picks)} rows, not {TOP}.")
    chosen = [sl["rows"][p - 1] for p in picks]
    rows = []
    for r, lines in zip(chosen, shown_lines(chosen)):
        row = {k: v for k, v in r.items() if k not in ("lead", "others")}
        row["lines"] = lines
        rows.append(row)
    rows.reverse()                       # highlights.json is in print order
    print("\nThe feed, top of the page first:\n")
    for r in reversed(rows):
        print(f"  {r['code']:4} {r['label']:4} {r['score']}" + (f"  {r['player']}" if r.get("player") else ""))
        for l in r["lines"]:
            print(f"            › {l}")
    data = {
        "_help": "The feed on the website, in the order it prints (the last row ends up at the top). "
                 "Written by `site.py top`; edit by hand if you like, then run `site.py build`. "
                 "Colours: yellow, cyan, green, red, magenta, grey.",
        "dates": sl["dates"],
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
    p.add_argument("command", choices=["pick", "top", "build", "publish"])
    p.add_argument("rows", nargs="*", help="top: the shortlist numbers to show, top of the page first")
    p.add_argument("--weekend", help="pick: the weekend's Saturday, yyyy-MM-dd (default: the latest)")
    p.add_argument("--goals", type=int, default=7, help="pick: how many goals on the shortlist (default 7)")
    p.add_argument("--fulltimes", type=int, default=3, help="pick: how many full times on the shortlist (default 3)")
    p.add_argument("--dry-run", action="store_true", help="pick: print the shortlist, write nothing")
    a = p.parse_args()
    if a.rows and a.command != "top":
        p.error("row numbers go with top")
    if a.command == "pick":
        pick(a.weekend, a.goals, a.fulltimes, a.dry_run)
    elif a.command == "top":
        if not a.rows:
            if not os.path.exists(SHORTLIST):
                sys.exit("No shortlist yet: run python3 site.py pick first.")
            sl = load(SHORTLIST)
            show_shortlist(sl["rows"])
            top(ask(len(sl["rows"])))
        else:
            top(a.rows)
    elif a.command == "publish":
        publish()
    else:
        build()
