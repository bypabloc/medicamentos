"""Descarga las fuentes abiertas a source/ (no se versiona).

Uso: python scripts/fetch.py [invima] [cima] [wikidata]   (sin argumentos: todas)
"""

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "source"
UA = "medicamentos-catalog-builder/1.0 (+https://github.com/bypabloc/medicamentos)"

INVIMA_URL = "https://www.datos.gov.co/resource/i7cb-raxc.json"
INVIMA_FIELDS = (
    "expediente,producto,titular,registrosanitario,fechavencimiento,"
    "consecutivocum,descripcioncomercial,estadocum,muestramedica,atc,"
    "viaadministracion,principioactivo,cantidad,unidadmedida,"
    "unidadreferencia,formafarmaceutica,modalidad"
)
CIMA_URL = "https://cima.aemps.es/cima/rest/medicamentos"
WIKIDATA_URL = "https://query.wikidata.org/sparql"
WIKIDATA_QUERY = """
SELECT ?item ?atc ?es ?en
  (GROUP_CONCAT(DISTINCT ?alias; separator="|") AS ?aliases)
WHERE {
  ?item wdt:P267 ?atc .
  OPTIONAL { ?item rdfs:label ?es FILTER(lang(?es) = "es") }
  OPTIONAL { ?item rdfs:label ?en FILTER(lang(?en) = "en") }
  OPTIONAL { ?item skos:altLabel ?alias FILTER(lang(?alias) = "es") }
}
GROUP BY ?item ?atc ?es ?en
"""


def get(url: str, params: dict[str, str], accept: str = "application/json") -> bytes:
    """GET con reintentos simples ante errores de red o 5xx."""
    full = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(full, headers={"User-Agent": UA, "Accept": accept})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except Exception as error:  # noqa: BLE001
            if attempt == 4:
                raise
            print(f"  reintento {attempt + 1}: {error}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_invima() -> None:
    """CUM vigentes de INVIMA con estado activo (CC BY-SA 4.0)."""
    rows: list[dict] = []
    while True:
        page = json.loads(get(INVIMA_URL, {
            "$select": INVIMA_FIELDS,
            "$where": "estadocum='Activo'",
            "$order": "expediente,consecutivocum,principioactivo",
            "$limit": "50000",
            "$offset": str(len(rows)),
        }))
        rows.extend(page)
        print(f"invima: {len(rows)}", file=sys.stderr)
        if len(page) < 50000:
            break
    (SOURCE / "invima-cum.json").write_text(json.dumps(rows, ensure_ascii=False))


def fetch_cima() -> None:
    """Medicamentos comercializados en España según CIMA (AEMPS)."""
    rows: list[dict] = []
    page_number = 1
    while True:
        page = json.loads(get(CIMA_URL, {"comerc": "1", "pagesize": "200", "pagina": str(page_number)}))
        rows.extend(page["resultados"])
        print(f"cima: {len(rows)}/{page['totalFilas']}", file=sys.stderr)
        if len(rows) >= page["totalFilas"] or not page["resultados"]:
            break
        page_number += 1
        time.sleep(0.3)
    (SOURCE / "cima.json").write_text(json.dumps(rows, ensure_ascii=False))


def fetch_wikidata() -> None:
    """Sustancias con código ATC en Wikidata (CC0)."""
    body = get(WIKIDATA_URL, {"query": WIKIDATA_QUERY}, accept="text/csv")
    (SOURCE / "wikidata-atc.csv").write_bytes(body)
    with (SOURCE / "wikidata-atc.csv").open(encoding="utf-8") as handle:
        print(f"wikidata: {sum(1 for _ in csv.DictReader(handle))}", file=sys.stderr)


FETCHERS = {"invima": fetch_invima, "cima": fetch_cima, "wikidata": fetch_wikidata}

if __name__ == "__main__":
    SOURCE.mkdir(exist_ok=True)
    for name in sys.argv[1:] or list(FETCHERS):
        FETCHERS[name]()
