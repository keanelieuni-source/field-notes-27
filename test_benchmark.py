import copy,unittest
from datetime import datetime,timezone
from collect_benchmark import parse,update
NOW=datetime(2026,10,15,4,tzinfo=timezone.utc)
def fixture():
 return {'license':'CC BY 4.0','unit':'USD per GPU per hour','data_updated_at':NOW.isoformat(),'methodology_version':'1','prices':[{'provider':'Peer','provider_id':'peer','gpu_id':'b300','gpu':'B300','gpu_count':8,'price_type':'on_demand','price_scope':'instance','listed_unit':'per_node','listed_currency':'USD','listed_price_hour':64,'status':'live','last_confirmed_at':NOW.isoformat(),'source_url':'https://example.com/pricing'}]}
class Tests(unittest.TestCase):
 def test_original_total(self):self.assertEqual(parse(fixture(),NOW)['rows'][0]['listed_price_hour'],64)
 def test_no_multi_gpu_math(self):
  d=fixture();d['prices'][0]['listed_unit']='per_gpu'
  with self.assertRaises(ValueError):parse(d,NOW)
 def test_stale(self):
  d=fixture();d['prices'][0]['last_confirmed_at']='2026-10-01T00:00:00+00:00'
  with self.assertRaises(ValueError):parse(d,NOW)
 def test_failure_preserves_direct_and_last_good(self):
  d={'snapshots':{'2026-10-15':{'capturedAt':NOW.isoformat(),'latitude':{'plans':[1]},'gpuEconomy':{'rows':['old']}}}};old=copy.deepcopy(d)
  update(d,lambda:(_ for _ in ()).throw(ValueError('fail')),NOW)
  self.assertEqual(d['snapshots']['2026-10-15']['latitude'],old['snapshots']['2026-10-15']['latitude']);self.assertEqual(d['snapshots']['2026-10-15']['gpuEconomy'],old['snapshots']['2026-10-15']['gpuEconomy']);self.assertFalse(d['snapshots']['2026-10-15']['gpuEconomyStatus']['ok'])
 def test_duplicate(self):
  d=fixture();d['prices']*=2
  with self.assertRaises(ValueError):parse(d,NOW)
 def test_no_change_to_earlier_dates(self):
  d={'snapshots':{'2026-10-14':{'capturedAt':'2026-10-14T00:00:00+00:00'},'2026-10-15':{'capturedAt':NOW.isoformat(),'latitude':{'plans':[1]}}}};before=copy.deepcopy(d['snapshots']['2026-10-14']);update(d,fixture,NOW);self.assertEqual(d['snapshots']['2026-10-14'],before)
if __name__=='__main__':unittest.main()
