"""Collect native public Latitude terms and stock. Validate fully before any write."""
import copy, json, math, os, re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'collector-output'
OUT.mkdir(exist_ok=True)
FIELDS = ['hourly','monthly','reservedMonthlyHourly','reservedMonthlyMonthly','reservedYearlyHourly','reservedYearlyAnnual']
def prices(text):
    return {unit: float(n.replace(',', '')) for n,unit in re.findall(r'\$([\d,.]+)/(hr|mo|yr)', text)}
def require(ok, message):
    if not ok: raise ValueError(message)
def collect():
    views, dialogs = {}, {}
    with sync_playwright() as p:
        args = {'headless':True}
        if os.getenv('CHROME_PATH'): args.update(executable_path=os.environ['CHROME_PATH'], args=['--no-sandbox'])
        browser = p.chromium.launch(**args)
        page = browser.new_page(viewport={'width':1440,'height':1000})
        response = page.goto('https://www.latitude.sh/pricing', wait_until='domcontentloaded', timeout=60000)
        require(response and response.status==200, 'Pricing page did not return HTTP 200')
        page.locator('table').first.wait_for(timeout=30000)
        for term in ['Hourly','Monthly','Paid yearly']:
            buttons=page.get_by_role('button',name=term,exact=True)
            require(buttons.count()>=3, 'Missing billing selectors: '+term)
            for i in range(buttons.count()):
                buttons.nth(i).click()
                page.wait_for_function("e=>!e.className.includes('hover:text-v2-slate-8')",arg=buttons.nth(i).element_handle())
            page.wait_for_function("term=>[...document.querySelectorAll('button')].filter(e=>e.innerText===term).every(e=>!e.className.includes('hover:text-v2-slate-8'))",arg=term)
            views[term]=page.locator('table').evaluate_all('ts=>ts.map(t=>[...t.rows].map(r=>[...r.cells].map(c=>c.innerText)))')
        base=[t for t in views['Hourly'] if t and t[0] and t[0][0]=='PLAN']
        require(len(base)==4, 'Expected GPU, Gen4, Gen3 and VM tables')
        ids=[r[0] for t in base for r in t[1:] if r]
        require(len(ids)==len(set(ids)) and len(ids)>=20,'Duplicate or missing plan rows')
        for ident in ids:
            if ident.startswith('vm.'): continue
            page.get_by_text(ident,exact=True).first.click()
            dialog=page.locator('[role="dialog"]').filter(has=page.locator('table')).first
            dialog.wait_for(timeout=15000)
            dialogs[ident]=dialog.locator('table').evaluate_all('ts=>ts.flatMap(t=>[...t.rows].map(r=>[...r.cells].map(c=>c.innerText)))')
            page.keyboard.press('Escape')
            dialog.wait_for(state='hidden',timeout=15000)
        page.screenshot(path=str(OUT/'overview.png'),full_page=True)
        browser.close()
    (OUT/'raw.json').write_text(json.dumps({'views':views,'dialogs':dialogs},indent=2),encoding='utf-8')
    indexed={term:{r[0]:r for t in tables if t and t[0] and t[0][0]=='PLAN' for r in t[1:] if r} for term,tables in views.items()}
    require(all(set(v)==set(ids) for v in indexed.values()),'Plan sets disagree between billing terms')
    result=[]
    for category,t in zip(['Metal GPU','Metal Gen 4','Metal Gen 3','Virtual machines'],base):
        for r in t[1:]:
            ident=r[0];h=prices(r[-1]);m=prices(indexed['Monthly'][ident][-1]);y=prices(indexed['Paid yearly'][ident][-1])
            require(all(v.get('hr',0)>0 for v in [h,m,y]),'Missing hourly billing terms: '+ident)
            require(m.get('mo',0)>0 and y.get('yr',0)>0,'Missing commitment totals: '+ident)
            locs=[];stock=None
            for row in dialogs.get(ident,[]):
                if not row: continue
                if row[0].upper() in ['CURRENTLY IN STOCK','OUT OF STOCK']: stock=row[0].upper();continue
                require(len(row)>=4 and stock is not None,'Unrecognized stock table: '+ident)
                a,b,c=map(prices,row[1:4]);loc={'location':row[0],'status':stock,'hourly':a.get('hr'),'monthly':a.get('mo'),'reservedMonthlyHourly':b.get('hr'),'reservedMonthlyMonthly':b.get('mo'),'reservedYearlyHourly':c.get('hr'),'reservedYearlyAnnual':c.get('yr')}
                # Out-of-stock locations can show dashes; never treat them as zero.
                require(stock=='OUT OF STOCK' or all(loc[k] is not None for k in FIELDS),'Incomplete in-stock location: '+ident)
                for k in FIELDS: require(loc[k] is None or math.isfinite(loc[k]) and loc[k]>0,'Invalid location price: '+ident)
                locs.append(loc)
            if not ident.startswith('vm.'):
                require(len(locs)>0,'No locations: '+ident)
                match=next((l for l in locs if l['hourly']==h['hr']),None)
                require(match is not None and match['monthly'] is not None,'Overview missing matching location: '+ident)
                require(match['reservedMonthlyHourly']==m['hr'] and match['reservedMonthlyMonthly']==m['mo'] and match['reservedYearlyHourly']==y['hr'] and match['reservedYearlyAnnual']==y['yr'],'Overview and location billing terms disagree: '+ident)
                h['mo']=match['monthly']
            priced=[l for l in locs if l['hourly'] is not None];lo=min((l['hourly'] for l in priced),default=None);hi=max((l['hourly'] for l in priced),default=None)
            result.append({'id':ident,'category':category,'hardware':r[1].replace('\n',' '),'memory':r[2].replace('\n',' '),'hourly':h['hr'],'monthly':h.get('mo'),'reservedMonthlyHourly':m['hr'],'reservedMonthlyMonthly':m['mo'],'reservedYearlyHourly':y['hr'],'reservedYearlyMonthly':None,'reservedYearlyAnnual':y['yr'],'source':'https://www.latitude.sh/pricing','locations':locs,'cheapestLocations':[l['location'] for l in priced if l['hourly']==lo],'mostExpensiveLocations':[l['location'] for l in priced if l['hourly']==hi],'locationHourlyMin':lo,'locationHourlyMax':hi,'availability':f"{sum(l['status']=='CURRENTLY IN STOCK' for l in locs)} of {len(locs)} listed locations in stock" if locs else 'Not verified by location','basis':'Direct displayed billing terms. Annual totals retained. Missing values are null.'})
    return result

def main():
    data=json.loads((ROOT/'snapshots.json').read_text());previous=max(data['snapshots'].values(),key=lambda s:s['capturedAt'])
    plans=collect();old={p['id']:p for p in previous['latitude']['plans']};new={p['id']:p for p in plans}
    require(set(old)==set(new),'Plan set changed; manual validation needed before publishing')
    for ident,p in new.items():
        for k in FIELDS:
            a,b=old[ident].get(k),p.get(k)
            require((a is None)==(b is None),'Missing-value pattern changed: '+ident+' '+k)
            if a is not None: require(.5<=b/a<=1.5,'Price move exceeds 50% safety bound: '+ident+' '+k)
        require(p['hardware']==old[ident]['hardware'] and p['memory']==old[ident]['memory'],'Hardware changed; manual validation needed: '+ident)
        require({l['location'] for l in p['locations']}=={l['location'] for l in old[ident]['locations']},'Location set changed; manual validation needed: '+ident)
        for loc in p['locations']:
            oldloc=next((x for x in old[ident]['locations'] if x['location']==loc['location']),None)
            require(oldloc is not None,'Unknown location: '+ident)
            for k in FIELDS:
                a,b=oldloc.get(k),loc.get(k)
                require((a is None)==(b is None),'Location price field changed: '+ident+' '+loc['location']+' '+k)
                if a is not None:require(.5<=b/a<=1.5,'Location price move exceeds safety bound: '+ident+' '+loc['location']+' '+k)
        if old[ident].get('source'):p['source']=old[ident]['source']
    now=datetime.now(ZoneInfo('Australia/Sydney'));key=now.date().isoformat();snap=copy.deepcopy(previous)
    snap['date']=key;snap['capturedAt']=now.isoformat(timespec='seconds');snap['latitude']['plans']=plans
    snap['latitude']['capturedAt']=snap['capturedAt'];snap['latitude']['reservedNote']='All billing terms read directly. Annual totals are annual. Missing values remain blank. Daily Latitude collection validated before publication.'
    from collect_demand import collect_partial as collect_ai
    snap['openrouter'],snap['ramp'],demand_errors=collect_ai(previous['openrouter'],previous['ramp'],snap['capturedAt'])
    for src_name,err in demand_errors.items():
        print('WARNING:',src_name,'unavailable; snapshot keeps last validated data marked stale.',err)
    data['snapshots'][key]=snap
    candidate=ROOT/'snapshots.json.tmp';candidate.write_text(json.dumps(data,separators=(',',':'))+'\n',encoding='utf-8');candidate.replace(ROOT/'snapshots.json')
    print('Validated',len(plans),'plans; saved',key,'and preserved',len(data['snapshots']),'date keys. OpenRouter and Ramp validated with original source periods.')
if __name__=='__main__': main()
