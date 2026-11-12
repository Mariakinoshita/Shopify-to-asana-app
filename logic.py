"""
Behind-the-scenes logic for the Shopify -> Asana app.
- Shopify: READ ONLY (looks up products, never changes anything)
- Asana: creates one new section + one task per product
"""

import re
import time
import requests

SHOPIFY_API_VERSION = "2025-10"
ASANA_API = "https://app.asana.com/api/1.0"

# Words that mean "this is a music format" (UPC is only filled in for these)
MUSIC_WORDS = [
    "vinyl", "lp", "2lp", "3lp", "4lp", "cd", "2cd", "3cd", "cassette", "tape",
    '7"', '10"', '12"', "7 inch", "10 inch", "12 inch", "7-inch", "12-inch",
    "box set", "boxset", "picture disc", "minidisc", "digital download", "album",
]

# Size endings that get stripped off to make the base SKU
SIZE_TOKENS = {
    "XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "XXXL", "3XL", "4XL", "5XL",
    "SM", "SML", "MD", "MED", "LG", "LRG", "OS", "ONESIZE", "OSFA",
}

COUNTRY_NAMES = {
    "GB": "United Kingdom", "US": "United States", "CN": "China", "BD": "Bangladesh",
    "PK": "Pakistan", "IN": "India", "TR": "Turkey", "PT": "Portugal", "DE": "Germany",
    "NL": "Netherlands", "FR": "France", "IT": "Italy", "ES": "Spain", "CZ": "Czech Republic",
    "PL": "Poland", "VN": "Vietnam", "KH": "Cambodia", "HN": "Honduras", "NI": "Nicaragua",
    "SV": "El Salvador", "GT": "Guatemala", "MX": "Mexico", "CA": "Canada", "JP": "Japan",
    "KR": "South Korea", "TW": "Taiwan", "HK": "Hong Kong", "IE": "Ireland", "BE": "Belgium",
    "AU": "Australia", "NZ": "New Zealand", "LK": "Sri Lanka", "ID": "Indonesia",
    "TH": "Thailand", "MY": "Malaysia", "PH": "Philippines", "MA": "Morocco",
    "TN": "Tunisia", "EG": "Egypt", "LT": "Lithuania", "LV": "Latvia", "BG": "Bulgaria",
    "RO": "Romania", "HU": "Hungary", "AT": "Austria", "CH": "Switzerland", "SE": "Sweden",
    "DK": "Denmark", "NO": "Norway", "FI": "Finland", "GR": "Greece", "BR": "Brazil",
}


# ---------------------------------------------------------------- helpers

def normalise(text):
    """Lower-case, straighten curly quotes, collapse spaces - for comparing titles."""
    text = (text or "").replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    return re.sub(r"\s+", " ", text).strip().casefold()


def squash(text):
    """Letters and numbers only, lower-case - for matching Asana column names."""
    return re.sub(r"[^a-z0-9]", "", (text or "").casefold())


def is_music(product):
    hay = normalise(f'{product.get("productType", "")} {product.get("title", "")}')
    for word in MUSIC_WORDS:
        if word.endswith('"') or " " in word or "-" in word:
            if word in hay:
                return True
        elif re.search(rf"\b{re.escape(word)}\b", hay):
            return True
    return False


def base_sku(variants):
    """One SKU for the whole product: size endings (-S, -M, -XL...) removed."""
    skus = [(v.get("sku") or "").strip() for v in variants]
    skus = [s for s in skus if s]
    if not skus:
        return ""
    if len(skus) == 1 and len(variants) == 1:
        return skus[0]

    bases = []
    for v in variants:
        sku = (v.get("sku") or "").strip()
        if not sku:
            continue
        size_values = [
            (o.get("value") or "").strip().upper()
            for o in v.get("selectedOptions", [])
            if "size" in (o.get("name") or "").lower()
        ]
        stripped = None
        for size in size_values:
            for sep in ("-", "_", " ", "/", "."):
                if size and sku.upper().endswith(sep + size.replace(" ", "")):
                    stripped = sku[: -(len(size.replace(" ", "")) + 1)]
                    break
            if stripped:
                break
        if stripped is None:
            parts = re.split(r"([-_/.])", sku)
            if len(parts) >= 3 and parts[-1].upper() in SIZE_TOKENS:
                stripped = "".join(parts[:-2])
        bases.append(stripped if stripped is not None else sku)

    if len(set(bases)) == 1:
        return bases[0]
    # Fallback: shared start of all the SKUs
    prefix = skus[0]
    for s in skus[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
    prefix = prefix.rstrip("-_/. ")
    return prefix or skus[0]


def first_filled(values):
    for v in values:
        if v not in (None, "", []):
            return v
    return ""


def find_release_date(metafields):
    for m in metafields:
        if "release" in (m.get("key") or "").lower():
            value = (m.get("value") or "").strip()
            match = re.search(r"\d{4}-\d{2}-\d{2}", value)
            if match:
                return match.group(0)
            if value:
                return value
    return ""


def build_row(product):
    """Turn a Shopify product into one row of the confirm table."""
    variants = product.get("variants", {}).get("nodes", [])
    inv = [v.get("inventoryItem") or {} for v in variants]
    music = is_music(product)
    prices = []
    for v in variants:
        try:
            prices.append(float(v.get("price")))
        except (TypeError, ValueError):
            pass
    cost = first_filled([(i.get("unitCost") or {}).get("amount") for i in inv])
    coo = first_filled([i.get("countryCodeOfOrigin") for i in inv])
    metafields = product.get("metafields", {}).get("nodes", [])

    return {
        "Send": True,
        "Task name": product.get("title", ""),
        "Artist": product.get("vendor", "") or "",
        "Release date": find_release_date(metafields),
        "UPC": first_filled([v.get("barcode") for v in variants]) if music else "",
        "SKU": base_sku(variants),
        "PPD / Cost per item": f"{float(cost):.2f}" if cost not in ("", None) else "",
        "RRP": f"{min(prices):.2f}" if prices else "",
        "HS code": first_filled([i.get("harmonizedSystemCode") for i in inv]) or "",
        "Country of origin": COUNTRY_NAMES.get(coo, coo) if coo else "",
    }


def size_lines(product):
    """For clothing: one line per size, e.g. 'S - QUE001-HOOD-S'.
    Used for anything with more than one variant that isn't a music format."""
    variants = product.get("variants", {}).get("nodes", [])
    has_size = any("size" in (o.get("name") or "").lower()
                   for v in variants for o in v.get("selectedOptions", []))
    if len(variants) < 2 or (is_music(product) and not has_size):
        return []
    lines = []
    for v in variants:
        label = (v.get("title") or "").strip() or " / ".join(
            o.get("value", "") for o in v.get("selectedOptions", []))
        sku = (v.get("sku") or "").strip()
        lines.append((label, f"{label} - {sku}" if sku else label))
    return lines


def size_description(lines):
    """Text for the Asana task description."""
    if not lines:
        return ""
    labels = [label for label, _ in lines]
    size_range = labels[0] if len(labels) == 1 else f"{labels[0]} – {labels[-1]}"
    return f"Size range: {size_range}\n\n" + "\n".join(line for _, line in lines)


# ---------------------------------------------------------------- Shopify (read only)

PRODUCT_QUERY = """
query ($q: String!) {
  products(first: 10, query: $q) {
    nodes {
      id title vendor productType
      variants(first: 100) {
        nodes {
          title sku barcode price
          selectedOptions { name value }
          inventoryItem { unitCost { amount } harmonizedSystemCode countryCodeOfOrigin }
        }
      }
      metafields(first: 50) { nodes { namespace key value } }
    }
  }
}
"""


def shopify_login(shop, client_id, client_secret):
    r = requests.post(
        f"https://{shop}/admin/oauth/access_token",
        data={"grant_type": "client_credentials", "client_id": client_id,
              "client_secret": client_secret},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Couldn't log in to {shop} ({r.status_code}). "
                           f"Is the app installed on this store? {r.text[:200]}")
    return r.json()["access_token"]


def shopify_query(shop, token, query, variables):
    url = f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    for _ in range(5):
        r = requests.post(url, json={"query": query, "variables": variables},
                          headers=headers, timeout=60)
        if r.status_code == 429:
            time.sleep(2)
            continue
        r.raise_for_status()
        body = r.json()
        errors = body.get("errors")
        if errors:
            if any("THROTTLED" in str(e) for e in errors):
                time.sleep(2)
                continue
            raise RuntimeError(f"Shopify error: {errors}")
        return body["data"]
    raise RuntimeError("Shopify kept saying 'slow down' - try again in a minute.")


def find_product(shop, token, title):
    """Returns (product or None, list of similar titles)."""
    wanted = normalise(title)
    escaped = title.replace("\\", "\\\\").replace('"', '\\"')
    plain = re.sub(r'[":()\\]', " ", title)
    seen, suggestions = set(), []
    for q in (f'title:"{escaped}"', plain):
        nodes = shopify_query(shop, token, PRODUCT_QUERY, {"q": q})["products"]["nodes"]
        for p in nodes:
            if normalise(p["title"]) == wanted:
                return p, []
            if p["title"] not in seen:
                seen.add(p["title"])
                suggestions.append(p["title"])
    return None, suggestions[:5]


# ---------------------------------------------------------------- Asana

# Which Asana column each piece of info goes into (names are matched loosely)
ASANA_COLUMNS = {
    "Artist": ["artist", "artistname", "vendor"],
    "Release date": ["releasedate", "release", "releaseday"],
    "UPC": ["upc", "barcode", "upcbarcode", "upcean", "ean"],
    "SKU": ["sku", "basesku", "skus"],
    "PPD / Cost per item": ["ppdcostperitem", "ppd", "costperitem", "ppdcost", "cost", "unitcost"],
    "RRP": ["rrp", "retailprice", "price"],
    "HS code": ["hscode", "hs", "harmonisedsystem", "harmonizedsystem", "harmonisedsystemcode",
                "harmonizedsystemcode", "hstariffcode", "commoditycode"],
    "Country of origin": ["countryoforigin", "coo", "origin", "countryorigin"],
}


def auto_match(fields):
    """fields: list of Asana custom fields. Returns {our column: field gid or None}."""
    result, used = {}, set()
    for stage in ("exact", "starts", "contains"):
        for col, candidates in ASANA_COLUMNS.items():
            if result.get(col):
                continue
            for f in fields:
                if f["gid"] in used:
                    continue
                name = squash(f["name"])
                hit = False
                for c in candidates:
                    if stage == "exact" and name == c:
                        hit = True
                    elif stage == "starts" and len(c) >= 3 and name.startswith(c):
                        hit = True
                    elif stage == "contains" and len(c) >= 4 and c in name:
                        hit = True
                if hit:
                    result[col] = f["gid"]
                    used.add(f["gid"])
                    break
    return {col: result.get(col) for col in ASANA_COLUMNS}


def parse_number(text):
    cleaned = re.sub(r"[£$€,\s]", "", str(text))
    return float(cleaned)


class Asana:
    def __init__(self, token):
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def call(self, method, path, **kwargs):
        for _ in range(6):
            r = requests.request(method, ASANA_API + path, headers=self.headers,
                                 timeout=60, **kwargs)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 5)))
                continue
            if r.status_code >= 400:
                try:
                    msg = "; ".join(e.get("message", "") for e in r.json().get("errors", []))
                except ValueError:
                    msg = r.text[:200]
                raise RuntimeError(f"Asana said no ({r.status_code}): {msg}")
            return r.json()
        raise RuntimeError("Asana kept saying 'slow down' - try again in a minute.")

    def get_all(self, path, params=None):
        params = dict(params or {}, limit=100)
        items = []
        while True:
            body = self.call("GET", path, params=params)
            items += body.get("data", [])
            nxt = body.get("next_page")
            if not nxt:
                return items
            params["offset"] = nxt["offset"]

    def workspaces(self):
        return self.get_all("/workspaces")

    def projects(self, workspace_gid):
        return self.get_all("/projects", {"workspace": workspace_gid, "archived": "false",
                                          "opt_fields": "name"})

    def custom_fields(self, project_gid):
        settings = self.get_all(
            f"/projects/{project_gid}/custom_field_settings",
            {"opt_fields": "custom_field.name,custom_field.resource_subtype,"
                           "custom_field.enum_options.name,custom_field.enum_options.enabled"},
        )
        return [s["custom_field"] for s in settings]

    def sections(self, project_gid):
        return self.get_all(f"/projects/{project_gid}/sections", {"opt_fields": "name"})

    def create_section(self, project_gid, name, at_top=False):
        data = {"name": name}
        if at_top:
            existing = self.sections(project_gid)
            if existing:
                data["insert_before"] = existing[0]["gid"]
        return self.call("POST", f"/projects/{project_gid}/sections", json={"data": data})["data"]

    def add_enum_option(self, field_gid, name):
        return self.call("POST", f"/custom_fields/{field_gid}/enum_options",
                         json={"data": {"name": name}})["data"]

    def create_task(self, project_gid, section_gid, name, custom_fields, after_gid=None,
                    notes=""):
        data = {"name": name, "projects": [project_gid], "custom_fields": custom_fields}
        if notes:
            data["notes"] = notes
        task = self.call("POST", "/tasks", json={"data": data})["data"]
        move = {"task": task["gid"]}
        if after_gid:
            move["insert_after"] = after_gid
        self.call("POST", f"/sections/{section_gid}/addTask", json={"data": move})
        return task

    def value_for(self, field, raw, add_missing_options):
        """Convert a value from the table into what Asana wants for this field type.
        Returns (value or None, warning text or None)."""
        raw = "" if raw is None else str(raw).strip()
        if not raw or raw.lower() == "nan":
            return None, None
        kind = field.get("resource_subtype")
        if kind == "text":
            return raw, None
        if kind == "number":
            try:
                return parse_number(raw), None
            except ValueError:
                return None, f"'{raw}' isn't a number, so {field['name']} was left blank"
        if kind == "date":
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                return {"date": raw}, None
            return None, f"'{raw}' isn't a YYYY-MM-DD date, so {field['name']} was left blank"
        if kind in ("enum", "multi_enum"):
            options = field.setdefault("enum_options", [])
            match = next((o for o in options if o.get("enabled", True)
                          and normalise(o["name"]) == normalise(raw)), None)
            if not match and add_missing_options:
                try:
                    match = self.add_enum_option(field["gid"], raw)
                    options.append(match)
                except RuntimeError as e:
                    return None, f"Couldn't add '{raw}' to the {field['name']} dropdown ({e})"
            if not match:
                return None, f"'{raw}' isn't an option in the {field['name']} dropdown"
            return (match["gid"] if kind == "enum" else [match["gid"]]), None
        return None, f"{field['name']} is a {kind} field, which the app can't fill in"
