"""Genera el catálogo unificado de medicamentos y principios activos.

Entradas: fuentes/arcsa-*.xlsx (versionado) y source/ (scripts/fetch.py).
Salidas: medicamentos-{ec,co,es}.csv, principios-activos.csv, rechazados.csv y reporte.json.

Uso: uv run --with openpyxl python build.py
"""

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
ARCSA = sorted((ROOT / "fuentes").glob("arcsa-*.xlsx"))[-1]

PRODUCT_COLUMNS = [
    "country", "id", "registration", "trade_name", "brand", "kind", "ingredients",
    "ingredient_ids", "strength", "dosage_form", "dosage_form_raw", "routes", "route_raw",
    "presentation", "holder", "holder_country", "sale_condition", "in_cnmb", "atc_code",
    "valid_until",
]
INGREDIENT_COLUMNS = [
    "id", "name", "atc_codes", "synonyms", "wikidata_id", "products_ec", "products_co",
    "products_es", "sources", "quality",
]

# Mismos valores que DosageForm y AdministrationRoute de la receta de Klinikae.
FORM_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("injectable", ("inyect", "infusion", "para inyeccion", "liofilizado", "perfusion", "parenteral")),
    ("inhaler", ("inhala", "nebuliz")),
    ("drops", ("gota", "oftalm", "otica", "colirio")),
    ("pessary", ("ovulo", "vaginal")),
    ("suppository", ("supositorio",)),
    ("patch", ("parche", "transderm")),
    ("syrup", ("jarabe", "elixir")),
    ("suspension", ("suspension",)),
    ("solution", ("solucion", "emulsion", "locion", "spray", "aerosol")),
    ("cream", ("crema",)),
    ("ointment", ("unguento", "pomada")),
    ("gel", ("gel",)),
    ("capsule", ("capsula",)),
    ("tablet", ("tableta", "comprimido", "gragea", "pastilla", "grageas")),
    ("powder", ("polvo", "granulado", "sobre")),
]
ROUTE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("sublingual", ("sublingual",)),
    ("ophthalmic", ("oftalm", "ocular", "conjuntival")),
    ("otic", ("otic", "auricular")),
    ("nasal", ("nasal",)),
    ("inhalation", ("inhala", "respirator", "pulmonar", "endotraqueal")),
    ("intramuscular", ("intramuscular",)),
    ("intravenous", ("intravenos", "endovenos", "infusion", "intravascular")),
    ("subcutaneous", ("subcutane",)),
    ("rectal", ("rectal",)),
    ("vaginal", ("vaginal",)),
    ("topical", ("topic", "cutane", "derm", "bucal", "oromucos", "gingival")),
    ("oral", ("oral", "enteral")),
]
SALE = {"Bajo Receta Médica": "prescription", "Venta Libre (OTC)": "otc",
        "Receta Especial / Controlada": "controlled"}
ATC_RE = re.compile(r"^[A-Z]\d\d[A-Z]{2}\d\d")
JUNK_RE = re.compile(r"^[\d\s.,%´'()/-]*$")
STRENGTH_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mg|mcg|µg|ug|g|ml|ui|u\.i\.|meq|mmol|%)(?![a-z])"
    r"(?:\s*/\s*(\d+(?:[.,]\d+)?)?\s*(ml|g|dosis|h)(?![a-z]))?",
    re.IGNORECASE,
)

rejects: list[dict[str, str]] = []
unmapped: dict[str, Counter[str]] = {"dosage_form": Counter(), "route": Counter()}


def norm(text: str | None) -> str:
    """Minúsculas, sin tildes ni espacios repetidos: la clave de comparación."""
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", plain.replace("®", " ").replace("™", " ")).strip().lower()


def clean(text: object) -> str:
    """Texto de salida en una sola línea, sin `=`, `+`, `-` ni `@` al inicio.

    Ninguna celda legítima empieza así (las fuentes usan `-` como «vacío»), y quitarlos evita que
    una hoja de cálculo interprete la celda como fórmula.
    """
    return re.sub(r"\s+", " ", str(text or "")).strip().lstrip("=+-@ ").strip()


def dosage_form(raw: str) -> str:
    """Forma de Klinikae por palabra clave; `other` si no se reconoce."""
    key = norm(raw)
    for value, words in FORM_RULES:
        if any(word in key for word in words):
            return value
    if key:
        unmapped["dosage_form"][key] += 1
    return "other"


def routes(raw: str) -> str:
    """Vías de Klinikae separadas por `|`, en el orden de ROUTE_RULES."""
    found = [value for value, words in ROUTE_RULES if any(w in norm(raw) for w in words)]
    if raw and not found:
        unmapped["route"][norm(raw)] += 1
    return "|".join(found)


def strength(raw: str, count: int) -> str:
    """Concentraciones legibles (`500 mg + 65 mg`); vacío si no hay ninguna."""
    parts = []
    for amount, unit, per_amount, per_unit in STRENGTH_RE.findall(raw or ""):
        unit = {"ug": "mcg", "µg": "mcg", "u.i.": "UI", "ui": "UI", "ml": "mL"}.get(unit.lower(), unit.lower())
        text = f"{amount} {unit}"
        if per_unit:
            text += f"/{per_amount + ' ' if per_amount else ''}{'mL' if per_unit.lower() == 'ml' else per_unit.lower()}"
        parts.append(text)
    return " + ".join(parts[: max(count, 1)])


EQUIVALENT_RE = re.compile(
    r"\b(?:equival\w*|equivil\w*|equiv|eq|correspond\w*|contiene[n]?)\.?(?:\s+(?:a|al|de)\b)?", re.I
)
CUT_RE = re.compile(r"(?<=\w)\s+\b(?:incluyendo|incuyendo|sobredosis|sobrecarga|expresad[oa])\b.*$", re.I)
WRAPPER_RE = re.compile(
    r"\b(?:exceso|pellets|n[uú]cleo|dc|de compresi[oó]n directa|compresi[oó]n directa|microgr[aá]nulos"
    r"|precomprimido|principio activo|cubierta|compactad[oa]|polvo granular|granular|polvo"
    r"|con recubrimiento ent[eé]rico|recubiert[oa]s?|gastrorresistentes?)\b", re.I,
)
UNIT_RE = re.compile(r"(?<![a-záéíóúñ])(?:mg|mcg|µg|ug|g|ml|ui|mui|u|m|meq|mmol|kui|c/u)(?![a-záéíóúñ])\.?", re.I)
NOISE_RE = re.compile(
    r"\([^)]*\)|\[[^]]*\]|\d+(?:[.,]\d+)?\s*(?:mg|mcg|µg|ug|g|ml|ui|mui|u|meq|mmol|kui|%)\b\.?"
    r"|\bu\.?s\.?p\.?|\b(?:bp|ph\.?\s*eur|fda|cpp|nf|ep|jp|dci|cas|micronizad[oa]|en polvo|base|esteril"
    r"|granulado|liofilizad[oa]|tamponad[oa]|del|al)\b|[*#?¹²³®™:;@\"“”()\[\]%]|\d+",
    re.I,
)
LEADING_RE = re.compile(r"^(?:(?:de|del|la|el|los|las|y|con|en forma de|como)\s+)+", re.I)
BAD_WORDS = ("cada", "contiene", "registro", "parte", "tableta", "capsula", "comprimido", "nucleo",
             "recubiert", "excipiente", "csp", "vehiculo", "frasco", "ampolla", "reconstituir", "equivalente",
             "concentracion", "formula", "nombre", "comercial", "componentes")
SALT_WORDS = {
    "clorhidrato", "hidrocloruro", "diclorhidrato", "bromhidrato", "sodico", "sodica", "sodio", "potasico",
    "potasica", "potasio", "calcico", "calcica", "magnesico", "besilato", "maleato", "mesilato", "fumarato",
    "succinato", "tartrato", "citrato", "sulfato", "fosfato", "acetato", "monohidrato", "dihidrato",
    "trihidrato", "hemihidrato", "sesquihidrato", "anhidro", "anhidra", "hidratado", "hidratada", "disodico",
    "disodica", "dipropionato", "propionato", "valerato", "furoato", "hiclato", "trometamol", "de", "del",
}


def clean_ingredient(raw: str) -> str:
    """Nombre del principio activo sin cantidades ni texto de fórmula; vacío si no lo parece."""
    text = re.sub(r"(?i)(\S)(equivalente)", r"\1 \2", clean(raw))
    text = WRAPPER_RE.sub(" ", text)
    parts = EQUIVALENT_RE.split(text)
    text = parts[-1] if len(parts) > 1 and len(norm(parts[-1])) >= 3 else parts[0]
    text = UNIT_RE.sub(" ", NOISE_RE.sub(" ", CUT_RE.sub("", text)))
    text = re.sub(r"\s+", " ", text).strip(" .,-/'´")
    text = LEADING_RE.sub("", text).strip(" .,-/'´")
    key = norm(text)
    words = key.split()
    if len(re.sub(r"[^a-z]", "", key)) < 3 or len(words) > 6 or any(w in BAD_WORDS for w in words):
        return ""
    return text


def base_key(name: str) -> str:
    """Clave sin sales ni hidratos, para unir la sal con su sustancia base."""
    return " ".join(w for w in norm(name).split() if w not in SALT_WORDS)


def split_ingredients(raw: str, separators: str = r"\+") -> list[str]:
    """Componentes limpios de una fórmula, sin restos numéricos ni repetidos."""
    seen: dict[str, str] = {}
    for part in re.split(separators, raw or ""):
        name = clean_ingredient(part)
        if name and not JUNK_RE.match(name):
            seen.setdefault(base_key(name) or norm(name), name)
    return list(seen.values())


def reject(country: str, row_id: str, reason: str, name: str) -> None:
    rejects.append({"country": country, "id": row_id, "reason": reason, "trade_name": name})


def iso(value: object, fmt: str) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    try:
        return datetime.strptime(str(value)[:10], fmt).date().isoformat()
    except ValueError:
        return ""


class Dictionary:
    """Principios activos: une los nombres de todas las fuentes por clave normalizada."""

    def __init__(self) -> None:
        self.entries: dict[str, dict] = {}
        self.alias: dict[str, str] = {}

    def add_wikidata(self, path: Path) -> None:
        items: dict[str, dict] = {}
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                qid = row["item"].rsplit("/", 1)[-1]
                item = items.setdefault(qid, {"atc": set(), "es": row["es"], "en": row["en"], "aliases": set()})
                item["atc"].add(row["atc"])
                item["aliases"].update(a for a in row["aliases"].split("|") if a)
        for qid, item in items.items():
            name = item["es"] or item["en"]
            if not name or re.match(r"^Q\d+$", name) or self._find(name):
                continue
            entry = self._entry(base_key(name) or norm(name), name.lower(), "wikidata")
            entry["wikidata_id"] = qid
            entry["atc"].update(item["atc"])
            for alias in {item["en"], *item["aliases"]} - {""}:
                entry["synonyms"].add(alias.lower())
                self._index(alias, entry["key"])

    def resolve(self, name: str, source: str, atc: str = "") -> str:
        """Id del principio activo; lo crea si ninguna fuente lo nombró antes."""
        entry = self._find(name) or self._entry(base_key(name) or norm(name), name.lower(), source)
        entry["sources"].add(source)
        entry["spellings"][name.lower()] += 1
        if norm(entry["name"]) != norm(name):
            entry["synonyms"].add(name.lower())
            self._index(name, entry["key"])
        if atc and len(atc) == 7:
            entry["atc"].add(atc)
        return entry["id"]

    def _find(self, name: str) -> dict | None:
        key = self.alias.get(norm(name)) or self.alias.get(base_key(name))
        return self.entries.get(key) if key else None

    def _index(self, name: str, key: str) -> None:
        self.alias.setdefault(norm(name), key)
        if base_key(name):
            self.alias.setdefault(base_key(name), key)

    def _entry(self, key: str, name: str, source: str) -> dict:
        entry = {"key": key, "id": "PA-" + re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:80], "name": name,
                 "atc": set(), "synonyms": set(), "wikidata_id": "", "sources": {source},
                 "products_ec": 0, "products_co": 0, "products_es": 0, "spellings": Counter()}
        self.entries[key] = entry
        self._index(name, key)
        self.alias.setdefault(key, key)
        return entry

    @property
    def by_id(self) -> dict[str, dict]:
        return {e["id"]: e for e in self.entries.values()}

    def rows(self) -> list[dict]:
        for e in self.entries.values():
            if not e["wikidata_id"] and e["spellings"]:
                # La ortografía más frecuente, prefiriendo la que lleva tildes ante un empate.
                e["name"] = max(e["spellings"].items(), key=lambda kv: (kv[1], kv[0] != norm(kv[0])))[0]
        return [
            {"id": e["id"], "name": e["name"], "atc_codes": "|".join(sorted(e["atc"])),
             "synonyms": "|".join(sorted(e["synonyms"] - {e["name"]})[:20]),
             "wikidata_id": e["wikidata_id"], "products_ec": e["products_ec"],
             "products_co": e["products_co"], "products_es": e["products_es"],
             "sources": "|".join(sorted(e["sources"])),
             "quality": "verified" if e["wikidata_id"] or len(e["sources"] - {"wikidata"}) >= 2 else "unverified"}
            for e in sorted(self.entries.values(), key=lambda e: e["key"])
        ]


def product(dictionary: Dictionary, country: str, names: list[str], atc: str, **fields: str) -> dict:
    ids = [dictionary.resolve(n, country, atc if len(names) == 1 else "") for n in names]
    row = {column: "" for column in PRODUCT_COLUMNS} | fields
    row |= {"country": country, "ingredients": " + ".join(names), "ingredient_ids": "|".join(ids), "atc_code": atc}
    return row


def ecuador(dictionary: Dictionary) -> list[dict]:
    sheet = openpyxl.load_workbook(ARCSA, read_only=True)["Base_Completa_ARCSA"]
    out: dict[str, dict] = {}
    for r in sheet.iter_rows(min_row=5, values_only=True):
        if not r[0]:
            continue
        registration = re.sub(r"\s+", "", clean(r[2]))
        # El principio «limpio» del Excel a veces trae solo un CAS o restos; la fórmula oficial es el respaldo.
        names = split_ingredients(clean(r[7])) or split_ingredients(clean(r[8]), r"\+|\n|;")
        trade = clean(r[5])
        if not registration:
            reject("ec", clean(r[0]), "missing_registration", trade)
        elif registration in out:
            reject("ec", registration, "duplicate_registration", trade)
        elif len(trade) < 2 or not names:
            reject("ec", registration, "missing_name_or_ingredient", trade)
        else:
            cum = clean(r[3])
            atc = cum[:7] if ATC_RE.match(cum) else ""
            atc = atc[:5] if atc.endswith("00") else atc
            brand = clean(r[6])
            out[registration] = product(
                dictionary, "ec", names, atc, id=registration, registration=registration, trade_name=trade,
                brand="" if norm(brand) == "generico" else brand,
                kind={"Marca": "brand", "Genérico": "generic"}.get(clean(r[4]), ""),
                strength=strength(clean(r[9]) or clean(r[8]), len(names)),
                dosage_form=dosage_form(clean(r[10])), dosage_form_raw=clean(r[10]),
                routes=routes(clean(r[11])), route_raw=clean(r[11]), presentation=clean(r[12]),
                holder=clean(r[13]), holder_country=clean(r[14]), sale_condition=SALE.get(clean(r[16]), ""),
                in_cnmb={"Si": "true", "No": "false"}.get(clean(r[17]), ""), valid_until=iso(r[18], "%Y-%m-%d"),
            )
    return list(out.values())


def colombia(dictionary: Dictionary) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads((SOURCE / "invima-cum.json").read_text()):
        if r.get("muestramedica") != "Si":
            groups[r["expediente"]].append(r)
    out = []
    for expediente, rows in groups.items():
        first = rows[0]
        parts: dict[str, str] = {}
        for r in rows:
            for name in split_ingredients(clean(r.get("principioactivo"))):
                amount = clean(r.get("cantidad"))
                parts.setdefault(name, f"{amount} {clean(r.get('unidadmedida'))}".strip() if amount else "")
        if not parts or len(clean(first.get("producto"))) < 2:
            reject("co", expediente, "missing_name_or_ingredient", clean(first.get("producto")))
            continue
        atc = clean(first.get("atc"))
        out.append(product(
            dictionary, "co", list(parts), atc if ATC_RE.match(atc) else "", id=expediente,
            registration=clean(first.get("registrosanitario")), trade_name=clean(first.get("producto")),
            strength=" + ".join(v for v in parts.values() if v),
            dosage_form=dosage_form(clean(first.get("formafarmaceutica"))),
            dosage_form_raw=clean(first.get("formafarmaceutica")),
            routes=routes(clean(first.get("viaadministracion"))), route_raw=clean(first.get("viaadministracion")),
            presentation=clean(first.get("descripcioncomercial")), holder=clean(first.get("titular")),
            valid_until=iso(first.get("fechavencimiento"), "%m/%d/%Y"),
        ))
    return out


def spain(dictionary: Dictionary) -> list[dict]:
    out = []
    for r in json.loads((SOURCE / "cima.json").read_text()):
        vtm = (r.get("vtm") or {}).get("nombre", "")
        names = split_ingredients(vtm, r"\s\+\s|,\s|\sy\s")
        if not names:
            reject("es", str(r["nregistro"]), "missing_name_or_ingredient", clean(r.get("nombre")))
            continue
        form = clean((r.get("formaFarmaceutica") or {}).get("nombre"))
        route = ", ".join(clean(v.get("nombre")) for v in r.get("viasAdministracion") or [])
        out.append(product(
            dictionary, "es", names, "", id=str(r["nregistro"]), registration=str(r["nregistro"]),
            trade_name=clean(r.get("nombre")), kind="generic" if r.get("generico") else "brand",
            strength=clean(r.get("dosis")), dosage_form=dosage_form(form), dosage_form_raw=form,
            routes=routes(route), route_raw=route, holder=clean(r.get("labtitular")),
            sale_condition="prescription" if r.get("receta") else "otc",
        ))
    return out


def write(name: str, columns: list[str], rows: list[dict]) -> None:
    with (ROOT / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    dictionary = Dictionary()
    dictionary.add_wikidata(SOURCE / "wikidata-atc.csv")
    countries = {"ec": ecuador(dictionary), "co": colombia(dictionary), "es": spain(dictionary)}
    by_id = dictionary.by_id
    report: dict = {"source_arcsa": ARCSA.name, "products": {}, "ingredients": len(by_id)}
    for country, rows in countries.items():
        rows.sort(key=lambda row: (norm(row["trade_name"]), row["id"]))
        for row in rows:
            for ingredient_id in row["ingredient_ids"].split("|"):
                by_id[ingredient_id][f"products_{country}"] += 1
        write(f"medicamentos-{country}.csv", PRODUCT_COLUMNS, rows)
        report["products"][country] = {
            "rows": len(rows),
            "with_atc": sum(1 for r in rows if r["atc_code"]),
            "with_strength": sum(1 for r in rows if r["strength"]),
            "dosage_form_other": sum(1 for r in rows if r["dosage_form"] == "other"),
            "without_route": sum(1 for r in rows if not r["routes"]),
        }
    write("principios-activos.csv", INGREDIENT_COLUMNS, dictionary.rows())
    write("rechazados.csv", ["country", "id", "reason", "trade_name"], rejects)
    report["rejected"] = Counter(f"{r['country']}:{r['reason']}" for r in rejects)
    report["unmapped_top"] = {k: v.most_common(40) for k, v in unmapped.items()}
    (ROOT / "reporte.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("products", "ingredients", "rejected")}, indent=2))


if __name__ == "__main__":
    main()
