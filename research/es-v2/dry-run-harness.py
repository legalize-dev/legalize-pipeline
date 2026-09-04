"""Dry-run del diseno propuesto sobre la muestra. Solo lectura, cero HTTP."""
import glob,json,os,re,sys,collections
sys.path.insert(0,'/Users/neli/projects/legalize/engine/src')
from lxml import etree
from legalize.transformer.xml_parser import parse_text_xml, _parse_p, _table_paragraph, _parse_blockquote, _image_paragraph, _image_paragraph
from legalize.transformer.markdown import render_paragraphs

D='/Users/neli/.claude/jobs/5bf7ddf4/tmp/dryrun'
cat=set()
for f in ('/tmp/cat0.json','/tmp/cat1.json'):
    cat |= {i['identificador'] for i in json.load(open(f))['data']}

DROP={'1590','1240','63','1250'}
rows=[]
for p in sorted(glob.glob(f'{D}/raw/*.xml')):
    bid=os.path.basename(p)[:-4]
    root=etree.fromstring(open(p,'rb').read())
    m=root.find('metadatos')
    g=lambda t:(m.findtext(t) or '').strip() if m is not None else ''
    rango_cod=(m.find('rango').get('codigo','') if m is not None and m.find('rango') is not None else '')
    ec=m.find('estado_consolidacion') if m is not None else None
    ec_cod=ec.get('codigo','') if ec is not None else ''
    # PUERTA texto: hijo DIRECTO de <documento>, no .//texto
    texto=root.find('texto')
    chars=len(' '.join(texto.itertext()).split()) if texto is not None else 0
    nchar=len(''.join(texto.itertext())) if texto is not None else 0
    palabras={(a.findtext('palabra') or '').strip()
              for a in root.iterfind('analisis/referencias/anteriores/anterior')}
    try: pi,pf=int(g('pagina_inicial')),int(g('pagina_final'))
    except ValueError: pi=pf=0
    pages=max(1,pf-pi+1) if pi else 0
    nimg=len(root.findall('.//texto//img'))
    # despacho REAL del engine sobre el cuerpo
    heads=arts=looks=upper=0; md=''
    if texto is not None and nchar:
        paras=[]
        for el in texto:
            if el.tag=='p':
                q=_parse_p(el);  paras.append(q) if q is not None else None
            elif el.tag=='table':
                q=_table_paragraph(el);  paras.append(q) if q is not None else None
            elif el.tag=='img':
                q=_image_paragraph(el);  paras.append(q) if q is not None else None
            elif el.tag=='blockquote':
                paras.extend(_parse_blockquote(el) or [])
        md=render_paragraphs(tuple(paras)) if paras else ''
        heads=len(re.findall(r'(?m)^#{1,6} ',md))
        arts=len(texto.findall('.//p[@class="articulo"]'))
        # El texto PARECE articulado? (parrafos que abren con Articulo/Art./Disposicion)
        looks=sum(1 for t in (' '.join(e.itertext()).strip() for e in texto.iter('p'))
                  if re.match(r'^(Art[íi]culo|Art\.|ARTICULO|ART[ÍI]CULO|Disposici[óo]n)\b', t))
        # clases en mayusculas (familia heredada)
        upper=sum(1 for e in texto.iter('p')
                  if (e.get('class') or '').strip() and (e.get('class') or '')==(e.get('class') or '').upper()
                  and re.search(r'[A-Z]{3}', e.get('class') or ''))
    rows.append(dict(id=bid,year=int(bid.split('-')[2]),rango=rango_cod,ec=ec_cod,
        in_cat=bid in cat, nchar=nchar, pages=pages, nimg=nimg,
        dens=round(nchar/pages,1) if pages else None,
        heads=heads, arts=arts, looks=looks, upper=upper, corr=any(re.match(r'^(CORRECCIÓN|CORRIGE)',w) for w in palabras),
        sentinels=len(re.findall(r'\[(precepto|encabezado|ignorar|firma)\]',md)),
        mdlen=len(md)))
json.dump(rows,open(f'{D}/rows.json','w'),indent=1)
print(f'analizados: {len(rows)}')
