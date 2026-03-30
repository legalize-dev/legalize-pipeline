"""Investigate BOE consolidated legislation catalog.

Paginates the full /legislacion-consolidada endpoint and reports:
- Total norms
- Breakdown by ambito (state vs autonomic)
- Breakdown by ELI jurisdiction
- Breakdown by rango
- Breakdown by estado (vigente/derogada)
- Date range
"""

import json
import requests
from collections import Counter

BASE_URL = "https://www.boe.es/datosabiertos/api/legislacion-consolidada"
BATCH = 1000


def fetch_all() -> list[dict]:
    """Paginate the full catalog."""
    all_items: list[dict] = []
    offset = 0

    while True:
        print(f"  Fetching offset {offset}...")
        resp = requests.get(
            BASE_URL,
            headers={"Accept": "application/json"},
            params={"limit": BATCH, "offset": offset},
            timeout=60,
        )
        resp.raise_for_status()
        items = resp.json().get("data", [])
        if not items:
            break
        all_items.extend(items)
        offset += BATCH

    return all_items


def extract_jurisdiction(item: dict) -> str:
    """Extract ELI jurisdiction from url_eli or bulletin prefix."""
    url_eli = item.get("url_eli", "")
    if url_eli:
        # e.g. https://www.boe.es/eli/es-pv/l/2019/12/20/11
        parts = url_eli.split("/eli/")
        if len(parts) > 1:
            jurisdiction = parts[1].split("/")[0]
            return jurisdiction

    # Fallback: infer from bulletin prefix
    identificador = item.get("identificador", "")
    prefix_map = {
        "BOA": "es-ar", "BOJA": "es-an", "DOGV": "es-vc", "BORM": "es-mc",
        "BOCL": "es-cl", "DOGC": "es-ct", "BOC": "es-cn", "BOIB": "es-ib",
        "BON": "es-nc", "DOG": "es-ga", "DOCM": "es-cm", "BOPV": "es-pv",
        "BOCT": "es-cb", "DOE": "es-ex", "BOCM": "es-md",
    }
    for prefix, juris in sorted(prefix_map.items(), key=lambda x: -len(x[0])):
        if identificador.startswith(prefix):
            return juris

    return "es"  # default to state-level


def main():
    print("Fetching full BOE consolidated legislation catalog...\n")
    items = fetch_all()
    print(f"\n{'='*60}")
    print(f"TOTAL NORMS: {len(items)}")
    print(f"{'='*60}\n")

    # By ambito
    ambito_counter = Counter()
    for item in items:
        ambito = item.get("ambito", {})
        code = ambito.get("codigo", "?")
        desc = ambito.get("descripcion", "unknown")
        ambito_counter[f"{code} ({desc})"] += 1

    print("BY AMBITO (scope):")
    for k, v in ambito_counter.most_common():
        print(f"  {k}: {v}")

    # By jurisdiction
    juris_counter = Counter()
    no_eli = []
    for item in items:
        j = extract_jurisdiction(item)
        juris_counter[j] += 1
        if not item.get("url_eli"):
            no_eli.append(item.get("identificador", "?"))

    print(f"\nBY ELI JURISDICTION ({len(juris_counter)} jurisdictions):")
    for k, v in juris_counter.most_common():
        print(f"  {k}: {v}")

    print(f"\nNorms WITHOUT url_eli: {len(no_eli)}")
    if no_eli[:5]:
        print(f"  Examples: {no_eli[:5]}")

    # By rango
    rango_counter = Counter()
    for item in items:
        rango = item.get("rango", {}).get("descripcion", "unknown")
        rango_counter[rango] += 1

    print(f"\nBY RANGO (rank):")
    for k, v in rango_counter.most_common():
        print(f"  {k}: {v}")

    # By estado
    estado_counter = Counter()
    for item in items:
        estado = item.get("estado_consolidacion", {}).get("descripcion", "unknown")
        estado_counter[estado] += 1

    print(f"\nBY ESTADO:")
    for k, v in estado_counter.most_common():
        print(f"  {k}: {v}")

    # State-level only (what legalize currently gets)
    state_only = [i for i in items if i.get("ambito", {}).get("codigo") == "1"]
    print(f"\nSTATE-LEVEL ONLY (ambito.codigo=='1'): {len(state_only)}")
    print(f"AUTONOMIC (missing from legalize): {len(items) - len(state_only)}")

    # Save raw data for further analysis
    output_path = "scripts/catalog_dump.json"
    with open(output_path, "w") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"\nRaw data saved to {output_path}")


if __name__ == "__main__":
    main()
