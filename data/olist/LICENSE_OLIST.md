# Olist data: attribution and license

The data used by the Olist demo (`scripts/olist_fetch.py`, `app/olist/`) is the
**Brazilian E-Commerce Public Dataset by Olist**:
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

- License: **CC BY-NC-SA 4.0** (https://creativecommons.org/licenses/by-nc-sa/4.0/), as reported by the Kaggle
  dataset API (`licenseName`) on 2026-10-24.
- Attribution: Olist. Data was anonymised by Olist; we do not re-identify anyone.
- Non-commercial: used only for a non-commercial hackathon demo.
- Share-alike: the derived tables built by `scripts/olist_fetch.py` and any Olist-derived memos or traces
  under `logs/olist*` are under CC BY-NC-SA 4.0, not under the repo's code license.
- The raw CSVs and the built DuckDB are not committed. `scripts/olist_fetch.py` downloads them and
  checks the archive's sha256.
