# Vidiprinter+ website

The website for the Vidiprinter+ iPhone app, served by GitHub Pages from `docs/index.html`.

Live at https://mikejmccarthy.github.io/vidiprinter-website/

Run the commands below from this folder (`cd ~/Developer/VidiprinterWebsite`).

| File | What's in it |
|---|---|
| `content.json` | Every word on the page: header, title, tabs, the features, the download button and the footer. Also the App Store link and the typing speeds |
| `highlights.json` | The feed's rows, written by `pick` each weekend |
| `template.html` | The layout and styling |
| `docs/index.html` | The page, built from the three files above. Don't edit it: the next build replaces it |
| `site.py` | Picks the highlights, builds the page and publishes it |

## Each weekend (Sunday evening or Monday)

```bash
python3 site.py pick --dry-run
```

This shows the six rows it would choose from Friday to today, each with a different type of stat. If they look right, write them, rebuild the page and put it live:

```bash
python3 site.py pick
```

```bash
python3 site.py publish
```

To swap a row, edit `highlights.json`, then run `publish`. `--goals` and `--fulltimes` change how many rows it picks (4 and 2 by default). `--weekend 2026-10-31` picks an earlier weekend; give its Saturday.

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
