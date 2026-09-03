#!/usr/bin/env python3
"""CELLAR SPARQL runner via curl: sq.py <file.rq> [--json out.json]"""
import sys, json, subprocess, time, tempfile, os

ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
UA = "legalize-bot/1.0 (+https://github.com/legalize-dev/legalize)"

def run(query, timeout=600):
    with tempfile.NamedTemporaryFile("w", suffix=".rq", delete=False, encoding="utf-8") as f:
        f.write(query); qf = f.name
    out = tempfile.NamedTemporaryFile(delete=False).name
    t0 = time.time()
    r = subprocess.run(
        ["curl", "-s", "-A", UA, "-m", str(timeout), "-G", ENDPOINT,
         "--data-urlencode", f"query@{qf}",
         "--data-urlencode", "format=application/sparql-results+json",
         "-o", out, "-w", "%{http_code}"],
        capture_output=True, text=True,
    )
    el = time.time() - t0
    code = r.stdout.strip()
    body = open(out, "rb").read()
    os.unlink(qf); os.unlink(out)
    if code != "200":
        raise RuntimeError(f"http={code} body={body[:300]!r}")
    d = json.loads(body)
    return d["head"]["vars"], d["results"]["bindings"], el

if __name__ == "__main__":
    q = open(sys.argv[1], encoding="utf-8").read()
    try:
        vars_, rows, el = run(q)
    except Exception as e:
        print(f"!! FAILED: {type(e).__name__}: {str(e)[:400]}"); sys.exit(1)
    print(f"# {len(rows)} rows in {el:.1f}s")
    print("\t".join(vars_))
    for b in rows:
        print("\t".join(b.get(v, {}).get("value", "").rsplit("/", 1)[-1] for v in vars_))
