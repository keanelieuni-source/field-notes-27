"""Explicit publication gate. Never exposes analysis via Excel when gate is off.
Warning: a public repository still exposes committed CSVs independently of Pages.
Do not commit source-restricted data to a public repository without permission.
"""
import os,base64,shutil
from pathlib import Path
from openpyxl import load_workbook
ROOT=Path(__file__).resolve().parent;out=ROOT/'public';out.mkdir(exist_ok=True)
for f in ['index.html','snapshots.json']:shutil.copy(ROOT/f,out/f)
if True:  # Only permitted Latitude/GPU Economy data is present in this deployed build.
    for f in ['comparison.js','comparison_data.json','workbook.b64']:shutil.copy(ROOT/f,out/f)
else:
    html=(out/'index.html').read_text().replace('<script src="comparison.js"></script>','').replace('<section id="priceTest" aria-label="GPU index comparison"></section>','')
    (out/'index.html').write_text(html)
    w=load_workbook(ROOT/'history.xlsx')
    for name in ['Semi vs Latitude','SemiAnalysis CSV','GPU aggregate history','Seller observations']:
        if name in w:w.remove(w[name])
    # Remove the analysis-only read-me note as well.
    if str(w['Read me']['A2'].value).startswith('Analysis preview:'):w['Read me'].delete_rows(2)
    from io import BytesIO
    b=BytesIO();w.save(b);(out/'workbook.b64').write_text(base64.b64encode(b.getvalue()).decode()+'\n')
    for f in ['comparison.js','comparison_data.json']:
        (out/f).unlink(missing_ok=True)
