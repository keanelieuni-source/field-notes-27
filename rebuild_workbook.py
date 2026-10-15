"""Rebuild history.xlsx from every entry in snapshots.json. pip install openpyxl"""
import base64
import json
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

ROOT = Path(__file__).resolve().parent
data = json.loads((ROOT / "snapshots.json").read_text(encoding="utf-8"))
wb = Workbook()
wb.remove(wb.active)
rows = {name: [] for name in ["Latitude plans", "Latitude locations", "OpenRouter models", "OpenRouter shares", "Ramp adoption", "Ramp financing", "Ramp token spend"]}
for key, s in sorted(data["snapshots"].items()):
    for p in s["latitude"]["plans"]:
        row = {"snapshotDate": key, **{k: v for k, v in p.items() if not isinstance(v, (list, dict))}}
        for field in ["cheapestLocations", "mostExpensiveLocations"]:
            row[field] = ", ".join(p.get(field, []))
        rows["Latitude plans"].append(row)
        for loc in p.get("locations", []):
            rows["Latitude locations"].append({"snapshotDate": key, "plan": p["id"], **loc})
    o, r = s["openrouter"], s["ramp"]
    rows["OpenRouter models"] += [{"snapshotDate": key, "usageThrough": o["usageThrough"], **m} for m in o["weekTopModels"]]
    rows["OpenRouter shares"] += [{"snapshotDate": key, "weekBeginning": o["marketShareWeekOf"], **m} for m in o["marketShare"]]
    rows["Ramp adoption"].append({"snapshotDate": key, "period": r["period"], **r["adoption"], **{k: r.get(k) for k in ["spendPerEmployee", "top1SpendPerEmployee", "top10SpendPerEmployee"]}})
    rows["Ramp financing"] += [{"snapshotDate": key, "period": r["period"], **m} for m in r["financingStatus"]]
    rows["Ramp token spend"] += [{"snapshotDate": key, "periodEnd": r["tokenSpend"]["periodEnd"], "unit": r["tokenSpend"]["unit"], **m} for m in r["tokenSpend"]["makers"]]
rows["GPU Economy quotes"] = []
rows["Quote observations"] = []
previous = None
for key, snap in sorted(data["snapshots"].items()):
    bench = snap.get("gpuEconomy", {})
    current_ok = snap.get("gpuEconomyStatus", {}).get("ok", False)
    oldbench = previous.get("gpuEconomy", {}) if previous else {}
    oldrows = {r["quoteKey"]: r for r in oldbench.get("rows", [])}
    oldplans = {p["id"]: p for p in previous["latitude"]["plans"]} if previous else {}
    plans = {p["id"]: p for p in snap["latitude"]["plans"]}
    from datetime import date
    consecutive = bool(previous and (date.fromisoformat(key) - date.fromisoformat(previous["date"])).days == 1)
    fresh_pair = current_ok and previous and previous.get("gpuEconomyStatus", {}).get("ok", False)
    for r in bench.get("rows", []):
        rows["GPU Economy quotes"].append({"snapshotDate": key, "feedOk": current_ok, "benchmarkCapturedAt": bench.get("capturedAt"), **r})
        a = oldrows.get(r["quoteKey"])
        same = bool(consecutive and fresh_pair and a and a.get("method") == r.get("method") and a.get("methodologyVersion") == r.get("methodologyVersion"))
        p = plans.get(r["latitudePlan"]); op = oldplans.get(r["latitudePlan"])
        eligible = r["listed_unit"] == "per_node" and r["price_type"] == "on_demand" and r["market"] == "on_demand" and r["price_scope"] == "instance"
        rows["Quote observations"].append({"snapshotDate": key, "plan": r["latitudePlan"], "provider": r["provider"], "quoteKey": r["quoteKey"], "term": r["price_type"], "originalUnit": r["listed_unit"], "latitudeHourly": p.get("hourly") if p else None, "originalQuoteHourly": r["listed_price_hour"], "previousObservedDate": previous["date"] if same else None, "quotePreviousObservedUsdHourly": a["listed_price_hour"] if same else None, "quoteCurrentObservedUsdHourly": r["listed_price_hour"], "latitudePreviousObservedUsdHourly": op["hourly"] if same and eligible and p and op and p["hardware"]==op["hardware"] and p["memory"]==op["memory"] else None, "latitudeCurrentObservedUsdHourly": p["hourly"] if p else None, "comparison": "Independent same-method movements only, not a like-for-like price spread. Exact variant/server inclusions unverified.", "source": r["source_url"]})
    previous = snap
# Price eras are per Latitude plan and billing term, never inferred before tracking.
terms = {"hourly": ("hourly", "monthly"), "monthly": ("reservedMonthlyHourly", "reservedMonthlyMonthly"), "yearly": ("reservedYearlyHourly", "reservedYearlyAnnual")}
rows["Latitude price eras"] = []
rows["Market since Latitude"] = []
eras = {}
for day, snap in sorted(data["snapshots"].items()):
    for p in snap["latitude"]["plans"]:
        if p.get("category") != "Metal GPU": continue
        for term, fields in terms.items():
            k = (p["id"], term)
            signature = (p.get("hardware"), p.get("memory"), *(p.get(f) for f in fields))
            old = eras.get(k)
            continuous = old and (date.fromisoformat(day)-date.fromisoformat(old["lastDay"])).days == 1 and old["signature"][:2] == signature[:2]
            changed = bool(continuous and old["signature"] != signature)
            if not continuous or changed:
                eras[k] = {"signature": signature, "baselineDate": day, "changeObserved": changed, "previousHourly": old["signature"][2] if changed else None, "lastDay": day, "baselineSnap": snap}
            era = eras[k]; era["lastDay"] = day
            days = (date.fromisoformat(day)-date.fromisoformat(era["baselineDate"])).days
            rows["Latitude price eras"].append({"snapshotDate": day, "plan": p["id"], "billingTerm": term, "hourly": p.get(fields[0]), "originalTotal": p.get(fields[1]), "totalPeriod": "year" if term == "yearly" else "month", "baselineDate": era["baselineDate"], "lastPriceChangeDate": era["baselineDate"] if era["changeObserved"] else None, "previousHourly": era["previousHourly"], "observedChangeUsdHourly": p.get(fields[0])-era["previousHourly"] if era["changeObserved"] and p.get(fields[0]) is not None and era["previousHourly"] is not None else None, "observedUnchangedDays": days, "status": "Latitude moved from " + str(era["previousHourly"]) + " to " + str(p.get(fields[0])) + " USD/hr" if era["changeObserved"] else "Tracking baseline only; earlier change date unknown"})
            if term != "hourly": continue  # Market term/commitment equality is not established for reserved offers.
            for q in snap.get("gpuEconomy", {}).get("rows", []):
                if q["latitudePlan"] != p["id"]: continue
                eligible = q["listed_unit"] == "per_node" and q["price_type"] == "on_demand" and q["market"] == "on_demand" and q["price_scope"] == "instance"
                pair = []
                valid = eligible and days > 0
                for d, ss in sorted(data["snapshots"].items()):
                    if not era["baselineDate"] <= d <= day: continue
                    qq = next((r for r in ss.get("gpuEconomy", {}).get("rows", []) if r["quoteKey"] == q["quoteKey"] and r.get("method") == q.get("method") and r.get("methodologyVersion") == q.get("methodologyVersion")), None)
                    if not ss.get("gpuEconomyStatus", {}).get("ok") or not qq: valid = False
                    pair.append(qq)
                if len(pair) != days+1: valid = False
                base = pair[0] if valid else None
                rows["Market since Latitude"].append({"snapshotDate": day, "plan": p["id"], "latitudeTerm": term, "latitudeBaselineDate": era["baselineDate"], "baselineType": "Observed Latitude price change" if era["changeObserved"] else "Tracking start; last change unknown", "provider": q["provider"], "quoteKey": q["quoteKey"], "originalUnit": q["listed_unit"], "originalQuoteHourly": q["listed_price_hour"], "quoteAtLatitudeBaseline": base["listed_price_hour"] if base else None, "quoteMoveSinceLatitudeUsdHourly": q["listed_price_hour"]-base["listed_price_hour"] if base else None, "note": "Independent market movement, not a like-for-like server-price spread. Blank if ineligible or incomplete history.", "source": q["source_url"]})
rows["Competitor price eras"] = []
quote_eras = {}
for day, snap in sorted(data["snapshots"].items()):
    if not snap.get("gpuEconomyStatus", {}).get("ok"): continue
    for q in snap.get("gpuEconomy", {}).get("rows", []):
        k = (q["quoteKey"], q.get("method"), q.get("methodologyVersion"))
        old = quote_eras.get(k)
        continuous = old and (date.fromisoformat(day)-date.fromisoformat(old["lastDay"])).days == 1
        changed = bool(continuous and old["price"] != q["listed_price_hour"])
        if not continuous or changed:
            quote_eras[k] = {"baselineDate": day, "changeObserved": changed, "before": old["price"] if changed else None}
        e = quote_eras[k]; e.update(lastDay=day, price=q["listed_price_hour"])
        rows["Competitor price eras"].append({"snapshotDate": day, "plan": q["latitudePlan"], "provider": q["provider"], "term": q["price_type"], "region": q["region"], "originalUnit": q["listed_unit"], "currentUsdHourly": q["listed_price_hour"], "lastObservedChangeDate": e["baselineDate"] if e["changeObserved"] else None, "previousUsdHourly": e["before"], "changeUsdHourly": q["listed_price_hour"]-e["before"] if e["before"] is not None else None, "observedUnchangedDays": (date.fromisoformat(day)-date.fromisoformat(e["baselineDate"])).days, "trackingBaseline": e["baselineDate"], "status": "Quote moved from " + str(e["before"]) + " to " + str(q["listed_price_hour"]) + " USD/hr" if e["changeObserved"] else "Earlier price change unknown", "quoteKey": q["quoteKey"], "source": q["source_url"]})
rows["GPU stock and prices"] = []
for day, snap in sorted(data["snapshots"].items()):
    for p in snap["latitude"]["plans"]:
        if p["category"] != "Metal GPU": continue
        for l in p["locations"]:
            rows["GPU stock and prices"].append({"Date": day, "Plan": p["id"], "Location": l["location"], "Stock": "In stock" if l["status"] == "CURRENTLY IN STOCK" else "Out of stock", "Hourly USD/hr": l["hourly"], "Hourly USD/mo": l["monthly"], "Monthly USD/hr": l["reservedMonthlyHourly"], "Monthly USD/mo": l["reservedMonthlyMonthly"], "Yearly USD/hr": l["reservedYearlyHourly"], "Yearly USD/year": l["reservedYearlyAnnual"], "Source": p["source"]})
rows["Read me"] = [{"note": x} for x in ["Latitude prices are per whole server; GPU Economy retains its original quoted unit. Annual totals remain annual. Missing values are blank, never zero.", "Source dates can differ from snapshot dates. Compare at least two dates before claiming a change.", "Latitude includes out-of-stock offers. VM location availability was not verified.", "Ramp token-spend volume is indexed spend, not raw tokens or USD.", "OpenRouter rankings: CC BY 4.0. https://openrouter.ai/rankings", "Price eras: unchanged durations start at the first consecutive observation, not an assumed earlier change. Latitude and competitor eras are separate. Market moves reset at each observed Latitude hourly price change. Missing or failed daily captures break comparability.", "GPU Economy: CC BY 4.0. https://gpueconomy.com/data . Original units/totals and source links retained; no per-GPU normalization performed. Comparisons between observations require consecutive dates, fresh successful feeds and unchanged quote identity/method. Exact GPU variant and server inclusions remain unverified; no like-for-like spread."]]
# Readable headers, units, stock colors and filters are rebuilt every day.
from openpyxl.styles import Alignment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.utils import get_column_letter
order = ["Read me", "GPU stock and prices", "Latitude price eras", "Competitor price eras", "Market since Latitude"] + [n for n in rows if n not in ["Read me", "GPU stock and prices", "Latitude price eras", "Competitor price eras", "Market since Latitude"]]
labels = {"snapshotDate":"Snapshot date", "billingTerm":"Latitude term", "originalUnit":"Original quote unit", "hourly":"Hourly USD/hr", "monthly":"Hourly USD/mo", "reservedMonthlyHourly":"Monthly USD/hr", "reservedMonthlyMonthly":"Monthly USD/mo", "reservedYearlyHourly":"Yearly USD/hr", "reservedYearlyAnnual":"Yearly USD/year", "observedUnchangedDays":"Observed unchanged days", "lastPriceChangeDate":"Last observed change date", "lastObservedChangeDate":"Last observed change date", "quoteMoveSinceLatitudeUsdHourly":"Market move USD/hr", "originalQuoteHourly":"Quote USD/hr", "currentUsdHourly":"Current USD/hr", "previousUsdHourly":"Previous USD/hr", "changeUsdHourly":"Change USD/hr", "quotePreviousObservedUsdHourly":"Quote from USD/hr", "quoteCurrentObservedUsdHourly":"Quote to USD/hr", "latitudePreviousObservedUsdHourly":"Latitude from USD/hr", "latitudeCurrentObservedUsdHourly":"Latitude to USD/hr"}
for idx,name in enumerate(order):
    records=rows[name];ws=wb.create_sheet(name)
    if not records: continue
    headers = list(dict.fromkeys(k for row in records for k in row))
    ws.append([labels.get(k, __import__('re').sub(r'(?<!^)(?=[A-Z])',' ',k).replace('_',' ').capitalize()) for k in headers])
    for row in records:
        ws.append([json.dumps(row.get(k)) if isinstance(row.get(k),(list,dict)) else row.get(k) for k in headers])
    ws.freeze_panes = "E2" if name=="GPU stock and prices" else "C2"
    ws.auto_filter.ref=ws.dimensions;ws.sheet_view.showGridLines=False
    ws.sheet_properties.pageSetUpPr.fitToPage=True
    ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A3;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
    ws.print_title_rows='1:1';ws.print_options.horizontalCentered=True
    ws.sheet_properties.tabColor='73A89A' if idx<5 else '585254'
    ws.row_dimensions[1].height=42
    for c in ws[1]:
        c.font=Font(name='Calibri',size=11,bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='344A44');c.alignment=Alignment(wrap_text=True,vertical='center')
    for row in ws.iter_rows(min_row=2):
        ws.row_dimensions[row[0].row].height=36 if name!='Read me' else 60
        for c in row:
            c.font=Font(name='Calibri',size=11,color='251F21');c.fill=PatternFill('solid',fgColor='F3F7F5' if c.row%2==0 else 'FFFFFF');c.alignment=Alignment(vertical='center',wrap_text=True)
            if isinstance(c.value,(int,float)) and not isinstance(c.value,bool):c.number_format='#,##0.00;[Red]-#,##0.00' if 'usd' in str(ws.cell(1,c.column).value).lower() or any(x in headers[c.column-1].lower() for x in ['hourly','monthly','annual']) else '#,##0.####'
            if isinstance(c.value,str) and c.value.startswith('https://'):c.hyperlink=c.value;c.value='Source';c.font=Font(name='Calibri',size=10,color='276F5F',underline='single')
            if c.value in ('In stock','CURRENTLY IN STOCK'):c.font=Font(name='Calibri',size=11,color='276F5F',bold=True)
            if c.value in ('Out of stock','OUT OF STOCK'):c.font=Font(name='Calibri',size=11,color='A33A35',bold=True)
    for j,k in enumerate(headers,1):
        width=20 if any(x in k.lower() for x in ['hourly','usd','monthly','annual']) else 24
        if k in ['note','comparison','status','basis']:width=52
        if k in ['source','source_url','quoteKey']:width=36
        if name=='Read me':width=115
        ws.column_dimensions[get_column_letter(j)].width=width
wb.save(ROOT / "history.xlsx")
(ROOT / "workbook.b64").write_text(base64.b64encode((ROOT / "history.xlsx").read_bytes()).decode()+"\n",encoding="ascii")
print("Rebuilt history.xlsx from", len(data["snapshots"]), "snapshot(s);",len(wb.sheetnames),"formatted sheets")
