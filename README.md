# Vidiprinter+ website

The website for the Vidiprinter+ iPhone app, served by GitHub Pages from `docs/index.html`.

Live at https://vidiprinterplus.app (GitHub Pages; the domain is set in `docs/CNAME` and its DNS is at Cloudflare).

Run the commands below from this folder (`cd ~/Developer/VidiprinterWebsite`).

| File | What's in it |
|---|---|
| `content.json` | Every word on the page: header, title, tabs, the features, the download button and the footer. Also the App Store link and the typing speeds |
| `highlights.json` | The feed's six rows, written by `top` (or `pick`) each weekend |
| `shortlist.json` | The weekend's top 10, written by `pick`. Not published |
| `template.html` | The home page's layout |
| `privacy.html` | The privacy policy's text, as HTML |
| `style.css`, `privacy-template.html` | The shared styling, and the privacy page's layout |
| `docs/` | The built site: `index.html`, `privacy.html` and `style.css`. Don't edit these: the next build replaces them |
| `site.py` | Lists the weekend's top 10, writes your six, builds the page and publishes it |

## Each weekend (Sunday evening or Monday)

```bash
python3 site.py pick
```

This reads Friday to today and lists the weekend's top 10 rows, strongest first, each led by a different type of stat. Under each row is its stat line, and sometimes a second line marked `+`, which appears only if no other row on the page has that type. Then it asks for your six:

```
Your 6, in order, top of the page first (e.g. 3 1 7 2 9 5):
```

The first number you give sits at the top of the page. The feed prints from the bottom up, so that row types last. Your choice is written to `highlights.json` and the page is rebuilt. Check `docs/index.html` in a browser, then put it live:

```bash
python3 site.py publish
```

To change your mind, run `top` with new numbers. It reuses the same top 10 and doesn't fetch the feed again:

```bash
python3 site.py top 2 5 1 8 3 9
```

`top` with no numbers shows the list again and asks. `pick --dry-run` shows the top 10 without writing anything. `--goals` and `--fulltimes` change the mix of the 10 (7 and 3 by default). `--weekend 2026-10-31` picks an earlier weekend; give its Saturday. You can still edit `highlights.json` by hand, then run `publish`.

`pick` reads the production feed with a session token. It finds the token in `$VIDI_TOKEN`, then `~/.config/vidiprinter/token`, then Commentator Pro's saved one. If the server refuses it, refresh the token and run `pick` again.

## Changing the words

Edit `content.json`, then run this:

```bash
python3 site.py build
```

Check `docs/index.html` in a browser, then run `publish`.

- `~~words~~` strikes words through.
- The colours are yellow, cyan, green, red, magenta and grey.
- `typing` sets how fast the feed and the features type out, in characters a second. The app types at 36.
- `{dates}` in `feedNote` becomes the weekend's dates.
- A stray comma before a closing `]` or `}` is fine. For any other mistake, the build names the line.
- Write a double quote inside text as `\"`. Apostrophes are fine as they are.
- When the app is live, put its link in `appStoreUrl`. The buttons then change from COMING SOON to GET THE APP and DOWNLOAD ON THE APP STORE.

## The privacy policy

It's at https://vidiprinterplus.app/privacy.html. Edit `privacy.html`, update the date at the top, then run `build` and `publish`. The app and App Store Connect link to this address.
