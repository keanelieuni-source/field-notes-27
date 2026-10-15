"""Offline malformed-value tests. No network calls or data writes."""
import copy,json
from pathlib import Path
from collect_demand import validate
ROOT=Path(__file__).resolve().parent
p=max(json.loads((ROOT/'snapshots.json').read_text())['snapshots'].values(),key=lambda s:s['capturedAt'])
o,r=p['openrouter'],p['ramp']
validate(o,r,o,r)
for kind in ['duplicate-model','missing-model','negative-tokens','shares-total','nan-spend','future-date','regressed-period','missing-maker','adoption-range']:
    a,b=copy.deepcopy(o),copy.deepcopy(r)
    if kind=='duplicate-model':a['weekTopModels'][1]['model']=a['weekTopModels'][0]['model']
    elif kind=='missing-model':a['weekTopModels'].pop()
    elif kind=='negative-tokens':a['weekTopModels'][0]['tokensT']=-1
    elif kind=='shares-total':a['marketShare'][0]['share']=0
    elif kind=='nan-spend':b['spendPerEmployee']=float('nan')
    elif kind=='future-date':a['usageThrough']='2099-01-01'
    elif kind=='regressed-period':b['period']='2020-01'
    elif kind=='missing-maker':b['tokenSpend']['makers']=[x for x in b['tokenSpend']['makers'] if x['maker']!='OpenAI']
    elif kind=='adoption-range':b['adoption']['overall']=150
    try:validate(a,b,o,r)
    except ValueError:print(kind,'rejected')
    else:raise AssertionError('Accepted bad data: '+kind)
print('All demand safety tests passed')
