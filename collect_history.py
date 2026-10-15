"""One conditional GET to the public model aggregate history; optional, no retries."""
import json,urllib.request,urllib.error,datetime
from pathlib import Path
from collect_benchmark import NoRedirect
ROOT=Path(__file__).resolve().parent;URL='https://gpueconomy.com/history.json'
def main():
    seed=json.loads((ROOT/'comparison_history.json').read_text());meta=ROOT/'gpu_history_http.json';old=json.loads(meta.read_text())if meta.exists()else{};headers={'User-Agent':'field-notes-daily/1.1 (one daily conditional request; no retries)','Accept':'application/json'}
    if old.get('etag'):headers['If-None-Match']=old['etag']
    try:
        try:
            with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(URL,headers=headers),timeout=45)as r:d=json.load(r);etag=r.headers.get('ETag')
        except urllib.error.HTTPError as e:
            if e.code==304:print('Aggregate history unchanged');return
            raise
        if d.get('license')!='CC BY 4.0':raise ValueError('History license changed')
        changes=[]
        for m in d.get('models',[]):
            gpu='h100'if m['gpu_id']=='h100-sxm'else 'b200'if m['gpu_id']=='b200'else None
            if not gpu:continue
            for s in m['series']:
                origin=s['source'];kind='catalog'if origin=='skypilot-catalog'else'own-model';identity=gpu+'-'+kind;points=[]
                for p in s['weeks']:
                    points.append({'date':p['week_start'],'median':p['median_usd_per_gpu_hour'],'cheapest':p['min_usd_per_gpu_hour'],'providers':p['providers'],'minProvider':p.get('min_provider'),'minRegion':p.get('min_region'),'minSource':p.get('min_source_url')})
                changes.append({'id':identity,'gpu':gpu,'kind':kind,'name':('SkyPilot reconstructed 'if kind=='catalog'else'GPU Economy own model ') +gpu.upper(),'source':URL,'points':points})
        # Preserve old weeks; refresh only the explicitly current calendar week.
        for new in changes:
            match=next((a for a in seed['aggregates']if a['id']==new['id']),None)
            if match:
                today=datetime.datetime.now(datetime.timezone.utc).date();week=(today-datetime.timedelta(days=today.weekday())).isoformat()
                olddates={p['date']for p in match['points']}
                for point in new['points']:
                    if point['date']not in olddates:match['points'].append(point)
                    elif point['date']==week:match['points']=[point if p['date']==week else p for p in match['points']]
                match['points'].sort(key=lambda p:p['date'])
            else:seed['aggregates'].append(new)
        (ROOT/'comparison_history.json').write_text(json.dumps(seed,separators=(',',':'))+'\n');meta.write_text(json.dumps({'etag':etag,'updatedAt':d['data_updated_at']})+'\n')
    except Exception as e:print('::warning::GPU Economy aggregate history failed; stored history unchanged: '+str(e)[:200])
if __name__=='__main__':main()
