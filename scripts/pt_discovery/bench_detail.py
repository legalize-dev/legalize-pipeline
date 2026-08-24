import sys, json, time, random, gzip, statistics as st, threading, collections
import os
WORK = os.environ.get("PT_WORK", os.path.join(os.path.dirname(__file__),
    "..", "..", "..", "countries", "data-pt", "discovery-work"))
os.makedirs(WORK, exist_ok=True)

sys.path.insert(0,os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from concurrent.futures import ThreadPoolExecutor
import legalize.fetcher.pt.client as C
from legalize.fetcher.pt.client import DREHttpClient, DOCUMENT_DETAIL, _split_sitemap_ref

# neutralise the racy periodic re-init (see finding): keep one warm session
_orig = DREHttpClient._post
def _post_norefresh(self, endpoint, payload):
    self._request_count = 1          # never hits % 100
    return _orig(self, endpoint, payload)
DREHttpClient._post = _post_norefresh

refs = json.load(open(os.path.join(WORK,"bench-refs.json")))
def raw(c, ref):
    tipo,key=_split_sitemap_ref(ref)
    p={"viewName":"Legislacao_Conteudos.Conteudo_Detalhe","screenData":{"variables":{
        "Tipo":tipo,"_tipoInDataFetchStatus":1,"Key":key,"_keyInDataFetchStatus":1,
        "ParteId":"0","_parteIdInDataFetchStatus":1}},"clientVariables":{"DiplomaConteudoId":""}}
    return c._post(DOCUMENT_DETAIL,p)

results={}; recs=[]; stop=threading.Event()
def run(label, nworkers, n, offset):
    if stop.is_set(): print("skipped", label, file=sys.stderr); return
    c = DREHttpClient(); c._min_interval = 0.0
    lat=[]; size=[]; err=[]; lock=threading.Lock()
    sub = refs[offset:offset+n]
    def one(r):
        t=time.time()
        try:
            data=raw(c,r); dt=time.time()-t
            d=data.get("data",{}).get("DetalheConteudo",{})
            body=json.dumps(data,ensure_ascii=False).encode()
            with lock:
                lat.append(dt); size.append(len(body))
                recs.append(dict(ref=r, bytes=len(body), date=d.get("DataPublicacao",""),
                    serie=d.get("Serie",""), sup=d.get("Suplemento",""), numero=d.get("Numero",""),
                    eli=bool(d.get("ELI")), pdf=bool(d.get("URL_PDF")),
                    txt=len(d.get("Texto","")), tf=len(d.get("TextoFormatado","")),
                    tipo=d.get("TipoDiploma","")))
        except Exception as e:
            m=str(e)[:160]
            with lock:
                err.append((type(e).__name__,m))
                if "429" in m or "Too Many" in m: stop.set()
    t0=time.time()
    with ThreadPoolExecutor(max_workers=nworkers) as ex: list(ex.map(one, sub))
    w=time.time()-t0; ok=len(lat)
    results[label]=dict(workers=nworkers, n=n, ok=ok, errors=len(err), wall=round(w,1),
        req_per_s=round(n/w,2), lat_mean=round(st.mean(lat),3), lat_p50=round(st.median(lat),3),
        lat_p95=round(sorted(lat)[min(int(.95*len(lat)),len(lat)-1)],3),
        bytes_mean=int(st.mean(size)), bytes_p50=int(st.median(size)), bytes_max=max(size),
        errkinds=dict(collections.Counter(e[0] for e in err)))
    print(label, json.dumps(results[label]), file=sys.stderr)
    if err: print("   err sample:", err[:3], file=sys.stderr)

run("w1",  1, 60,   0)
run("w2",  2, 100,  60)
run("w4",  4, 140, 160)
run("w8",  8, 160, 300)
run("w16",16, 100, 460)
json.dump({"results":results,"recs":recs}, open(os.path.join(WORK,"bench3.json"),"w"))
print("records collected:", len(recs), file=sys.stderr)
