"""Read-only Latitude trial. Keeps native raw values; never updates snapshots."""
import json
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path("trial-output")
out.mkdir(exist_ok=True)
report = {"capturedAt": datetime.now(timezone.utc).isoformat(), "source": "https://www.latitude.sh/pricing", "snapshotsUpdated": False}
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        response = page.goto(report["source"], wait_until="domcontentloaded", timeout=60000)
        report["httpStatus"] = response.status if response else None
        page.locator("table").first.wait_for(timeout=30000)
        report["title"] = page.title()
        report["billingViews"] = {}
        for term in ["Hourly", "Monthly", "Paid yearly"]:
            buttons = page.get_by_role("button", name=term, exact=True)
            count = buttons.count()
            if not count:
                raise RuntimeError("Missing billing buttons: " + term)
            for index in range(count):
                buttons.nth(index).click()
            report["billingViews"][term] = page.locator("table").evaluate_all("tables => tables.map(t => [...t.rows].map(r => [...r.cells].map(c => c.innerText)))")
            page.screenshot(path=str(out / (term.replace(" ", "-") + ".png")), full_page=True)
        if not all("g4.b300.large" in json.dumps(v) for v in report["billingViews"].values()):
            raise RuntimeError("Required GPU plan absent in captured tables")
        report["outcome"] = "captured"
        report["note"] = "Native displayed table strings only. No equivalent-price arithmetic. Detail/location validation still required before promotion."
        browser.close()
except Exception as e:
    report["outcome"] = "failed"
    report["error"] = str(e)
finally:
    (out / "latitude-raw.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in report.items() if k != "billingViews"}, indent=2))
if report["outcome"] != "captured":
    raise SystemExit(1)
