# Compute pricing monitor

A static dashboard with date-keyed history and an Excel download. It runs without Instinct, a database, or a build step.

## Run locally

Download or clone this repository, then from its folder run:

```sh
python3 -m http.server 8000
```

Open http://localhost:8000. Do not double-click `index.html`: browsers can block its JSON request under `file://`.

## Refresh the data yourself

1. Read the current source sites, or use your own collector to produce the same schema as `snapshots.json`. Your Latitude script can help collect prices, but its output needs mapping into this schema; it is not a drop-in refresh for this dashboard.
2. Copy the latest entry under `snapshots` to a new `YYYY-MM-DD` key, change its `date` and `capturedAt`, and replace values with verified readings. Keep every earlier date. A second refresh on the same date replaces only that date's entry. JSON `null` means unverified or unavailable, not zero.
3. For Latitude, check Hourly, Monthly, and Paid yearly separately. Prices are USD per whole server, not per GPU. Keep yearly totals annual. Do not calculate a price that should be read. Check location prices and stock separately. Keep source dates for OpenRouter and Ramp; Ramp's volume view is indexed spend, not raw token counts or USD.
4. Run `python3 -m json.tool snapshots.json > /dev/null`, then run `python3 rebuild_workbook.py` to rebuild `history.xlsx` and `workbook.b64` from all snapshots. Preview locally and check prices, notes, and the download.
5. In GitHub, commit changed `snapshots.json` and `workbook.b64` to `main` (or use Add file > Upload files and replace those files). The Publish dashboard changes workflow republishes Pages automatically. Check the deployment in Actions, then reload the site.

`Reload published data` reads the stored JSON again. It does not collect from source websites. Latitude is refreshed by the daily workflow below. Future collection can be manual or your own script, without Instinct.

## Files and sources

- `index.html`: dashboard
- `snapshots.json`: full history, currently one baseline dated 2026-10-15
- `workbook.b64`: encoded Excel workbook of all stored dates; the dashboard decodes it into a normal `.xlsx` download. The exporter also produces local `history.xlsx`.
- `rebuild_workbook.py`: offline exporter; requires `pip install openpyxl`

No earlier Claude history was supplied, so a price change cannot be established until another date is stored. Public site visitors can download the data. VM availability was not checked behind login.

Sources: https://www.latitude.sh/pricing , https://openrouter.ai/rankings , https://ramp.com/data/ai-index . OpenRouter rankings data is CC BY 4.0: https://creativecommons.org/licenses/by/4.0/ .

## Daily Latitude auto-update

Actions > Latitude daily update > Run workflow runs `collect_latitude.py`, rebuilds the workbook, commits only `snapshots.json` and `workbook.b64`, then deploys Pages. It runs daily at 21:17 UTC. GitHub schedules can start late. No VM or paid service is used by this workflow.

The collector reads Hourly, Monthly and Paid yearly prices directly, plus every metal server's location and stock tables. It does not derive missing prices. It rejects failed pages, missing/duplicate plans, incomplete terms, invalid prices, changed plan/hardware/location sets, or any price move over 50% from the previous snapshot. Rejected collections stop before publication, leaving the last good data live. A legitimate large change or new plan needs manual review and a baseline update before automation resumes. Source changes can still defeat a scraper; review failures in Actions.

One Sydney-calendar-date key is written per day. Same-day runs replace only that day's entry; older dates are kept. OpenRouter and Ramp are not scraped by this workflow yet: their verified figures and original source periods are carried forward and shown on the dashboard. Do not treat a new Latitude capture date as fresh AI-demand collection. VM stock/location data is still unverified.

Collection JSON and an overview screenshot are kept in the `latitude-collection` artifact for 7 days. The workflow's collection job has repository contents write permission to commit these data files; its deployment job has Pages deployment permission. It uses only the standard GitHub token, with no stored personal secrets. `Publish dashboard changes` separately redeploys manual edits to the three public assets.
