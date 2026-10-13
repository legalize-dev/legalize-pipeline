"""Deducir el token de encabezado de articulo SIN conocer el idioma.
Senal: token que abre parrafos cortos, seguido de un ordinal, repetido en el documento."""
import glob,os,re,json,collections,statistics
from lxml import etree
D='/Users/neli/.claude/jobs/5bf7ddf4/tmp/dryrun'
ORD=re.compile(r'\d')                    # un digito: neutral en cualquier idioma
def infer(paras):
    """paras: lista de (clase, texto). Devuelve el conjunto de tokens inferidos."""
    if len(paras)<8: return set()
    lens=[len(t) for _,t in paras if t]
    if not lens: return set()
    med=statistics.median(lens)
    first=collections.Counter()
    follow=collections.defaultdict(collections.Counter)
    short=collections.defaultdict(list)
    for _,t in paras:
        w=t.split()
        if not w: continue
        tok=w[0].strip('.:,;()[]«»')
        if not tok or len(tok)>24: continue
        first[tok]+=1
        follow[tok][w[1].strip('.:,;()[]«»') if len(w)>1 else '']+=1
        short[tok].append(len(t))
    out=set()
    for tok,n in first.items():
        if n<3: continue
        # (a) el token va seguido de algo con un digito, o de un conjunto cerrado pequeño
        f=follow[tok]; tot=sum(f.values())
        numeric=sum(v for k,v in f.items() if ORD.search(k))
        closed=len([k for k in f if k])<=12 and tot>=3
        if not (numeric/max(1,tot)>=0.5 or closed): continue
        # (b) los parrafos que abre son cortos frente a la mediana del documento
        if statistics.median(short[tok]) > max(60, med*0.6): continue
        # (c) no puede ser la mayoria del documento (seria el cuerpo, no encabezados)
        if n > len(paras)*0.5: continue
        out.add(tok)
    return out

rows=[]
for p in sorted(glob.glob(f'{D}/raw/*.xml')):
    bid=os.path.basename(p)[:-4]
    root=etree.fromstring(open(p,'rb').read())
    t=root.find('texto')
    if t is None: continue
    paras=[((e.get('class') or ''), ' '.join(e.itertext()).strip()) for e in t.iter('p')]
    paras=[(c,x) for c,x in paras if x]
    if not paras: continue
    marked=sum(1 for c,_ in paras if c=='articulo')
    toks=infer(paras)
    # cuantos parrafos recupera el token inferido
    rec=sum(1 for _,x in paras if x.split() and x.split()[0].strip('.:,;()[]«»') in toks)
    rows.append(dict(id=bid,year=int(bid.split('-')[2]),n=len(paras),marked=marked,
                     toks=sorted(toks),recovered=rec))
json.dump(rows,open(f'{D}/infer.json','w'),indent=1)
print(f'{len(rows)} documentos')
