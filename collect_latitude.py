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

def classify_table(table):
    """Classify a pricing table from its heading and current plan identifiers."""
    if not table or not table[0] or table[0][0] != 'PLAN': return None
    heading = table[0][1].strip().upper() if len(table[0]) > 1 else ''
    if heading == 'GPU': return 'Metal GPU'
    if heading == 'VCPU': return 'Virtual machines'
    require(heading == 'CPU', 'Unrecognized Latitude plan table heading: '+heading)
    generations=set()
    for row in table[1:]:
        if not row: continue
        match=re.match(r'^[a-z]+(\d+)\.',row[0],re.I)
        require(match is not None,'Unrecognized CPU plan identifier: '+str(row[0]))
        generations.add(int(match.group(1)))
    require(len(generations)==1,'Mixed CPU plan generations in one source table')
    return 'Metal Gen '+str(next(iter(generations)))

def missing_plan_record(old_plan,last_observed_at,checked_at):
    """Keep historical values separate from a missing current listing."""
    last_known={k:copy.deepcopy(old_plan.get(k)) for k in FIELDS+['hardware','memory','locations','availability','basis','source']}
    return {'id':old_plan['id'],'category':old_plan['category'],'hardware':old_plan.get('hardware',''),'memory':old_plan.get('memory',''),
      **{k:None for k in FIELDS},'source':old_plan.get('source','https://www.latitude.sh/pricing'),'locations':[],
      'cheapestLocations':[],'mostExpensiveLocations':[],'locationHourlyMin':None,'locationHourlyMax':None,
      'availability':'Not listed in the current pricing catalog; retirement not confirmed.','currentStatus':'not_listed_in_current_catalog',
      'checkedAt':checked_at,'lastObservedAt':last_observed_at,'lastKnown':last_known,
      'basis':'Current catalog does not list this plan. Earlier observation preserved in lastKnown; no current price inferred.'}

def validate_against_previous(plan, prior):
    """Retain the existing bounds on a current listed plan versus its last observation."""
    baseline=prior.get('lastKnown') if prior.get('currentStatus')=='not_listed_in_current_catalog' else prior
    ident=plan['id']
    for k in FIELDS:
        a,b=baseline.get(k),plan.get(k)
        require((a is None)==(b is None),'Missing-value pattern changed: '+ident+' '+k)
        if a is not None: require(.5<=b/a<=1.5,'Price move exceeds 50% safety bound: '+ident+' '+k)
    require(plan['hardware']==baseline['hardware'] and plan['memory']==baseline['memory'],'Hardware changed; manual validation needed: '+ident)
    require({l['location'] for l in plan['locations']}=={l['location'] for l in baseline['locations']},'Location set changed; manual validation needed: '+ident)
    for loc in plan['locations']:
        oldloc=next((x for x in baseline['locations'] if x['location']==loc['location']),None)
        require(oldloc is not None,'Unknown location: '+ident)
        for k in FIELDS:
            a,b=oldloc.get(k),loc.get(k)
            require((a is None)==(b is None),'Location price field changed: '+ident+' '+loc['location']+' '+k)
            if a is not None: require(.5<=b/a<=1.5,'Location price move exceeds safety bound: '+ident+' '+loc['location']+' '+k)
    if prior.get('source'): plan['source']=prior['source']

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
        categories={id(t):classify_table(t) for t in base}
        require({'Metal GPU','Virtual machines'} <= set(categories.values()) and any(c.startswith('Metal Gen ') for c in categories.values()), 'Required Latitude plan tables are missing')
        ids=[r[0] for t in base for r in t[1:] if r]
        require(len(ids)==len(set(ids)) and len(ids)>=15,'Duplicate or unexpectedly few plan rows')
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
    for t in base:
        category=classify_table(t)
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
            result.append({'id':ident,'category':category,'hardware':r[1].replace('\n',' '),'memory':r[2].replace('\n',' '),'hourly':h['hr'],'monthly':h.get('mo'),'reservedMonthlyHourly':m['hr'],'reservedMonthlyMonthly':m['mo'],'reservedYearlyHourly':y['hr'],'reservedYearlyMonthly':None,'reservedYearlyAnnual':y['yr'],'source':'https://www.latitude.sh/pricing','locations':locs,'cheapestLocations':[l['location'] for l in priced if l['hourly']==lo],'mostExpensiveLocations':[l['location'] for l in priced if l['hourly']==hi],'locationHourlyMin':lo,'locationHourlyMax':hi,'availability':f"{sum(l['status']=='CURRENTLY IN STOCK' for l in locs)} of {len(locs)} listed locations in stock" if locs else 'Not verified by location','currentStatus':'listed_in_current_catalog','basis':'Direct displayed billing terms. Annual totals retained. Missing values are null.'})
    return result

def main():
    data=json.loads((ROOT/'snapshots.json').read_text());previous=max(data['snapshots'].values(),key=lambda s:s['capturedAt'])
    plans=collect();old={p['id']:p for p in previous['latitude']['plans']};new={p['id']:p for p in plans}
    unknown=set(new)-set(old)
    require(not unknown,'New plan IDs require manual validation before publishing: '+', '.join(sorted(unknown)))
    now=datetime.now(ZoneInfo('Australia/Sydney'));key=now.date().isoformat();checked=now.isoformat(timespec='seconds')
    for ident,p in new.items():
        validate_against_previous(p,old[ident])
    missing=sorted(set(old)-set(new));last_observed=previous.get('latitude',{}).get('capturedAt') or previous.get('capturedAt')
    plans.extend(missing_plan_record(old[i],last_observed,checked) for i in missing)
    plans.sort(key=lambda p:(p.get('category',''),p['id']))
    snap=copy.deepcopy(previous);snap['date']=key;snap['capturedAt']=checked;snap['latitude']['plans']=plans;snap['latitude']['capturedAt']=checked
    snap['latitude']['sourceStatus']={'status':'partial_catalog' if missing else 'complete','checkedAt':checked,'missingPlanIds':missing,'source':'https://www.latitude.sh/pricing'}
    snap['latitude']['reservedNote']='Current displayed billing terms validated. Plans absent from the current pricing catalog are retained as unavailable with their last-known values separated; no retirement or current price is inferred.'
    from collect_demand import collect_partial as collect_ai
    snap['openrouter'],snap['ramp'],demand_errors=collect_ai(previous['openrouter'],previous['ramp'],checked)
    for src_name,err in demand_errors.items():print('WARNING:',src_name,'unavailable; snapshot keeps last validated data marked stale.',err)
    data['snapshots'][key]=snap
    candidate=ROOT/'snapshots.json.tmp';candidate.write_text(json.dumps(data,separators=(',',':'))+'\n',encoding='utf-8');candidate.replace(ROOT/'snapshots.json')
    print('Validated',len(new),'current plans;',len(missing),'known plans not listed; saved',key,'and preserved',len(data['snapshots']),'date keys. OpenRouter and Ramp validated with original source periods.')
if __name__=='__main__': main()
