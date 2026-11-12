import pandas as pd
import streamlit as st

from logic import (ASANA_COLUMNS, Asana, auto_match, build_row, find_product,
                   shopify_login, size_description, size_lines)

st.set_page_config(page_title="Shopify → Asana", page_icon="📋", layout="wide")
st.title("📋 Shopify → Asana")
st.caption("Pick a store, paste product titles, check the info, then send it to an Asana board.")

# Optional team password: only asked for if APP_PASSWORD is set in the secrets
if st.secrets.get("APP_PASSWORD") and not st.session_state.get("unlocked"):
    pw = st.text_input("Team password", type="password")
    if pw == st.secrets["APP_PASSWORD"]:
        st.session_state.unlocked = True
        st.rerun()
    if pw:
        st.error("Wrong password.")
    st.stop()

STORES = dict(st.secrets.get("STORES", {}))          # "Queen UK" = "queen-uk.myshopify.com"
DEFAULT_BOARDS = dict(st.secrets.get("ASANA_BOARDS", {}))  # "Queen UK" = "<project gid>"
COLUMNS = ["Send", "Task name"] + list(ASANA_COLUMNS) + ["Sizes"]


@st.cache_data(ttl=60 * 60 * 20, show_spinner=False)
def get_shopify_token(shop):
    return shopify_login(shop, st.secrets["SHOPIFY_CLIENT_ID"], st.secrets["SHOPIFY_CLIENT_SECRET"])


@st.cache_resource
def asana():
    return Asana(st.secrets["ASANA_TOKEN"])


@st.cache_data(ttl=600, show_spinner=False)
def get_projects():
    ws_gid = st.secrets.get("ASANA_WORKSPACE_GID")
    workspaces = [{"gid": ws_gid}] if ws_gid else asana().workspaces()
    projects = []
    for ws in workspaces:
        projects += asana().projects(ws["gid"])
    return sorted(projects, key=lambda p: p["name"].lower())


@st.cache_data(ttl=300, show_spinner=False)
def get_fields(project_gid):
    return asana().custom_fields(project_gid)


# ------------------------------------------------------------ 1. Store + titles
if not STORES:
    st.error("No stores set up yet - add them under [STORES] in the app's secrets.")
    st.stop()

store = st.selectbox("Store", list(STORES))
if st.session_state.get("store") != store:  # new store -> clear old results
    st.session_state.update(store=store, rows=None, missing=[])

titles_text = st.text_area("Product titles (one per line, exactly as in Shopify)", height=180)

if st.button("🔍 Look up products", type="primary"):
    titles = list(dict.fromkeys(t.strip() for t in titles_text.splitlines() if t.strip()))
    if not titles:
        st.warning("Paste at least one product title first.")
    else:
        shop = STORES[store]
        rows, missing, sizes = [], [], []
        try:
            token = get_shopify_token(shop)
            bar = st.progress(0.0, "Looking up products…")
            for i, title in enumerate(titles, 1):
                product, suggestions = find_product(shop, token, title)
                if product:
                    lines = size_lines(product)
                    rows.append({**build_row(product),
                                 "Sizes": f"{len(lines)} sizes" if lines else ""})
                    sizes.append(size_description(lines))
                else:
                    missing.append((title, suggestions))
                bar.progress(i / len(titles), f"Looked up {i} of {len(titles)}")
            bar.empty()
        except Exception as e:
            st.error(str(e))
        st.session_state.rows = pd.DataFrame(rows, columns=COLUMNS) if rows else None
        st.session_state.missing = missing
        st.session_state.sizes = sizes
        st.session_state.sent = None
        st.session_state.lookup_id = st.session_state.get("lookup_id", 0) + 1

for title, suggestions in st.session_state.get("missing", []):
    tip = f" Did you mean: {' / '.join(suggestions)}" if suggestions else ""
    st.warning(f"Not found in {store}: **{title}**.{tip}")

rows = st.session_state.get("rows")
if rows is None:
    st.stop()

# ------------------------------------------------------------ 2. Confirm
st.subheader("2. Check the info")
st.caption("Click any cell to fix it. Untick **Send** to leave a product out. "
           "UPC is only filled in for music formats; release date and country of origin "
           "are only filled in if they're in Shopify.")
edited = st.data_editor(
    rows, hide_index=True, use_container_width=True, key=f"editor_{st.session_state.get('lookup_id', 0)}",
    column_config={"Send": st.column_config.CheckboxColumn(width="small")},
    disabled=["Sizes"],
)
all_sizes = st.session_state.get("sizes", [])
with st.expander("Size descriptions preview"):
    shown = False
    for i, row in edited.iterrows():
        if row["Send"] and all_sizes[i]:
            st.markdown(f"**{row['Task name']}**")
            st.text(all_sizes[i])
            shown = True
    if not shown:
        st.write("None of these products have sizes.")
blanks = {c: int((edited[edited["Send"]][c].astype(str).str.strip() == "").sum())
          for c in ASANA_COLUMNS}
blank_notes = [f"{c}: {n}" for c, n in blanks.items() if n]
if blank_notes:
    st.info("Blank cells (these will be left empty in Asana) — " + ", ".join(blank_notes))

# ------------------------------------------------------------ 3. Asana
st.subheader("3. Send to Asana")
try:
    projects = get_projects()
except Exception as e:
    st.error(f"Couldn't connect to Asana: {e}")
    st.stop()

names = [p["name"] for p in projects]
default_gid = DEFAULT_BOARDS.get(store)
default_index = next((i for i, p in enumerate(projects) if p["gid"] == default_gid), 0)
board_name = st.selectbox("Asana board", names, index=default_index if names else None)
if not board_name:
    st.stop()
project = projects[names.index(board_name)]

section_name = st.text_input("New section title", placeholder="e.g. Queen – Winter Drop Nov 26")
at_top = st.checkbox("Put the new section at the top of the board", value=False)
add_sizes = st.checkbox("Add the size range and size SKUs to the task description (clothing)",
                        value=True)
add_options = st.checkbox("If a dropdown (e.g. Artist) is missing an option, add it", value=True)

fields = get_fields(project["gid"])
field_by_gid = {f["gid"]: f for f in fields}
auto = auto_match(fields)
with st.expander("Which Asana column gets which info", expanded=any(v is None for v in auto.values())):
    choices = [None] + [f["gid"] for f in fields]
    label = lambda g: "— don't fill in —" if g is None else field_by_gid[g]["name"]
    mapping = {}
    for col in ASANA_COLUMNS:
        mapping[col] = st.selectbox(col, choices, index=choices.index(auto[col]),
                                    format_func=label, key=f"map_{project['gid']}_{col}")
    if not fields:
        st.warning("This board has no custom columns, so only task names will be added.")

to_send = edited[edited["Send"]]
if st.button(f"📤 Send {len(to_send)} task(s) to “{board_name}”", type="primary",
             disabled=to_send.empty or not section_name.strip()):
    warnings, created = [], 0
    try:
        section = asana().create_section(project["gid"], section_name.strip(), at_top)
        bar = st.progress(0.0, "Creating tasks…")
        prev = None
        for i, (idx, row) in enumerate(to_send.iterrows(), 1):
            values = {}
            for col, gid in mapping.items():
                if not gid:
                    continue
                value, warn = asana().value_for(field_by_gid[gid], row[col], add_options)
                if warn:
                    warnings.append(f"{row['Task name']}: {warn}")
                if value is not None:
                    values[gid] = value
            try:
                notes = all_sizes[idx] if add_sizes else ""
                task = asana().create_task(project["gid"], section["gid"], row["Task name"],
                                           values, prev, notes)
                prev = task["gid"]
                created += 1
            except Exception as e:
                warnings.append(f"{row['Task name']}: not created – {e}")
            bar.progress(i / len(to_send), f"Created {created} of {len(to_send)}")
        bar.empty()
        get_fields.clear()
        st.session_state.sent = (created, board_name, project["gid"], warnings)
    except Exception as e:
        st.error(f"Couldn't create the section: {e}")

sent = st.session_state.get("sent")
if sent:
    created, board, gid, warnings = sent
    st.success(f"✅ Added {created} task(s) to **{board}**. "
               f"[Open the board](https://app.asana.com/0/{gid}/list)")
    for w in warnings:
        st.warning(w)
