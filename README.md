# Field notes

## Local use

```sh
pip install playwright==1.55.0 openpyxl==3.1.5
python -m playwright install chromium
python test_collector.py
python test_demand.py
python collect_latitude.py
python rebuild_workbook.py
python -m http.server 8000
```

Open http://localhost:8000. Keep earlier keys in `snapshots.json`; same-day updates replace only that date. Check the page and workbook before committing `snapshots.json` and `workbook.b64` to `main`.

Actions > Daily update > Run workflow performs the same update and publishes the page. The daily schedule is 21:17 UTC and may start late. Failed validation keeps the previous published data. Source dates are shown on the page; a new check does not imply a new release. Structural changes or large moves need manual review. The data, files and history are public.
