"""Create a small sample SQLite database for the data starter.

Usage:
    python init_db.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "sample_data" / "sample.db"


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                country TEXT,
                created_at TEXT
            );

            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT,
                unit_price REAL
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                ordered_at TEXT,
                FOREIGN KEY (customer_id) REFERENCES customers(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            """
        )
        cur.executemany(
            "INSERT INTO customers (name, country, created_at) VALUES (?, ?, ?)",
            [
                ("Acme Corp", "US", "2024-11-01"),
                ("Globex", "UK", "2025-01-14"),
                ("Initech", "US", "2025-02-08"),
                ("Umbrella Co.", "JP", "2025-03-02"),
                ("Hooli", "US", "2025-03-30"),
            ],
        )
        cur.executemany(
            "INSERT INTO products (name, category, unit_price) VALUES (?, ?, ?)",
            [
                ("Widget A", "widgets", 9.99),
                ("Widget B", "widgets", 14.99),
                ("Gizmo Pro", "gizmos", 49.99),
                ("Sprocket", "mechanical", 3.49),
                ("Data Subscription", "saas", 199.0),
            ],
        )
        cur.executemany(
            "INSERT INTO orders (customer_id, product_id, quantity, ordered_at) VALUES (?, ?, ?, ?)",
            [
                (1, 1, 25, "2025-03-10"),
                (1, 3, 2, "2025-03-12"),
                (2, 2, 10, "2025-03-15"),
                (3, 5, 1, "2025-03-20"),
                (4, 4, 200, "2025-03-22"),
                (5, 1, 5, "2025-04-01"),
                (5, 3, 3, "2025-04-04"),
                (2, 5, 1, "2025-04-10"),
            ],
        )
        conn.commit()

    print(f"Wrote sample database → {DB_PATH}")
    print("Connection string: sqlite:///" + str(DB_PATH.as_posix()))


if __name__ == "__main__":
    main()
