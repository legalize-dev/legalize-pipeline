"""Spike 2: the amendment timeline of one consolidated diploma.

Answers the cost question: how many distinct versions does a big code have, and
does the timeline say exactly WHICH fragments each amendment touched?
"""
import json, re, sys, time, requests

BASE = "https://diariodarepublica.pt/dr"
UA = "legalize-bot/1.0 (+https://github.com/legalize-dev/legalize-pipeline)"
CALL_RE = re.compile(r'callDataAction\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"')
JS = f"{BASE}/scripts/dr.LegislacaoConsolidada.AlteracoesTimelineByDiplomaLegisId.mvc.js"

s = requests.Session(); s.headers["User-Agent"] = UA
csrf = re.search(r'AnonymousCSRFToken\s*=\s*"([^"]+)"', s.get(f"{BASE}/scripts/OutSystems.js").text).group(1)
mv = s.get(f"{BASE}/moduleservices/moduleversioninfo").json()["versionToken"]
actions = {a: (p, v) for a, p, v in CALL_RE.findall(s.get(JS).text)}
path, api = actions["DataActionGetConsolidacaoByDiplomaFrag"]

legis_id, frag_id = sys.argv[1], sys.argv[2]
body = {
    "versionInfo": {"moduleVersion": mv, "apiVersion": api},
    # the BLOCK's action must be posted under the SCREEN's viewName
    "viewName": "LegislacaoConsolidada.LegCons_Detalhe",
    "screenData": {"variables": {
        "DiplomaLegisId": legis_id, "_diplomaLegisIdInDataFetchStatus": 1,
        "DiplomaFragId": frag_id, "_diplomaFragIdInDataFetchStatus": 1,
        "Data": "2099-12-31", "_dataInDataFetchStatus": 1,
        "ModificanteFragId": "0", "_modificanteFragIdInDataFetchStatus": 1,
        "Modificacoes": {"List": [], "EmptyListItem": {}},
        "IsRendered": True, "IsRenderingFragmentoVersao": False,
        "IsLoadingChangesForNewDate": False, "ShowAllAlteracoes": True,
        "SelectedDiploLegisId": "0", "SelectedDataValidacao": "1900-01-01",
        "SelectedModificanteFragId": "0", "ModificanteFragIdAux": "",
        "DataAux": "2099-12-31",
    }},
    "clientVariables": {},
}
r = s.post(f"{BASE}/{path.lstrip('/')}", json=body,
           headers={"X-CSRFToken": csrf, "Content-Type": "application/json; charset=UTF-8"}, timeout=120)
d = r.json()
if d.get("exception"):
    raise SystemExit(d["exception"])
lst = d["data"]["ModificacoesList"]["List"]
print("counter:", d["data"].get("ModificacoesCounter"), "entries:", len(lst))
dates, frag_versions = set(), set()
for m in lst:
    for mod in m["ModificacaoList"]["List"]:
        dates.add(mod["DataEntradaVigor"][:10])
        frag_versions.add(mod["FragmentoVersaoDestinoId"])
print("distinct entry-into-force dates:", len(dates))
print("distinct target fragment versions:", len(frag_versions))
print("date range:", min(dates) if dates else None, "→", max(dates) if dates else None)
print("\nfirst entry:\n", json.dumps(lst[0], indent=1, ensure_ascii=False)[:1800] if lst else "none")
json.dump({"entries": len(lst), "dates": sorted(dates), "frag_versions": len(frag_versions),
           "sample": lst[:2]}, open(sys.argv[3], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
