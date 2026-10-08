"""El corpus se ensena su propio vocabulario de encabezados.
Supervision: los documentos donde la fuente SI marca (class=articulo).
Cero conocimiento de idioma, cero HTTP."""
import glob,os,re,json,collections
from lxml import etree
D='/Users/neli/.claude/jobs/5bf7ddf4/tmp/dryrun'
def tok(t):
    w=t.split()
    return w[0].strip('.:,;()[]«»"') if w else ''

docs=[]
for p in sorted(glob.glob(f'{D}/raw/*.xml')):
    root=etree.fromstring(open(p,'rb').read()); t=root.find('texto')
    if t is None: continue
    ps=[((e.get('class') or ''), ' '.join(e.itertext()).strip()) for e in t.iter('p')]
    ps=[(c,x) for c,x in ps if x]
    if ps: docs.append((os.path.basename(p)[:-4], ps))

# --- FASE 1: aprender del subconjunto supervisado -------------------------
pos=collections.Counter(); neg=collections.Counter()
sup=0
for bid,ps in docs:
    if not any(c=='articulo' for c,_ in ps): continue
    sup+=1
    for c,x in ps:
        k=tok(x)
        if not k: continue
        (pos if c=='articulo' else neg)[k]+=1
# un token es marcador si aparece mucho como articulo y casi nunca como no-articulo
learned={k:(v,neg[k]) for k,v in pos.items() if v>=5 and v/(v+neg[k])>=0.80}
print(f"FASE 1 — aprendido de {sup} documentos que la fuente SI marca:")
for k,(a,b) in sorted(learned.items(),key=lambda z:-z[1][0]):
    print(f"   {k!r:16} como articulo {a:5}  como no-articulo {b:4}   precision {100*a/(a+b):.0f}%")

# --- FASE 2: aplicarlo donde la fuente NO marca ---------------------------
L=set(learned)
json.dump(sorted(L),open(f'{D}/learned_tokens.json','w'),ensure_ascii=False,indent=1)
rows={x['id']:x for x in json.load(open(f'{D}/rows.json'))}
DROP={'1590','1240','63','1250'}
fails=[b for b,_ in docs if (r:=rows.get(b)) and r['rango'] not in DROP and not r['corr']
       and r['nchar']>0 and r['heads']==0 and r['looks']>0]
tot=solved=recov=0
for bid,ps in docs:
    if bid not in fails: continue
    tot+=1
    n=sum(1 for _,x in ps if tok(x) in L)
    if n: solved+=1; recov+=n
print(f"\nFASE 2 — aplicado a los {tot} documentos donde la fuente NO marca:")
print(f"   estructura recuperada en: {solved}/{tot}  ({100*solved/tot:.0f}%)")
print(f"   encabezados recuperados:  {recov}")
