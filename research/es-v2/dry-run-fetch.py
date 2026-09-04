import json,os,random,re,time,urllib.request
D='/Users/neli/.claude/jobs/5bf7ddf4/tmp/dryrun'
UA='legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)'
YEARS=[1979,1984,1989,1993,1997,2001,2005,2009,2013,2017,2021,2025]
PER=35
n=[0]
def get(url,delay=1.0):
    time.sleep(delay); n[0]+=1
    r=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/xml'})
    try:
        with urllib.request.urlopen(r,timeout=90) as f: return f.status, f.read()
    except urllib.error.HTTPError as e: return e.code, b''
    except Exception as e: return -1, str(e).encode()

# 1. index: one request per year
idx={}
for y in YEARS:
    u=(f'https://www.boe.es/buscar/boe.php?campo%5B0%5D=ORIS&dato%5B0%5D%5B1%5D=1'
       f'&operador%5B0%5D=and&campo%5B6%5D=FPU&operador%5B6%5D=and'
       f'&dato%5B6%5D%5B0%5D={y}-01-01&dato%5B6%5D%5B1%5D={y}-12-31&page_hits=2000&accion=Buscar')
    st,b=get(u)
    h=b.decode('utf-8','replace')
    tot=re.search(r'de ([0-9.]+)</',h)
    ids=sorted(set(re.findall(rf'id=(BOE-A-{y}-\d+)',h)))
    idx[y]={'status':st,'declared':int(tot.group(1).replace('.','')) if tot else None,'parsed':len(ids),'ids':ids}
    print(f'{y}: http {st} declarado {idx[y]["declared"]} parseado {len(ids)}',flush=True)
json.dump({k:{kk:vv for kk,vv in v.items() if kk!="ids"} for k,v in idx.items()},
          open(f'{D}/index_check.json','w'),indent=1)

# 2. sample and fetch the diary document for each
rnd=random.Random(20260903); sample=[]
for y in YEARS:
    ids=idx[y]['ids']
    sample += rnd.sample(ids,min(PER,len(ids)))
print(f'\nmuestra: {len(sample)} actos',flush=True)
meta={}
for i,bid in enumerate(sample,1):
    p=f'{D}/raw/{bid}.xml'
    if os.path.exists(p): continue
    st,b=get(f'https://www.boe.es/diario_boe/xml.php?id={bid}')
    meta[bid]=st
    if st==200: open(p,'wb').write(b)
    if i%40==0: print(f'  {i}/{len(sample)}  peticiones={n[0]}',flush=True)
json.dump({'sample':sample,'status':meta,'requests':n[0]},open(f'{D}/sample.json','w'),indent=1)
print(f'\nTOTAL peticiones: {n[0]}')
