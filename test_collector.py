"""Offline tests for catalog changes, mutation gates and historical preservation."""
import copy,json,tempfile
from pathlib import Path
import collect_latitude as collector
from collect_latitude import classify_table, missing_plan_record, validate_against_previous
import collect_demand

source=Path(__file__).resolve().parent/'snapshots.json'
data=json.loads(source.read_text())
latest=max(data['snapshots'].values(),key=lambda x:x['capturedAt'])
all_old={p['id']:p for p in latest['latitude']['plans']}
listed=[copy.deepcopy(p) for p in latest['latitude']['plans'] if p.get('currentStatus')!='not_listed_in_current_catalog']
old_listed={p['id']:p for p in listed}
checked='2026-10-31T08:00:00+11:00'

# Current headings and plan IDs classify tables without hard-coding generation count.
assert classify_table([['PLAN','GPU'],['g4.x','GPU']])=='Metal GPU'
assert classify_table([['PLAN','VCPU'],['vm.x','VM']])=='Virtual machines'
assert classify_table([['PLAN','CPU'],['rs4.x','CPU'],['m4.y','CPU']])=='Metal Gen 4'
assert classify_table([['PLAN','CPU'],['m3.x','CPU']])=='Metal Gen 3'
for bad in [[['PLAN','Other'],['m4.x','x']], [['PLAN','CPU'],['unknown','x']], [['PLAN','CPU'],['m4.x','x'],['c3.x','x']]]:
    try: classify_table(bad)
    except ValueError: pass
    else: raise AssertionError('unrecognized table accepted: '+repr(bad))

# Billing selection must wait against current DOM state, not a captured element.
class FakeButton:
    def __init__(self,page,index): self.page,self.index=page,index
    def click(self): self.page.active[self.index]=True  # simulate a replaced DOM node
class FakeButtons:
    def __init__(self,page): self.page=page
    def count(self): return len(self.page.active)
    def nth(self,index): return FakeButton(self.page,index)
class FakePage:
    def __init__(self): self.active=[False,False,False];self.waits=[]
    def get_by_role(self,*args,**kwargs): return FakeButtons(self)
    def wait_for_function(self,script,arg=None,timeout=None):
        self.waits.append((arg,timeout))
        if isinstance(arg,dict): assert self.active[arg['index']]
        else: assert all(self.active)
class NeverSettlesPage(FakePage):
    def wait_for_function(self,script,arg=None,timeout=None): raise TimeoutError('selector state did not change')
ui=FakePage();collector.select_billing_term(ui,'Monthly');assert all(ui.active) and len(ui.waits)==4
assert all(timeout==15000 for _,timeout in ui.waits)
try:collector.select_billing_term(NeverSettlesPage(),'Paid yearly')
except TimeoutError:pass
else:raise AssertionError('failed billing selector was allowed to continue')
print('billing selector current-DOM success and timeout behavior passed')

# Unavailable Gen3 history remains separated from null current values.
unavailable=[p for p in latest['latitude']['plans'] if p.get('currentStatus')=='not_listed_in_current_catalog']
assert {p['id'] for p in unavailable}=={'m3.large.x86','s3.large.x86','c3.large.x86','c3.small.x86'}
for old_plan in unavailable:
    row=missing_plan_record(old_plan,latest['latitude']['capturedAt'],checked)
    assert row['hourly'] is None and row['locations']==[]
    assert row['lastKnown']==old_plan['lastKnown']
    assert row['lastObservedAt']==old_plan['lastObservedAt']
    assert row['currentStatus']=='not_listed_in_current_catalog'
    assert 'retirement not confirmed' in row['availability']

# Listed-price mutation checks still apply to current listings.
base=copy.deepcopy(old_listed['rs4.metal.xlarge'])
mutations=[]
x=copy.deepcopy(base);x['hourly']=None;mutations.append(('missing-value',x))
x=copy.deepcopy(base);x['hourly']*=2;mutations.append(('huge-price',x))
x=copy.deepcopy(base);x['hardware']='wrong';mutations.append(('hardware',x))
x=copy.deepcopy(base);x['locations'].pop();mutations.append(('location',x))
for name,plan in mutations:
    try:validate_against_previous(plan,base)
    except ValueError:print(name,'rejected')
    else:raise AssertionError('Should reject '+name)

oldpartial=collect_demand.collect_partial
oldroot=collector.ROOT
oldcollect=collector.collect
try:
    collect_demand.collect_partial=lambda o,r,n:(copy.deepcopy(o),copy.deepcopy(r),{})
    # Unsafe malformed plans and unknown IDs are rejected before stored data changes.
    for kind in ['missing-value','huge-price','hardware','location','unknown-id','reappearance-price']:
        with tempfile.TemporaryDirectory() as td:
            collector.ROOT=Path(td);f=collector.ROOT/'snapshots.json';f.write_text(json.dumps(data));before=f.read_bytes()
            plans=copy.deepcopy(listed)
            if kind=='missing-value': plans[0]['hourly']=None
            elif kind=='huge-price': plans[0]['hourly']*=2
            elif kind=='hardware': plans[0]['hardware']='wrong'
            elif kind=='location': plans[0]['locations'].pop()
            elif kind=='unknown-id': plans[0]['id']='new.unknown.plan'
            else:
                prior=all_old['c3.large.x86'];known=copy.deepcopy(prior['lastKnown'])
                p={'id':prior['id'],**known,'category':prior['category'],'currentStatus':'listed_in_current_catalog'}
                p['hourly']*=2;plans.append(p)
            collector.collect=lambda plans=plans:copy.deepcopy(plans)
            try:
                try:collector.main()
                except ValueError:pass
                else:raise AssertionError('main accepted '+kind)
                assert f.read_bytes()==before,kind+' changed stored file before rejecting'
            finally:collector.ROOT=Path(__file__).resolve().parent
            print(kind,'rejected; stored file unchanged')

    def run_main(plans):
        with tempfile.TemporaryDirectory() as td:
            collector.ROOT=Path(td);f=collector.ROOT/'snapshots.json';f.write_text(json.dumps(data))
            before=json.loads(f.read_text())
            collector.collect=lambda:copy.deepcopy(plans)
            collector.main();after=json.loads(f.read_text())
            return before,after

    # Listed -> unavailable: preserve source values and the date it was actually observed.
    ident='rs4.metal.xlarge';prior=copy.deepcopy(all_old[ident]);capture=latest['latitude']['capturedAt']
    plans=[p for p in listed if p['id']!=ident]
    before,after=run_main(plans)
    updated=max(after['snapshots'].values(),key=lambda x:x['capturedAt'])
    row=next(p for p in updated['latitude']['plans'] if p['id']==ident)
    assert row['hourly'] is None and row['currentStatus']=='not_listed_in_current_catalog'
    assert row['lastKnown']['hourly']==prior['hourly'] and row['lastObservedAt']==capture
    for date,snap in before['snapshots'].items():assert after['snapshots'][date]==snap
    print('listed-to-unavailable transition and historical snapshots passed')

    # Already unavailable -> still unavailable next day: preserve original known values and last-observed date.
    plans=copy.deepcopy(listed)
    before,after=run_main(plans)
    updated=max(after['snapshots'].values(),key=lambda x:x['capturedAt'])
    for old_plan in unavailable:
        row=next(p for p in updated['latitude']['plans'] if p['id']==old_plan['id'])
        assert row['lastKnown']==old_plan['lastKnown']
        assert row['lastObservedAt']==old_plan['lastObservedAt']
        assert row['hourly'] is None and row['currentStatus']=='not_listed_in_current_catalog'
    for date,snap in before['snapshots'].items():assert after['snapshots'][date]==snap
    print('repeat-day unavailable state and historical snapshots passed')

    # Reappearance: validate against lastKnown values; then publish fresh values as current.
    returning=all_old['c3.large.x86'];known=copy.deepcopy(returning['lastKnown'])
    recovered={'id':returning['id'],'category':returning['category'],**known,
               'currentStatus':'listed_in_current_catalog','basis':'Current source display validated.'}
    plans=copy.deepcopy(listed)+[recovered]
    before,after=run_main(plans)
    updated=max(after['snapshots'].values(),key=lambda x:x['capturedAt'])
    row=next(p for p in updated['latitude']['plans'] if p['id']==returning['id'])
    assert row['currentStatus']=='listed_in_current_catalog' and row['hourly']==known['hourly']
    assert 'lastKnown' not in row and 'lastObservedAt' not in row
    for date,snap in before['snapshots'].items():assert after['snapshots'][date]==snap
    print('unavailable-to-listed reappearance and historical snapshots passed')
finally:
    collect_demand.collect_partial=oldpartial
    collector.ROOT=oldroot
    collector.collect=oldcollect
print('Classification, catalog transitions, mutation guards, and history preservation tests passed')
