"""Deterministic synthetic e-commerce SQLite database.

Same seed -> byte-identical data, so every task has an exact, reproducible
ground truth. The agent does NOT get the schema up front; it must spend tool
calls (list_tables / describe_table / run_sql) to discover it, which is what
makes the budget actually bind.
"""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path

SEED = 20260603
DB_PATH = Path(__file__).parent / "data" / "shop.sqlite"

CATEGORIES = [
    "Electronics", "Books", "Home & Kitchen", "Toys", "Clothing",
    "Sports", "Garden", "Beauty",
]
COUNTRIES = ["USA", "Germany", "France", "UK", "Canada", "Japan", "Brazil"]
# weights make the distribution non-uniform (more realistic, less guessable)
COUNTRY_WEIGHTS = [30, 14, 10, 12, 9, 8, 7]
ORDER_STATUSES = ["completed", "cancelled", "returned", "pending"]
STATUS_WEIGHTS = [70, 12, 10, 8]

FIRST = ["Ava", "Liam", "Noah", "Emma", "Oliver", "Mia", "Lucas", "Sofia",
         "Ethan", "Isla", "Mateo", "Aria", "Leo", "Zoe", "Hugo", "Nora",
         "Felix", "Lena", "Jonas", "Clara", "Theo", "Ines", "Milo", "Rosa"]
LAST = ["Smith", "Muller", "Dubois", "Brown", "Tanaka", "Silva", "Jones",
        "Weber", "Martin", "Wilson", "Costa", "Sato", "Klein", "Moreau",
        "Taylor", "Suzuki", "Becker", "Petit", "Davies", "Lima"]


def build_db(path: Path = DB_PATH, seed: int = SEED) -> Path:
    """Build the SQLite DB from scratch. Idempotent: overwrites if present."""
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE categories (
            category_id INTEGER PRIMARY KEY,
            name        TEXT NOT NULL
        );
        CREATE TABLE products (
            product_id  INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            category_id INTEGER NOT NULL REFERENCES categories(category_id),
            price       REAL NOT NULL
        );
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            country     TEXT NOT NULL,
            signup_date TEXT NOT NULL
        );
        CREATE TABLE orders (
            order_id    INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
            order_date  TEXT NOT NULL,
            status      TEXT NOT NULL
        );
        CREATE TABLE order_items (
            order_item_id INTEGER PRIMARY KEY,
            order_id      INTEGER NOT NULL REFERENCES orders(order_id),
            product_id    INTEGER NOT NULL REFERENCES products(product_id),
            quantity      INTEGER NOT NULL,
            unit_price    REAL NOT NULL
        );
        """
    )

    # categories
    cats = [(i + 1, name) for i, name in enumerate(CATEGORIES)]
    cur.executemany("INSERT INTO categories VALUES (?,?)", cats)

    # products: 60, each in a category, price 5..500
    products = []
    for pid in range(1, 61):
        cid = rng.randint(1, len(CATEGORIES))
        price = round(rng.uniform(5, 500), 2)
        products.append((pid, f"Product {pid:03d}", cid, price))
    cur.executemany("INSERT INTO products VALUES (?,?,?,?)", products)

    # customers: 200
    customers = []
    for cid in range(1, 201):
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        country = rng.choices(COUNTRIES, weights=COUNTRY_WEIGHTS)[0]
        year = 2024
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        customers.append((cid, name, country, f"{year}-{month:02d}-{day:02d}"))
    cur.executemany("INSERT INTO customers VALUES (?,?,?,?)", customers)

    # orders: 1000, spread across 2025
    orders = []
    for oid in range(1, 1001):
        cust = rng.randint(1, 200)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        status = rng.choices(ORDER_STATUSES, weights=STATUS_WEIGHTS)[0]
        orders.append((oid, cust, f"2025-{month:02d}-{day:02d}", status))
    cur.executemany("INSERT INTO orders VALUES (?,?,?,?)", orders)

    # order_items: 1..5 per order; unit_price drawn around product price
    price_by_pid = {p[0]: p[3] for p in products}
    items = []
    oi_id = 1
    for oid in range(1, 1001):
        for _ in range(rng.randint(1, 5)):
            pid = rng.randint(1, 60)
            qty = rng.randint(1, 4)
            # unit_price within +-10% of list price (promotions etc.)
            up = round(price_by_pid[pid] * rng.uniform(0.9, 1.1), 2)
            items.append((oi_id, oid, pid, qty, up))
            oi_id += 1
    cur.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", items)

    con.commit()
    con.close()
    return path


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


if __name__ == "__main__":
    p = build_db()
    con = connect(p)
    for tbl in ["categories", "products", "customers", "orders", "order_items"]:
        n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"{tbl:14s} {n:6d} rows")
    con.close()
    print(f"built {p}")
