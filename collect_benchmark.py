"""Optional CC BY GPU Economy feed. Never changes direct source data."""
import copy,json,math,urllib.request
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
URL='https://gpueconomy.com/prices.json'
MAP={'b300':('g4.b300.large',8,288),'rtx-pro-6000':('g4.rtx6kpro.large',8,96),'h100':('g3.h100.small',1,80),'h100-pcie':('g3.h100.small',1,80),'h100-sxm':('g3.h100.small',1,80)}
def parse(d,now):
    if d.get('license')!='CC BY 4.0' or not str(d.get('unit','')).startswith('USD per GPU'):raise ValueError('Feed license/unit changed')
    updated=datetime.fromisoformat(d['data_updated_at']);age=(now-updated).total_seconds()
    if not 0<=age<=48*3600:raise ValueError('Feed stale/future')
    rows=[];seen=set()
    for r in d['prices']:
        spec=MAP.get(r.get('gpu_id'))
        if not spec or r.get('gpu_count')!=spec[1] or r.get('status')!='live':continue
        if not r.get('last_confirmed_at') or not 0<=(now-datetime.fromisoformat(r['last_confirmed_at'])).total_seconds()<=48*3600:continue
        unit=r.get('listed_unit');price=r.get('listed_price_hour')
        if unit not in ['per_node','per_gpu'] or (spec[1]>1 and unit!='per_node'):continue
        if r.get('listed_currency')!='USD' or isinstance(price,bool) or not isinstance(price,(float,int)) or not math.isfinite(price) or price<=0:continue
        source=r.get('source_url','')
        if not source.startswith('https://'):continue
        identity=[r.get(k) for k in ['provider_id','gpu_id','gpu_count','price_type','market','risk','price_scope','region','instance','min_commitment','listed_unit','listed_currency','source_url']]
        key=json.dumps(identity,separators=(',',':'),sort_keys=True)
        if key in seen:raise ValueError('Duplicate quote identity')
        seen.add(key)
        row={k:r.get(k) for k in ['provider','provider_id','gpu','gpu_id','gpu_count','price_type','market','risk','price_scope','region','instance','min_commitment','listed_unit','listed_currency','listed_price_hour','source_url','scraped_at','last_confirmed_at']}
        row.update(quoteKey=key,latitudePlan=spec[0],vramGbPerGpu=spec[2],variantCaveat='Model/count/VRAM candidates only; exact variant, server inclusions and network not fully verified.',method='GPU Economy original listed USD hourly quote v1',methodologyVersion=d.get('methodology_version'))
        rows.append(row)
    if not rows:raise ValueError('No fresh matching quotes')
    return {'source':URL,'license':'CC BY 4.0','attribution':'GPU Economy (https://gpueconomy.com/data). Provider source links retained.','capturedAt':now.isoformat(timespec='seconds'),'sourceUpdatedAt':d['data_updated_at'],'methodologyVersion':d.get('methodology_version'),'rows':rows}
def update(data,fetch,now):
    latest=max(data['snapshots'].values(),key=lambda s:s['capturedAt'])
    try:
        new=parse(fetch(),now)
        latest['gpuEconomy']=new
        latest['gpuEconomyStatus']={'ok':True,'checkedAt':now.isoformat(timespec='seconds'),'message':'Fresh feed loaded. Hardware candidates, not fully comparable servers.'}
    except Exception as e:
        latest['gpuEconomyStatus']={'ok':False,'checkedAt':now.isoformat(timespec='seconds'),'message':'GPU Economy update failed; last good data retained: '+str(e)[:250]}
        print('::warning::'+latest['gpuEconomyStatus']['message'])
    return data
def main():
    p=ROOT/'snapshots.json';data=json.loads(p.read_text());now=datetime.now(timezone.utc)
    def fetch():
        req=urllib.request.Request(URL,headers={'User-Agent':'field-notes-daily/1.0'})
        with urllib.request.urlopen(req,timeout=45)as r:return json.load(r)
    update(data,fetch,now);temp=p.with_suffix('.benchmark.tmp');temp.write_text(json.dumps(data,separators=(',',':'))+'\n');temp.replace(p)
    s=max(data['snapshots'].values(),key=lambda x:x['capturedAt']);print('Optional benchmark',s['gpuEconomyStatus'],len(s.get('gpuEconomy',{}).get('rows',[])))
if __name__=='__main__':main()
