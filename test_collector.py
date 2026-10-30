"""Offline tests for table classification, price safety and missing-catalog records."""
import copy,json,tempfile
from pathlib import Path
import collect_latitude as collector
from collect_latitude import classify_table, missing_plan_record, validate_against_previous
import collect_demand
source=Path(__file__).resolve().parent/'snapshots.json'
data=json.loads(source.read_text());latest=max(data['snapshots'].values(),key=lambda x:x['capturedAt'])
old={p['id']:p for p in latest['latitude']['plans']}
# Dynamic table classification handles a missing generation without dropping its history.
assert classify_table([['PLAN','GPU'],['g4.x','GPU']])=='Metal GPU'
assert classify_table([['PLAN','VCPU'],['vm.x','VM']])=='Virtual machines'
assert classify_table([['PLAN','CPU'],['rs4.x','CPU'],['m4.y','CPU']])=='Metal Gen 4'
assert classify_table([['PLAN','CPU'],['m3.x','CPU']])=='Metal Gen 3'
for bad in [[['PLAN','Other'],['m4.x','x']], [['PLAN','CPU'],['unknown','x']], [['PLAN','CPU'],['m4.x','x'],['c3.x','x']]]:
    try: classify_table(bad)
    except ValueError: pass
    else: raise AssertionError('unrecognized table accepted: '+repr(bad))
# Preserve historical missing SKUs, but do not claim old pricing is current.
for ident in ['m3.large.x86','s3.large.x86','c3.large.x86','c3.small.x86']:
    row=missing_plan_record(old[ident],latest['latitude']['capturedAt'],'2026-10-30T08:00:00+11:00')
    assert row['hourly'] is None and row['lastKnown']['hourly']==old[ident]['hourly']
    assert row['currentStatus']=='not_listed_in_current_catalog'
    assert 'retirement not confirmed' in row['availability'] and not row['locations']
# Preserve the previous mutation guard coverage for listed plans.
base=copy.deepcopy(old['rs4.metal.xlarge'])
mutations=[]
x=copy.deepcopy(base);x['hourly']=None;mutations.append(('missing-value',x))
x=copy.deepcopy(base);x['hourly']*=2;mutations.append(('huge-price',x))
x=copy.deepcopy(base);x['hardware']='wrong';mutations.append(('hardware',x))
x=copy.deepcopy(base);x['locations'].pop();mutations.append(('location',x))
for name,plan in mutations:
    try:validate_against_previous(plan,base)
    except ValueError:print(name,'rejected')
    else:raise AssertionError('Should reject '+name)
# Exercise the main write path: invalid changes must not touch the stored file.
original=copy.deepcopy(data); baseline=copy.deepcopy(latest['latitude']['plans'])
for kind in ['missing-value','huge-price','hardware','location','unknown-id']:
    with tempfile.TemporaryDirectory() as td:
        collector.ROOT=Path(td);f=collector.ROOT/'snapshots.json';f.write_text(json.dumps(original));before=f.read_bytes()
        plans=copy.deepcopy(baseline)
        if kind=='missing-value': plans[0]['hourly']=None
        elif kind=='huge-price': plans[0]['hourly']*=2
        elif kind=='hardware': plans[0]['hardware']='wrong'
        elif kind=='location': plans[0]['locations'].pop()
        else: plans[0]['id']='new.unknown.plan'
        collector.collect=lambda:plans
        oldpartial=collect_demand.collect_partial;collect_demand.collect_partial=lambda o,r,n:(copy.deepcopy(o),copy.deepcopy(r),{})
        try:
            try: collector.main()
            except ValueError: pass
            else: raise AssertionError('main accepted '+kind)
            assert f.read_bytes()==before,kind+' changed stored file before rejecting'
        finally: collect_demand.collect_partial=oldpartial
        print(kind,'rejected; stored file unchanged')
# A missing old catalog ID is retained as unavailable; all prior dated snapshots stay identical.
with tempfile.TemporaryDirectory() as td:
    collector.ROOT=Path(td);f=collector.ROOT/'snapshots.json';f.write_text(json.dumps(original))
    plans=[copy.deepcopy(p) for p in baseline if p['id']!='m3.large.x86']
    collector.collect=lambda:plans
    oldpartial=collect_demand.collect_partial;collect_demand.collect_partial=lambda o,r,n:(copy.deepcopy(o),copy.deepcopy(r),{})
    try:
        collector.main();after=json.loads(f.read_text())
        for date,snap in original['snapshots'].items(): assert after['snapshots'][date]==snap
        row=next(p for p in after['snapshots'][max(after['snapshots'])]['latitude']['plans'] if p['id']=='m3.large.x86')
        assert row['currentStatus']=='not_listed_in_current_catalog' and row['hourly'] is None
    finally: collect_demand.collect_partial=oldpartial
print('Classification, unavailable-plan status, mutation guard, and history preservation tests passed')
