import gzip, re, collections, json, random
import os
WORK = os.environ.get("PT_WORK", os.path.join(os.path.dirname(__file__),
    "..", "..", "..", "countries", "data-pt", "discovery-work"))
os.makedirs(WORK, exist_ok=True)

# global index: numkey (number-year, upper) -> set(tipo);  plus number-only index
g = collections.defaultdict(set); gnum = collections.defaultdict(set)
YEAR = re.compile(r"1[5-9]\d\d|20[0-3]\d")
for l in gzip.open(os.path.join(os.path.dirname(__file__),"..","..","..","countries","data-pt","sitemaps","_all-detalhe-urls.tsv.gz"),"rt"):
    t, key, y = l.rstrip("\n").split("\t")
    if t == "ato-societario": continue
    nk = key.rsplit("-",1)[0].upper()
    g[nk].add(t)
    p = nk.split("-")
    if len(p)>1 and YEAR.fullmatch(p[-1]): gnum["-".join(p[:-1])].add(t)
print("global numkeys:", len(g), "number-only:", len(gnum))

def cands(num):
    v = {num}
    p = num.split("-")
    if len(p)>1 and re.fullmatch(r"\d{2}", p[-1]):
        yy=int(p[-1]); v.add("-".join(p[:-1]+[str(1900+yy if yy>=11 else 2000+yy)]))
    # …/YYYY/N  ->  repo id ends -YYYY-N ; DRE key has no /N
    if len(p)>2 and re.fullmatch(r"\d{1,2}", p[-1]) and YEAR.fullmatch(p[-2]):
        v |= cands("-".join(p[:-1]))
    if len(p)>1 and p[-1] in ("A","M"): v |= cands("-".join(p[:-1]))
    return v

repo=[l.strip().removeprefix("pt/").removesuffix(".md")
      for l in open(os.environ.get("PT_FILES", "/tmp/pt-files.txt"))]
hit=0; miss=[]; how=collections.Counter(); tipohit=collections.Counter()
for rid in repo:
    m=re.match(r"^DRE-([A-Z]+)-(.*)$", rid)
    if not m: miss.append(rid); continue
    num=m.group(2).upper(); ok=False
    for v in cands(num):
        if v in g: how["number+year"]+=1; tipohit.update(g[v]); ok=True; break
    if not ok and num in gnum: how["number-only"]+=1; ok=True
    if ok: hit+=1
    else: miss.append(rid)
print(f"\nREPO -> SITEMAP (type-agnostic): {hit}/{len(repo)} = {100*hit/len(repo):.2f}%; missing {len(miss)}")
print("how:", dict(how))
random.seed(3); print("\nsample misses:", random.sample(miss, min(30,len(miss))))
json.dump(miss, open(os.path.join(WORK,"repo-misses2.json"),"w"))
cnt=collections.Counter(r.split("-")[1] for r in miss); print("\nmisses by code:", cnt.most_common())
