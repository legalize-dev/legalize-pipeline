import sys, io
sys.path.insert(0, "src")
from legalize.fetcher.eu.parser import EURLexTextParser

R = "samples"  # ejecutar desde engine/research/eu-v2/ con PYTHONPATH=../../src
cases = [
    ("32016R0679", "RGPD (reglamento, YA en el corpus)"),
    ("32014L0024", "Directiva contratacion (NO existe hoy)"),
    ("31968R1017", "Reglamento 1968 (historico, derogado)"),
    ("31993D0465", "Decision 1993 (NO existe hoy)"),
    ("11957E000",  "Tratado CEE (NO existe hoy)"),
    ("32019R0947", "Reglamento drones (tablas/anexos)"),
]
p = EURLexTextParser()
print(f"{'CELEX':<12} {'bloques':>8} {'parrafos':>9} {'chars':>10}  caso")
for celex, label in cases:
    data = open(f"{R}/s-{celex}.html", "rb").read()
    try:
        blocks = p.parse_text(data)
    except Exception as e:
        print(f"{celex:<12} {'EXCEPCION':>8}  {type(e).__name__}: {str(e)[:60]}  {label}")
        continue
    npar = sum(len(v.paragraphs) for b in blocks for v in b.versions)
    nchars = sum(len(getattr(par, 'text', '') or '') for b in blocks for v in b.versions for par in v.paragraphs)
    print(f"{celex:<12} {len(blocks):>8} {npar:>9} {nchars:>10,}  {label}")
