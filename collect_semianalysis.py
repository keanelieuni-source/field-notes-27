"""Optional single-request SemiAnalysis collector.
Preserves the supplied archive's immutable source-date logic; no redirects or retries.
"""
import csv,json,sys,datetime,urllib.request,urllib.error
from pathlib import Path
from gpu_archive import NoRedirect,parse,pending,append,INDEX_FIELDS,CONTRACT_FIELDS,URL
ROOT=Path(__file__).resolve().parent

def main():
    status={'checkedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'ok':False}
    try:
        req=urllib.request.Request(URL,headers={'User-Agent':'FieldNotesPricingCheck/1.0 (one request per day; no retries)','Accept':'application/json'})
        with urllib.request.build_opener(NoRedirect).open(req,timeout=30) as r:body=r.read()
        daily,contracts=parse(json.loads(body));new=pending(ROOT/'gpu_index.csv',INDEX_FIELDS,daily);newcontracts=pending(ROOT/'h100_contracts.csv',CONTRACT_FIELDS,contracts)
        append(ROOT/'gpu_index.csv',INDEX_FIELDS,new);append(ROOT/'h100_contracts.csv',CONTRACT_FIELDS,newcontracts)
        status.update(ok=True,newDates=len(new),latestSourceDate=daily[-1][0]);print('SemiAnalysis loaded:',len(new),'new index dates; latest source date',daily[-1][0])
    except Exception as e:
        status['message']='SemiAnalysis fetch failed; last good CSV unchanged: '+str(e)[:200];print('::warning::'+status['message'])
    (ROOT/'semi_status.json').write_text(json.dumps(status)+'\n')
if __name__=='__main__':main()
