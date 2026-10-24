"""Download the public Olist Brazilian E-Commerce dataset and build data/olist/olist.duckdb.

Source:  https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce  (Olist, "Brazilian E-Commerce
         Public Dataset by Olist"). License: CC BY-NC-SA 4.0, as reported by the Kaggle dataset API
         (licenseName) on 2026-10-24. Non-commercial use with attribution; derivatives share alike.
         The raw files and the built DuckDB are NOT committed (data/olist/ is gitignored); this script
         re-downloads them. See data/olist/LICENSE_OLIST.md.

Derived tables (the only transformation; every derived column is defined here, nothing else):
  ol_orders   order_id, customer_state (customers.csv join), status, purchase_date,
              delivered     = order_delivered_customer_date IS NOT NULL
              late          = delivered date > estimated delivery date (both as DATE)
              delivery_days = purchase -> delivered to customer, days (3 decimals)
              handling_days = purchase -> handed to carrier, days
              transit_days  = handed to carrier -> delivered, days
  ol_items    order_id, item_no, product_id, seller_id, category (English, translation.csv), price, freight
  ol_reviews  review_id, order_id, score, created_date
  ol_sellers  seller_id, seller_state

  python scripts/olist_fetch.py            # download (if missing), verify sha256, build
  python scripts/olist_fetch.py --zip PATH # use an already downloaded archive
"""
from __future__ import annotations
import argparse, hashlib, sys, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "olist"
URL = "https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce"
SHA256 = "967e41e04fc306fe604e2a693f488995a8b41e5047418f8a5c8e4abd6deca784"  # archive fetched 2026-10-24
DB = DIR / "olist.duckdb"

BUILD = """
CREATE OR REPLACE TABLE ol_orders AS SELECT o.order_id, c.customer_state, o.order_status AS status,
  CAST(o.order_purchase_timestamp AS DATE) AS purchase_date,
  (o.order_delivered_customer_date IS NOT NULL) AS delivered,
  CASE WHEN o.order_delivered_customer_date IS NULL THEN NULL
       ELSE CAST(o.order_delivered_customer_date AS DATE) > CAST(o.order_estimated_delivery_date AS DATE) END AS late,
  ROUND(date_diff('second', o.order_purchase_timestamp, o.order_delivered_customer_date) / 86400.0, 3) AS delivery_days,
  ROUND(date_diff('second', o.order_purchase_timestamp, o.order_delivered_carrier_date) / 86400.0, 3) AS handling_days,
  ROUND(date_diff('second', o.order_delivered_carrier_date, o.order_delivered_customer_date) / 86400.0, 3) AS transit_days
FROM read_csv_auto('{d}/olist_orders_dataset.csv') o JOIN read_csv_auto('{d}/olist_customers_dataset.csv') c USING (customer_id);
CREATE OR REPLACE TABLE ol_items AS SELECT i.order_id, CAST(i.order_item_id AS INTEGER) AS item_no, i.product_id, i.seller_id,
  COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
  CAST(i.price AS DOUBLE) AS price, CAST(i.freight_value AS DOUBLE) AS freight
FROM read_csv_auto('{d}/olist_order_items_dataset.csv') i
LEFT JOIN read_csv_auto('{d}/olist_products_dataset.csv') p USING (product_id)
LEFT JOIN read_csv_auto('{d}/product_category_name_translation.csv') t USING (product_category_name);
CREATE OR REPLACE TABLE ol_reviews AS SELECT review_id, order_id, CAST(review_score AS INTEGER) AS score,
  CAST(review_creation_date AS DATE) AS created_date FROM read_csv_auto('{d}/olist_order_reviews_dataset.csv');
CREATE OR REPLACE TABLE ol_sellers AS SELECT seller_id, seller_state FROM read_csv_auto('{d}/olist_sellers_dataset.csv');
"""
TABLES = ("ol_orders", "ol_items", "ol_reviews", "ol_sellers")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build(zip_path: Path | None = None, db: Path = DB) -> Path:
    import duckdb
    raw = DIR / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    z = zip_path or DIR / "brazilian-ecommerce.zip"
    if not z.exists():
        print(f"downloading {URL}")
        urllib.request.urlretrieve(URL, z)
    got = sha256(z)
    if got != SHA256:
        raise SystemExit(f"sha256 mismatch for {z}: {got} (expected {SHA256}); refusing to build")
    zipfile.ZipFile(z).extractall(raw)
    db.unlink(missing_ok=True)
    con = duckdb.connect(str(db))
    for stmt in BUILD.format(d=raw.as_posix()).split(";"):
        if stmt.strip():
            con.execute(stmt)
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    con.close()
    print(f"built {db}: {counts}")
    return db


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zip", type=Path)
    a = ap.parse_args()
    build(a.zip)
