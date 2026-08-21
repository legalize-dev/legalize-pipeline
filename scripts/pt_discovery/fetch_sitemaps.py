import re, sys, time, gzip, os
from concurrent.futures import ThreadPoolExecutor
import requests
import os
WORK = os.environ.get("PT_WORK", os.path.join(os.path.dirname(__file__),
    "..", "..", "..", "countries", "data-pt", "discovery-work"))
os.makedirs(WORK, exist_ok=True)


UA = "legalize-bot/1.0 (+https://github.com/legalize-dev/legalize-pipeline)"
DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "countries", "data-pt", "sitemaps")
locs = re.findall(r"<loc>([^<]+)</loc>", open(f"{DIR}/sitemap.xml").read())

URL_RE = re.compile(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]*)</lastmod>)?", re.S)
sess = requests.Session(); sess.headers["User-Agent"] = UA
lock_out = open(os.path.join(WORK, os.path.join(WORK,"allurls.tsv")), "w")

def grab(u):
    name = u.rsplit("/", 1)[1]
    dst = f"{DIR}/{name}.gz"
    if os.path.exists(dst):
        body = gzip.open(dst, "rt", encoding="utf-8", errors="replace").read()
    else:
        for _ in range(4):
            try:
                r = sess.get(u, timeout=120)
                if r.status_code == 429: time.sleep(15); continue
                if r.status_code != 200: return name, r.status_code, []
                body = r.content.decode("utf-8", "replace"); break
            except Exception: time.sleep(3)
        else: return name, -1, []
        with gzip.open(dst, "wt", encoding="utf-8") as f: f.write(body)
    return name, 200, URL_RE.findall(body)

t0 = time.time(); nurl = 0; bad = []
with ThreadPoolExecutor(max_workers=5) as ex:
    for i, (name, st, rows) in enumerate(ex.map(grab, locs)):
        if st != 200: bad.append((name, st)); continue
        stype = re.sub(r"-sitemap-\d+\.xml$", "", name)
        for loc, lm in rows:
            lock_out.write(f"{stype}\t{loc}\t{lm}\n"); nurl += 1
        if i % 50 == 0: print(i, name, len(rows), nurl, round(time.time()-t0), file=sys.stderr)
lock_out.close()
print("DONE", nurl, "urls in", round(time.time()-t0,1), "s; failed:", bad, file=sys.stderr)
