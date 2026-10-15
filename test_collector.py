import importlib.util, json,tempfile,copy,hashlib
from pathlib import Path
spec=importlib.util.spec_from_file_location('collector',str(Path(__file__).resolve().parent/'collect_latitude.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
import collect_demand
collect_demand.collect=lambda o,r,now:(copy.deepcopy(o),copy.deepcopy(r))
original=json.load(open(Path(__file__).resolve().parent/'snapshots.json'));base=next(iter(original['snapshots'].values()))
for kind in ['missing-plan','missing-value','huge-price','hardware','location']:
 with tempfile.TemporaryDirectory() as td:
  m.ROOT=Path(td);f=m.ROOT/'snapshots.json';f.write_text(json.dumps(original));before=f.read_bytes();plans=copy.deepcopy(base['latitude']['plans'])
  if kind=='missing-plan':plans.pop()
  elif kind=='missing-value':plans[0]['hourly']=None
  elif kind=='huge-price':plans[0]['hourly']*=2
  elif kind=='hardware':plans[0]['hardware']='wrong'
  elif kind=='location':plans[0]['locations'].pop()
  m.collect=lambda:plans
  try:m.main();raise AssertionError('Should reject '+kind)
  except ValueError:assert f.read_bytes()==before;print(kind,'rejected; old file unchanged')
with tempfile.TemporaryDirectory() as td:
 m.ROOT=Path(td);data=copy.deepcopy(original);data['snapshots']['2026-10-14']=copy.deepcopy(base);data['snapshots']['2026-10-14']['date']='2026-10-14';data['snapshots']['2026-10-14']['capturedAt']='2026-10-14';f=m.ROOT/'snapshots.json';f.write_text(json.dumps(data));m.collect=lambda:copy.deepcopy(base['latitude']['plans']);m.main();after=json.loads(f.read_text());assert after['snapshots']['2026-10-14']==data['snapshots']['2026-10-14'];print('Earlier snapshot preserved exactly')
