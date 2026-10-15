"""Offline build. Reads local CSV and stored quotes only; never fetches SemiAnalysis."""
import csv,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def build():
    out=json.loads((ROOT/'comparison_history.json').read_text());rows=[];seen=set()
    import io
    with ((ROOT/'gpu_index.csv').open(newline='') if (ROOT/'gpu_index.csv').exists() else io.StringIO('date,a100_usd_per_gpu_hour,h100_usd_per_gpu_hour,b200_usd_per_gpu_hour\n')) as f:
        for r in csv.DictReader(f):
            if r['date'] in seen:raise ValueError('Duplicate SemiAnalysis date')
            seen.add(r['date']);p={'date':r['date']}
            for gpu in ['a100','h100','b200']:
                text=r[gpu+'_usd_per_gpu_hour'];v=float(text) if text else None
                if v is not None and (not math.isfinite(v) or v<0):raise ValueError('Invalid index price')
                p[gpu]=v
            rows.append(p)
    out['semiAnalysis']=sorted(rows,key=lambda p:p['date']);out['latitude']=[]
    snapshots=json.loads((ROOT/'snapshots.json').read_text())['snapshots']
    from collections import defaultdict
    sellers={q['key']:q for q in out['sellerObservations']};groups=defaultdict(list)
    for day,s in sorted(snapshots.items()):
        for p in s['latitude']['plans']:
            if p['category']=='Metal GPU':
                gpu='h100' if 'h100' in p['id'] else 'b300' if 'b300' in p['id'] else 'rtx'
                n=int(p['hardware'].split(' ')[0])
                for term,field in [('hourly','hourly'),('monthly','reservedMonthlyHourly'),('yearly','reservedYearlyHourly')]:
                    key=p['id']+'|'+term
                    groups[key].append({'date':day,'value':p[field]/n if p[field] is not None else None,'originalNodePrice':p[field],'gpuCount':n,'gpu':gpu,'id':p['id'],'hardware':p['hardware'],'term':term,'capturedAt':s['latitude'].get('capturedAt'),'source':p['source']})
        test=s.get('gpuPriceTests',{})
        if not s.get('gpuPriceTestsStatus',{}).get('ok'):continue
        for r in test.get('rows',[]):
            key=next((k for k,q in sellers.items()if q['gpu']==r['family'] and q['provider']==r['provider'] and q.get('instance')==r.get('instance') and q.get('region')==r.get('region')),r['quoteKey']);q=sellers.setdefault(key,{'key':key,'gpu':r['family'],'provider':r['provider'],'instance':r.get('instance'),'region':r.get('region'),'verification':'Aggregator-sourced; vendor bundle/availability not independently verified','source_url':r['source_url'],'points':[]})
            point={'date':day,'value':r['derivedUsdPerGpuHour'],'originalNodePrice':r['listed_price_hour'],'gpuCount':r['gpu_count'],'origin':'Own stored GPU Economy observation','methodologyVersion':r['methodologyVersion']}
            q['points']=[a for a in q['points'] if a['date']!=day]+[point];q['points'].sort(key=lambda a:a['date'])
    out['latitude']=[{'key':k,'name':ps[-1]['id']+' · '+ps[-1]['term'],'gpu':ps[-1]['gpu'],'points':ps,'caveat':'Latitude H100 exact variant unverified. Full plan includes CPU/RAM/storage/network. No B200/A100 plan present.'}for k,ps in groups.items()]
    out['sellerObservations']=list(sellers.values());(ROOT/'comparison_data.json').write_text(json.dumps(out,separators=(',',':'))+'\n')
    return out
if __name__=='__main__':print('Built local comparison:',len(build()['semiAnalysis']),'source dates')
