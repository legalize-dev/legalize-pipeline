import sys, json, random, time, datetime, gzip, re, collections
import os
WORK = os.environ.get("PT_WORK", os.path.join(os.path.dirname(__file__),
    "..", "..", "..", "countries", "data-pt", "discovery-work"))
os.makedirs(WORK, exist_ok=True)

sys.path.insert(0,os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from legalize.fetcher.pt.client import DREHttpClient, DREApiError

random.seed(11)
dates=[]
for y in range(1960, 2027):
    for _ in range(2):
        d = datetime.date(y,1,1) + datetime.timedelta(days=random.randrange(365))
        if d.weekday() < 5 and d <= datetime.date(2026,8,20): dates.append(d.isoformat())
dates = sorted(set(dates))
print("sampling", len(dates), "dates", file=sys.stderr)

c = DREHttpClient()
rows=[]; t0=time.time(); errs=[]
for i,ds in enumerate(dates):
    try: js = c.get_journals_by_date(ds)
    except Exception as e: errs.append((ds,repr(e)[:120])); continue
    for j in js:
        title = j.get("conteudoTitle","")
        if not re.search(r"Série I(?!I)", title): continue
        sup = "Suplemento" in title
        try: docs = c.get_documents_by_journal(j["Id"], is_serie1=True)
        except Exception as e: errs.append((ds,j["Id"],repr(e)[:120])); continue
        for d in docs:
            rows.append({"date":ds,"journal":title,"sup":sup,"ref":d.get("LinkSitemap",""),
                         "num":d.get("Numero",""),"tipo":d.get("TipoDiploma",""),
                         "noindex":d.get("Isnoindex")})
    if i%20==0: print(i, ds, len(rows), round(time.time()-t0), file=sys.stderr)
json.dump({"rows":rows,"errs":errs,"dates":dates}, open(os.path.join(WORK,"journalwalk1.json"),"w"))
print("docs", len(rows), "errs", len(errs), "elapsed", round(time.time()-t0,1), file=sys.stderr)
