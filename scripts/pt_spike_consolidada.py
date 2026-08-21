"""Spike: fetch DRE consolidated legislation at an arbitrary date (point-in-time).

Proves the version-history gate for Portugal: the same article at two dates comes
back as two distinct FragmentoVersao records with their own DataEntradaVigor.
"""
from __future__ import annotations

import json
import re
import sys
import time

import requests

BASE = "https://diariodarepublica.pt/dr"
UA = "legalize-bot/1.0 (+https://github.com/legalize-dev/legalize-pipeline)"

SCREEN_JS = f"{BASE}/scripts/dr.LegislacaoConsolidada.LegCons_Detalhe.mvc.js"
CALL_RE = re.compile(r'callDataAction\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"')


class Dre:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        js = self._get(f"{BASE}/scripts/OutSystems.js").text
        m = re.search(r'AnonymousCSRFToken\s*=\s*"([^"]+)"', js)
        if not m:
            raise SystemExit("no CSRF token")
        self.csrf = m.group(1)
        self.module_version = self._get(f"{BASE}/moduleservices/moduleversioninfo").json()["versionToken"]
        self.actions = {
            a: (p, v) for a, p, v in CALL_RE.findall(self._get(SCREEN_JS).text)
        }

    def _get(self, url):
        time.sleep(0.5)
        r = self.s.get(url, timeout=30)
        r.raise_for_status()
        return r

    def call(self, action: str, variables: dict) -> dict:
        path, api_version = self.actions[action]
        body = {
            "versionInfo": {"moduleVersion": self.module_version, "apiVersion": api_version},
            "viewName": "LegislacaoConsolidada.LegCons_Detalhe",
            "screenData": {"variables": variables},
            "clientVariables": {},
        }
        time.sleep(0.5)
        r = self.s.post(
            f"{BASE}/{path.lstrip('/')}",
            json=body,
            headers={"X-CSRFToken": self.csrf, "Content-Type": "application/json; charset=UTF-8"},
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("exception"):
            raise SystemExit(f"{action}: {data['exception']}")
        return data["data"]


def screen_vars(tipo, key, ano, diploma_legis_id, diploma_frag_id, data_sel, header=None) -> dict:
    """The LegCons_Detalhe screen state, trimmed to what the server actually reads."""
    return {
        "HasJurisprudenciaAssociadaVar": True,
        "DiplomaLegisId": diploma_legis_id,
        "IsRended": True,
        "ShowFragAlteracoes": False,
        "ShowFragDiferencas": False,
        "DiplomaFragId": diploma_frag_id,
        "DataSelecionada": data_sel,
        "FragmentoVersaoId": "0",
        "ELI_HTML": "",
        "hasFragIdLink": False,
        "Ano": ano,
        "DataAux": data_sel,
        "Mensagem": {"Texto": "", "IsActive": False, "AlertId": ""},
        "TituloComFragmento": "",
        "Description": "",
        "ShowRevogados": True,
        "LoadFiltro": False,
        "FragVersaoIndice": "0",
        "ShowZoom": False,
        "CurrentZoom": "1",
        "IsPageTracked": True,
        "FragmentoVersaoIdAux": "0",
        "IndexLinhaToScrollId": "",
        "IsShowConteudoRelacionado": True,
        "ShowZoomButtons": True,
        "TituloAux": "",
        "TipoConteudosBools": {
            "AcordaosSTA": False, "Atos1": False, "Atos2": False, "AtosSocietarios": False,
            "DGAP": False, "DGODOUT": False, "DiarioRepublica": False, "Jurisprudencia": False,
            "Legacor": False, "REGTRAB": False,
        },
        "EmissorVar": "",
        "PesquisaAvancada_Struct": {
            "tipoConteudo": {"List": [], "EmptyListItem": ""},
            "serie": {"List": [], "EmptyListItem": ""},
            "numero": "", "ano": "0", "suplemento": "0", "dataPublicacao": "",
            "dataPublicacaoDe": "1900-01-01", "dataPublicacaoAte": "1900-01-01",
            "parte": "", "apendice": "", "fasciculo": "",
            "tipo": {"List": [], "EmptyListItem": ""},
            "emissor": {"List": [], "EmptyListItem": ""},
            "texto": "", "sumario": "",
            "entidadeProponente": {"List": [], "EmptyListItem": ""},
            "numeroDR": "", "paginaInicial": "0", "paginaFinal": "0",
            "dataAssinatura": "", "dataDistribuicao": "",
            "entidadePrincipal": {"List": [], "EmptyListItem": ""},
            "entidadeEmitente": {"List": [], "EmptyListItem": ""},
            "docType": "", "proferido": "", "processo": "", "assunto": "",
            "recorrente": "", "recorrido": "", "relator": "", "empresa": "",
            "concelho": "", "nif": "", "anuncio": "", "numeroDoc": "",
            "DataAssinaturaDe": "1900-01-01", "DataAssinaturaAte": "1900-01-01",
            "DataDistribuicaoDe": "1900-01-01", "DataDistribuicaoAte": "1900-01-01",
            "semestre": "", "IsLegConsolidadaSelected": False, "IsFromData": False,
            "DescritorList": {"List": [], "EmptyListItem": ""},
        },
        "IsPrint": False,
        "IsLoadingPDFConsolidacao": False,
        "Comes": "",
        "WithConteudoRevogado": True,
        "ModificanteFragId": "0",
        "IndiceList": {"List": [], "EmptyListItem": {}},
        "IsFiltrar": False,
        "WithAlteracoes": False,
        "SumarioAux": "",
        "Tipo": tipo,
        "_tipoInDataFetchStatus": 1,
        "Key": key,
        "_keyInDataFetchStatus": 1,
        # DataActionGetData reads the header action's own output back off the screen.
        "GetDiplomaFragByIdAndApplicationSetting": header or {},
    }


def main() -> None:
    tipo, ano, frag_id = "decreto-lei", 1966, "34509075"   # Código Civil
    key = f"{ano}-{frag_id}"
    dre = Dre()
    print("actions:", json.dumps({a: v for a, (_, v) in dre.actions.items()}, indent=1))

    # 1. resolve the diploma header (gives DiplomaLegisId + ELI)
    head = dre.call(
        "DataActionGetDiplomaFragByIdAndApplicationSetting",
        screen_vars(tipo, key, ano, "0", frag_id, "2026-08-21"),
    )
    det = head["ConsolidadaConteudoDetalhe"]
    legis_id = det["DiplomaLegis"]["Id"]
    print("\nDiplomaLegisId:", legis_id)
    print("title:", det["DiplomaFrag"]["FormattedTitle"])
    print("ELI:", det["DiplomaFrag"]["ELI"])

    # 2. two point-in-time snapshots
    snaps = {}
    for when in ("2000-01-01", "2026-06-23"):
        data = dre.call(
            "DataActionGetData",
            screen_vars(tipo, key, ano, legis_id, frag_id, when, header=head),
        )
        snaps[when] = data["LegConsBase"]["List"]
        print(f"{when}: {len(snaps[when])} fragments")

    def art(items, name):
        for it in items:
            if it["ConsolidacaoFragmento"]["Name"] == name:
                fv = it["FragmentoVersao"]
                txt = re.sub(r"<[^>]+>", " ", fv["Texto"])
                return {
                    "fragmento_versao_id": fv["Id"],
                    "data_entrada_vigor": fv["DataEntradaVigor"],
                    "data_versao": fv["DataVersao"],
                    "epigrafe": fv["Epigrafe"],
                    "texto": re.sub(r"\s+", " ", txt).strip()[:200],
                }
        return None

    out = {
        "diploma": det["DiplomaFrag"]["FormattedTitle"],
        "eli": det["DiplomaFrag"]["ELI"],
        "diploma_legis_id": legis_id,
        "diploma_frag_id": frag_id,
        "snapshots": {d: {"fragments": len(v), "art_1601": art(v, "Artigo 1601.º")} for d, v in snaps.items()},
    }
    print("\n" + json.dumps(out, indent=2, ensure_ascii=False))
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
