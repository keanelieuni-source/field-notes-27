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

def read_ramp(page,anchor,now):
    OUT.mkdir(exist_ok=True)
    r=page.goto(RAMP_URL,wait_until='domcontentloaded',timeout=60000);require(r and r.status==200,'Ramp HTTP failure')
    page.screenshot(path=str(OUT/'ramp-page.png'),full_page=True)
    page.get_by_text('Total token spend by businesses, indexed',exact=False).wait_for(timeout=30000)
    scripts=page.locator('script').all_text_contents()
    script=next((x for x in scripts if 'self.__next_f.push(' in x and 'adoptionOverall' in x),None)
    require(script is not None,'Ramp server data payload missing')
    decoder=json.JSONDecoder();stream='';pos=0
    while True:
        pos=script.find('self.__next_f.push(',pos)
        if pos<0:break
        start=script.find('[',pos);arr,_=decoder.raw_decode(script[start:])
        if arr[0]==1 and isinstance(arr[1],str):stream+=arr[1]
        pos=start+1
    marker='"adoptionOverall":';i=stream.find(marker);require(i>=0,'Ramp adoption dataset missing')
    raw,_=decoder.raw_decode(stream[stream.rfind('{',0,i):])
    raw['tokenVersion']=page.evaluate("()=>performance.getEntriesByType('resource').map(x=>x.name).find(x=>x.includes('/chart-data/tokenVolumes?version='))?.split('version=')[1]")
    require(all(raw.get(k) for k in ['adoptionOverall','adoptionVendor','spendPerEmployee','spendPerEmployeeCurated']),'Ramp numeric datasets unavailable')
    token_url=f'https://ramp.com/data/ai-index/chart-data/tokenVolumes?version={raw["tokenVersion"]}' if raw.get('tokenVersion') else None
    token=[];token_error=None
    if token_url:
        try:
            resp=page.request.get(token_url,timeout=60000);require(resp.ok,'Ramp token chart data HTTP failure')
            token=resp.json();require(isinstance(token,list) and len(token)>100,'Ramp token chart dataset malformed')
            require(all(x.get('period_grain')=='weekly' and x.get('metric_key') in ['token_spend','token_volume'] and x.get('dimension_type')=='model' and x.get('model_maker') and numeric(x.get('metric_value')) for x in token),'Ramp token rows malformed')
        except Exception as e:token_error=str(e)
    else:token_error='Ramp token data request was not observed in page resources.'
    (OUT/'ramp-raw.json').write_text(json.dumps({'page':raw,'tokenRows':token,'tokenError':token_error},indent=2))
    a=max(raw['adoptionOverall'],key=lambda x:x['date_month']);period=a['date_month'];sp=next((x for x in raw['spendPerEmployee'] if x['date_month']==period),None)
    v={x['vendor']:x for x in raw['adoptionVendor'] if x['date_month']==period};fin=[x for x in raw['spendPerEmployeeCurated'] if x['date_month']==period and x['dimension_type']=='company_financing_status']
    require(sp and 'Anthropic'in v and 'OpenAI'in v and len(fin)>=3,'Ramp periods incomplete')
    # No current published index levels are present in the JSON route. Keep the last observed publisher index exactly as-is and flag just this subfeed stale; monthly page data remains independently refreshable.
    token_spend=copy.deepcopy(anchor['tokenSpend'])
    token_spend['stale']=True
    token_spend['checkedAt']=now
    token_spend['sourceCapturedAt']=anchor.get('capturedAt')
    token_spend['staleSince']=anchor.get('sourceCapturedAt') or anchor.get('capturedAt')
    token_spend['staleReason']=('Ramp current chart lacks verifiable published index levels; raw JSON USD totals cannot replace them.' if not token_error else 'Ramp publisher index markup missing; raw token dataset also unavailable: '+token_error[:170])
    result={'source':'https://ramp.com/data/ai-index','tokenSource':'https://ramp.com/data/ai-index','tokenDataSource':token_url,'period':period[:7],'periodLabel':datetime.strptime(period,'%Y-%m-%d').strftime('%B %Y'),'adoption':{'overall':a['adoption_rate_pct'],'overallChange':a['mom_change_pp'],'anthropic':v['Anthropic']['adoption_rate_pct'],'anthropicChange':v['Anthropic']['mom_change_pp'],'openai':v['OpenAI']['adoption_rate_pct'],'openaiChange':v['OpenAI']['mom_change_pp']},'spendPerEmployee':sp['median_pepm'],'top1SpendPerEmployee':sp['top_1_percent_median_pepm'],'top10SpendPerEmployee':sp['top_10_percent_median_pepm'],'financingStatus':[{'status':x['dimension_label'],'medianSpendPerEmployee':x['median_pepm']} for x in fin],'tokenSpend':token_spend}
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
    if r['tokenSpend'].get('stale'):
        require(r['tokenSpend']['periodEnd']==old_r['tokenSpend']['periodEnd'] and r['tokenSpend']['unit']==old_r['tokenSpend']['unit'] and r['tokenSpend']['makers']==old_r['tokenSpend']['makers'],'Stale Ramp index must preserve last validated values exactly')
    else:
        require(old_r['tokenSpend']['periodEnd']<=r['tokenSpend']['periodEnd']<=date.today().isoformat(),'Ramp token period regressed/future')
    require(len(r['tokenSpend']['makers'])>=8 and all(numeric(x['index']) for x in r['tokenSpend']['makers']),'Ramp maker index invalid')
    require({'Anthropic','OpenAI'}<={x['maker'] for x in r['tokenSpend']['makers']},'Ramp major makers missing')
    require(len({x['maker'] for x in r['tokenSpend']['makers']})==len(r['tokenSpend']['makers']),'Duplicate Ramp makers')
    oldmakers={x['maker']:x['index'] for x in old_r['tokenSpend']['makers']}
    for x in r['tokenSpend']['makers']:
        if x['maker'] in ['Anthropic','OpenAI'] and x['maker'] in oldmakers:require(.1<=x['index']/oldmakers[x['maker']]<=10,'Major maker index move requires review')
    oldfin={x['status']:x['medianSpendPerEmployee'] for x in old_r['financingStatus']}
    for x in r['financingStatus']:require(.25<=x['medianSpendPerEmployee']/oldfin[x['status']]<=4,'Financing spend move requires review')

def collect(old_o,old_r,now):
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        args={'headless':True}
        if os.getenv('CHROME_PATH'):args.update(executable_path=os.environ['CHROME_PATH'],args=['--no-sandbox'])
        b=p.chromium.launch(**args);page=b.new_page(viewport={'width':1440,'height':1000})
        try:o=read_openrouter(page);r=read_ramp(page,old_r,now)
        finally:b.close()
    validate(o,r,old_o,old_r)
    for x in [o,r]:x['capturedAt']=now;x['checkedAt']=now
    return o,r

def mark_stale(x,now,reason):
    """Reuse the last validated payload, clearly marked stale. capturedAt stays the data's own date."""
    x=copy.deepcopy(x)
    x['checkedAt']=now
    x['stale']=True
    x['staleSince']=x.get('capturedAt')
    x['staleReason']=reason[:300]
    return x

def collect_partial(old_o,old_r,now):
    """Collect OpenRouter and Ramp independently. A source that fails collection or
    validation falls back to the last validated payload marked stale, so one
    unavailable source never blocks the day's snapshot."""
    OUT.mkdir(exist_ok=True)
    o_new=r_new=None;err_o=err_r=None
    with sync_playwright() as p:
        args={'headless':True}
        if os.getenv('CHROME_PATH'):args.update(executable_path=os.environ['CHROME_PATH'],args=['--no-sandbox'])
        b=p.chromium.launch(**args);page=b.new_page(viewport={'width':1440,'height':1000})
        try:
            try:o_new=read_openrouter(page)
            except Exception as e:err_o=e
            try:r_new=read_ramp(page,old_r,now)
            except Exception as e:err_r=e
        finally:b.close()
    o=r=None;errors={}
    if o_new is not None:
        try:validate(o_new,old_r,old_o,old_r);o=o_new
        except Exception as e:errors['openrouter']='validation failed: '+str(e)
    elif err_o is not None:errors['openrouter']='collection failed: '+str(err_o)
    if r_new is not None:
        try:validate(old_o,r_new,old_o,old_r);r=r_new
        except Exception as e:errors['ramp']='validation failed: '+str(e)
    elif err_r is not None:errors['ramp']='collection failed: '+str(err_r)
    if o is not None:o['capturedAt']=now;o['checkedAt']=now
    else:o=mark_stale(old_o,now,errors.get('openrouter','unavailable'))
    if r is not None:
        r['capturedAt']=now;r['checkedAt']=now
        if r['tokenSpend'].get('stale'):errors['ramp_token_index']='collection unavailable: '+r['tokenSpend'].get('staleReason','publisher index unavailable')
    else:r=mark_stale(old_r,now,errors.get('ramp','unavailable'))
    return o,r,errors
