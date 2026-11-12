# Shopify → Asana

Pick a store, paste product titles, check the info in a table, then send it to an Asana board.
The app makes a **new section** (you choose the title) and **one task per product**.
Size variants count as one product, so you get one task and not one per size.

| Asana column | Comes from Shopify |
|---|---|
| Task name | Product title |
| Artist | Vendor |
| Release date | Any product metafield with "release" in its name (only if there is one) |
| UPC | Barcode, **only for music formats** (vinyl, CD, cassette, LP, 7"/12", box set…) |
| SKU | SKU; for size variants, the base SKU without the -S / -M / -L ending |
| PPD / Cost per item | Cost per item |
| RRP | Price (the lowest variant price if sizes differ) |
| HS code | Harmonized System code |
| Country of origin | Country of origin (only if listed) |

Shopify is **read-only**. The app never changes anything in your stores.

---

## Setup (about 15 minutes)

### 1. Get an Asana token
1. In Asana, click your profile picture → **Settings** → **Apps** → **Manage Developer Apps**
   (or go to https://app.asana.com/0/my-apps).
2. **Create new token**. Name it "Shopify to Asana" and copy it.
   The app acts as *you*, so it can only see boards you can see.

### 2. Shopify
Nothing new to set up. Reuse the Client ID and Secret from your **sku-sheet-maker** app,
which is already installed on all the stores in the dropdown and already has the scopes this
app needs (`read_products`, `read_inventory`).
For a new store, install the sku-sheet-maker app on it as usual and add one line under `[STORES]`.

### 3. Try it on your laptop (PowerShell, in VS Code)
```powershell
cd Desktop\shopify_reports
# put the shopify-to-asana folder here, then:
cd shopify-to-asana
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
# open .streamlit\secrets.toml and paste in your Client ID, Secret and Asana token
streamlit run app.py
```

### 4. Put it online for the team (same as the SKU sheet generator)
1. Make a new GitHub repo and upload everything **except** `.streamlit/secrets.toml`
   (the `.gitignore` already leaves it out).
2. In Streamlit Community Cloud, click **Create app**, pick the repo, and set the main file to `app.py`.
3. **Advanced settings → Secrets**: paste the contents of your secrets.toml.

---

## How to use it
1. Choose the **store** and paste product titles, one per line, exactly as in Shopify.
2. Click **Look up products**. Any title it can't find is shown with "Did you mean…" suggestions.
3. **Check the table.** You can click any cell to fix it, and untick **Send** to leave a product out.
4. Choose the **Asana board**, type the **section title**, and click **Send**.
5. The first time you use a board, open **"Which Asana column gets which info"** to check
   the columns matched correctly. It matches by name (e.g. "PPD/Cost" → PPD / Cost per item),
   and you can change any of them.

### Good to know
- **Dropdown columns** (e.g. Artist as a dropdown): if the artist isn't an option yet, the app
  adds it, as long as the tickbox is on and you have permission to edit that field.
- **Number columns** accept "£6.50" or "6.50". **Date columns** need YYYY-MM-DD.
- Tasks are added in the same order you pasted the titles.
- Anything left blank in the table stays blank in Asana, and the app lists what was skipped and why.
