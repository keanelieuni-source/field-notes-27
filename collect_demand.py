"""Read and validate public OpenRouter tables and Ramp chart datasets."""
import copy,json,math,os,re
from datetime import datetime,date
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'collector-output'
RAMP_URL='https://ramp.com/data/ai-index?metric=token-spend&detail=maker&mode=volume'
def require(ok,msg):
    if not ok:raise ValueError(msg)
def numeric(x,low=0,high=None):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>=low and (high is None or x<=high)
def iso(s):return datetime.strptime(s,'%b %d, %Y').date().isoformat()
def read_openrouter(page):
    r=page.goto('https://openrouter.ai/rankings',wait_until='domcontentloaded',timeout=60000)
    require(r and r.status==200,'OpenRouter HTTP failure');page.locator('table').first.wait_for(timeout=30000)
    raw=page.evaluate("()=>({text:document.body.innerText,tables:[...document.querySelectorAll('table')].map(t=>({caption:t.caption?.innerText,rows:[...t.rows].map(r=>[...r.cells].map(c=>c.innerText))}))})")
    (OUT/'openrouter-raw.json').write_text(json.dumps(raw,indent=2))
    tables={t['caption']:t['rows'] for t in raw['tables']}
    models=tables.get('Model rankings by tokens processed');shares=tables.get('Model authors ranked by their share of text requests on OpenRouter in the most recent complete week')
    require(models and shares,'OpenRouter required tables missing')
    usage=re.search(r'Usage data through ([A-Z][a-z]+ \d{1,2}, \d{4})',raw['text']);week=re.search(r'week beginning ([A-Z][a-z]+ \d{1,2}, \d{4})',raw['text'])
    require(usage and week,'OpenRouter source dates missing')
    result={'source':'https://openrouter.ai/rankings','license':'CC BY 4.0','usageThrough':iso(usage[1]),'marketShareWeekOf':iso(week[1]),'weekTopModels':[],'marketShare':[]}
    for row in models[1:11]:
        require(len(row)==5,'Malformed model row');m=re.fullmatch(r'([\d,.]+)([TBMK])(?: tokens)?',row[3]);require(m,'Unknown token unit')
        result['weekTopModels'].append({'rank':int(row[0]),'model':row[1],'author':row[2],'tokensT':float(m[1].replace(',',''))*{'T':1,'B':.001,'M':.000001,'K':.000000001}[m[2]],'change':row[4]})
    for row in shares[1:]:
        require(len(row)>=4 and row[2].endswith('%'),'Malformed share row')
        result['marketShare'].append({'author':row[1],'share':float(row[2][:-1]),'change':row[3]})
    page.screenshot(path=str(OUT/'openrouter.png'),full_page=True)
    return result

def read_ramp(page):
    r=page.goto(RAMP_URL,wait_until='domcontentloaded',timeout=60000);require(r and r.status==200,'Ramp HTTP failure')
    page.locator('.token-plot svg').wait_for(timeout=40000)
    raw=page.evaluate("""()=>{const el=document.querySelector('.token-plot svg');const key=Object.keys(el).find(k=>k.startsWith('__reactFiber'));let f=el[key],out={};for(let i=0;f&&i<30;i++,f=f.return){const p=f.memoizedProps;if(p?.chart)out.chart=p.chart;if(p?.tokenVolumes){for(const k of ['adoptionOverall','adoptionVendor','spendPerEmployee','spendPerEmployeeCurated'])out[k]=p[k]}}return out}""")
    (OUT/'ramp-raw.json').write_text(json.dumps(raw,indent=2))
    require(all(raw.get(k) for k in ['chart','adoptionOverall','adoptionVendor','spendPerEmployee','spendPerEmployeeCurated']),'Ramp numeric datasets unavailable')
    a=max(raw['adoptionOverall'],key=lambda x:x['date_month']);period=a['date_month'];sp=next((x for x in raw['spendPerEmployee'] if x['date_month']==period),None)
    v={x['vendor']:x for x in raw['adoptionVendor'] if x['date_month']==period};fin=[x for x in raw['spendPerEmployeeCurated'] if x['date_month']==period and x['dimension_type']=='company_financing_status']
    require(sp and 'Anthropic'in v and 'OpenAI'in v and len(fin)>=3,'Ramp periods incomplete')
    chart=raw['chart'];points=sorted(chart['points'],key=lambda x:x['date']);latest=points[-1];prior=points[-2]
    makers=[{'maker':x['label'],'index':latest['values'][x['key']],'previousIndex':prior['values'].get(x['key'])} for x in chart['series'] if x['key'] in latest['values']]
    result={'source':'https://ramp.com/data/ai-index','tokenSource':RAMP_URL,'period':period[:7],'periodLabel':datetime.strptime(period,'%Y-%m-%d').strftime('%B %Y'),'adoption':{'overall':a['adoption_rate_pct'],'overallChange':a['mom_change_pp'],'anthropic':v['Anthropic']['adoption_rate_pct'],'anthropicChange':v['Anthropic']['mom_change_pp'],'openai':v['OpenAI']['adoption_rate_pct'],'openaiChange':v['OpenAI']['mom_change_pp']},'spendPerEmployee':sp['median_pepm'],'top1SpendPerEmployee':sp['top_1_percent_median_pepm'],'top10SpendPerEmployee':sp['top_10_percent_median_pepm'],'financingStatus':[{'status':x['dimension_label'],'medianSpendPerEmployee':x['median_pepm']} for x in fin],'tokenSpend':{'periodEnd':latest['date'],'unit':'Index, not USD or tokens','makers':makers}}
    page.screenshot(path=str(OUT/'ramp.png'),full_page=True)
    return result

def validate(o,r,old_o,old_r):
    require(len(o['weekTopModels'])==10 and [m['rank'] for m in o['weekTopModels']]==list(range(1,11)),'OpenRouter top 10 ranks invalid')
    require(len({m['model'] for m in o['weekTopModels']})==10,'Duplicate models')
    require(all(m['model'] and m['author'] and numeric(m['tokensT'],.000001) and re.fullmatch(r'(?:[+\-<>]?\d+(?:\.\d+)?%|new|0%)',m['change'],re.I) for m in o['weekTopModels']),'Invalid model values')
    require(6<=len(o['marketShare'])<=40 and len({s['author'] for s in o['marketShare']})==len(o['marketShare']),'Invalid share set')
    require(all(numeric(s['share'],0,100) for s in o['marketShare']) and 98<=sum(s['share'] for s in o['marketShare'])<=102,'Share totals invalid')
    require(old_o['usageThrough']<=o['usageThrough']<=date.today().isoformat() and old_o['marketShareWeekOf']<=o['marketShareWeekOf']<=o['usageThrough'],'OpenRouter source period regressed or future')
    old_total=sum(m['tokensT'] for m in old_o['weekTopModels']);new_total=sum(m['tokensT'] for m in o['weekTopModels']);require(.25<=new_total/old_total<=4,'Token total move requires review')
    require(old_r['period']<=r['period']<=date.today().isoformat()[:7],'Ramp monthly period regressed/future')
    for k,v in r['adoption'].items():require(numeric(v,0,100) if not k.endswith('Change') else numeric(abs(v),0,100),'Invalid adoption metric')
    for k in ['overall','anthropic','openai']:require(abs(r['adoption'][k]-old_r['adoption'][k])<=15,'Ramp adoption move requires review')
    require(0<r['spendPerEmployee']<=r['top10SpendPerEmployee']<=r['top1SpendPerEmployee'],'Spend ordering invalid')
    for k in ['spendPerEmployee','top1SpendPerEmployee','top10SpendPerEmployee']:require(numeric(r[k],.000001) and .25<=r[k]/old_r[k]<=4,'Spend move requires review')
    require({x['status'] for x in r['financingStatus']}=={x['status'] for x in old_r['financingStatus']} and all(numeric(x['medianSpendPerEmployee'],0) for x in r['financingStatus']),'Financing data invalid')
    require(old_r['tokenSpend']['periodEnd']<=r['tokenSpend']['periodEnd']<=date.today().isoformat(),'Ramp token period regressed/future')
    require(len(r['tokenSpend']['makers'])>=8 and all(numeric(x['index']) for x in r['tokenSpend']['makers']),'Ramp maker index invalid')
    require({'Anthropic','OpenAI'}<={x['maker'] for x in r['tokenSpend']['makers']},'Ramp major makers missing')

def collect(old_o,old_r,now):
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        args={'headless':True}
        if os.getenv('CHROME_PATH'):args.update(executable_path=os.environ['CHROME_PATH'],args=['--no-sandbox'])
        b=p.chromium.launch(**args);page=b.new_page(viewport={'width':1440,'height':1000})
        try:o=read_openrouter(page);r=read_ramp(page)
        finally:b.close()
    validate(o,r,old_o,old_r)
    for x in [o,r]:x['capturedAt']=now;x['checkedAt']=now
    return o,r
