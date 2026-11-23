"""Build a small, synthetic manufacturing ERP database (data/erp.db).

Everything here is made up: a fictional implement manufacturer, "Prairie Implements".
The schema is generic ERP (parts, inventory, purchasing, production, sales) and is not
copied from any real company's system.

Run:  python data/build_db.py
"""

import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
DB_PATH = HERE / "erp.db"
DICT_PATH = HERE / "data_dictionary.json"

rng = random.Random(42)  # fixed seed: the same database every time

# ── Schema + data dictionary (what each column means) ────────────────────────
TABLES = {
    "customers": {
        "description": "Dealers and farms that buy from us.",
        "columns": {
            "customer_id": ("INTEGER PRIMARY KEY", "Unique customer number."),
            "name": ("TEXT NOT NULL", "Customer (dealer or farm) name."),
            "province": ("TEXT NOT NULL", "Canadian province code, e.g. AB, SK, MB."),
            "segment": ("TEXT NOT NULL", "Customer type: 'Dealer' or 'Direct farm'."),
        },
    },
    "suppliers": {
        "description": "Companies we buy parts and raw material from.",
        "columns": {
            "supplier_id": ("INTEGER PRIMARY KEY", "Unique supplier number."),
            "name": ("TEXT NOT NULL", "Supplier name."),
            "country": ("TEXT NOT NULL", "Supplier country: 'Canada', 'USA' or 'Germany'."),
            "lead_time_days": ("INTEGER NOT NULL", "Typical days from order to delivery."),
        },
    },
    "parts": {
        "description": "Every item we buy, make or sell. Finished machines are parts with category 'Finished good'.",
        "columns": {
            "part_id": ("INTEGER PRIMARY KEY", "Internal part number (use for joins)."),
            "part_number": ("TEXT NOT NULL UNIQUE", "Part number printed on labels, e.g. 'PI-1001'."),
            "description": ("TEXT NOT NULL", "What the part is."),
            "category": ("TEXT NOT NULL", "'Raw material', 'Component', 'Hydraulics', 'Electrical' or 'Finished good'."),
            "unit_cost": ("REAL NOT NULL", "Standard cost per unit in CAD."),
            "list_price": ("REAL", "Selling price per unit in CAD. Only set for finished goods."),
            "supplier_id": ("INTEGER REFERENCES suppliers(supplier_id)", "Main supplier. NULL for parts we make ourselves."),
            "reorder_point": ("INTEGER NOT NULL", "Reorder when total available stock falls below this."),
        },
    },
    "inventory": {
        "description": "Stock per part per warehouse.",
        "columns": {
            "part_id": ("INTEGER NOT NULL REFERENCES parts(part_id)", "The part."),
            "warehouse": ("TEXT NOT NULL", "Warehouse: 'Main plant' or 'Parts depot'."),
            "qty_on_hand": ("INTEGER NOT NULL", "Units physically in the warehouse."),
            "qty_allocated": ("INTEGER NOT NULL", "Units already promised to orders. Available = qty_on_hand - qty_allocated."),
        },
        "primary_key": ["part_id", "warehouse"],
    },
    "purchase_orders": {
        "description": "Orders we place with suppliers (header).",
        "columns": {
            "po_id": ("INTEGER PRIMARY KEY", "Purchase order number."),
            "supplier_id": ("INTEGER NOT NULL REFERENCES suppliers(supplier_id)", "Supplier ordered from."),
            "order_date": ("TEXT NOT NULL", "Date ordered, ISO format YYYY-MM-DD."),
            "status": ("TEXT NOT NULL", "'Open', 'Partially received', 'Received' or 'Cancelled'."),
        },
    },
    "po_lines": {
        "description": "Lines of a purchase order: which part, how many.",
        "columns": {
            "po_id": ("INTEGER NOT NULL REFERENCES purchase_orders(po_id)", "The purchase order."),
            "line_no": ("INTEGER NOT NULL", "Line number within the order."),
            "part_id": ("INTEGER NOT NULL REFERENCES parts(part_id)", "Part ordered."),
            "qty_ordered": ("INTEGER NOT NULL", "Units ordered."),
            "qty_received": ("INTEGER NOT NULL", "Units received so far."),
            "unit_price": ("REAL NOT NULL", "Price per unit in CAD on this order."),
        },
        "primary_key": ["po_id", "line_no"],
    },
    "work_orders": {
        "description": "Production jobs: build a quantity of a finished good.",
        "columns": {
            "wo_id": ("INTEGER PRIMARY KEY", "Work order number."),
            "part_id": ("INTEGER NOT NULL REFERENCES parts(part_id)", "Finished good being built."),
            "qty": ("INTEGER NOT NULL", "Units to build."),
            "start_date": ("TEXT NOT NULL", "Planned start, YYYY-MM-DD."),
            "due_date": ("TEXT NOT NULL", "Planned finish, YYYY-MM-DD."),
            "status": ("TEXT NOT NULL", "'Planned', 'In progress', 'Complete' or 'On hold'."),
        },
    },
    "sales_orders": {
        "description": "Orders customers place with us (header).",
        "columns": {
            "so_id": ("INTEGER PRIMARY KEY", "Sales order number."),
            "customer_id": ("INTEGER NOT NULL REFERENCES customers(customer_id)", "Customer who ordered."),
            "order_date": ("TEXT NOT NULL", "Date ordered, YYYY-MM-DD."),
            "ship_date": ("TEXT", "Date shipped, YYYY-MM-DD. NULL if not shipped yet."),
            "status": ("TEXT NOT NULL", "'Open', 'Shipped' or 'Cancelled'."),
        },
    },
    "so_lines": {
        "description": "Lines of a sales order: which machine, how many, at what price.",
        "columns": {
            "so_id": ("INTEGER NOT NULL REFERENCES sales_orders(so_id)", "The sales order."),
            "line_no": ("INTEGER NOT NULL", "Line number within the order."),
            "part_id": ("INTEGER NOT NULL REFERENCES parts(part_id)", "Finished good sold."),
            "qty": ("INTEGER NOT NULL", "Units sold."),
            "unit_price": ("REAL NOT NULL", "Selling price per unit in CAD on this order."),
        },
        "primary_key": ["so_id", "line_no"],
    },
}


def create_schema(con: sqlite3.Connection) -> None:
    for table, spec in TABLES.items():
        cols = [f"{name} {ctype}" for name, (ctype, _) in spec["columns"].items()]
        if "primary_key" in spec:
            cols.append(f"PRIMARY KEY ({', '.join(spec['primary_key'])})")
        con.execute(f"CREATE TABLE {table} (\n  " + ",\n  ".join(cols) + "\n)")


def d(start: date, days: int) -> str:
    return (start + timedelta(days=days)).isoformat()


def populate(con: sqlite3.Connection) -> None:
    provinces = ["AB", "AB", "AB", "SK", "SK", "MB", "BC"]
    farm_words = ["Prairie", "Golden", "Northern", "Willow", "Badlands", "Aspen", "Red Deer",
                  "Bow River", "Coulee", "Chinook", "Parkland", "Big Sky"]
    customers = []
    for i in range(1, 31):
        seg = "Dealer" if i % 3 else "Direct farm"
        name = f"{rng.choice(farm_words)} {'Ag Equipment' if seg == 'Dealer' else 'Farms'} {i}"
        customers.append((i, name, rng.choice(provinces), seg))
    con.executemany("INSERT INTO customers VALUES (?,?,?,?)", customers)

    suppliers = [
        (1, "Alberta Steel Supply", "Canada", 7),
        (2, "Midwest Hydraulics", "USA", 21),
        (3, "Calgary Fasteners", "Canada", 5),
        (4, "Hansa Antriebstechnik", "Germany", 45),
        (5, "Prairie Electric Components", "Canada", 10),
        (6, "Great Plains Castings", "USA", 30),
    ]
    con.executemany("INSERT INTO suppliers VALUES (?,?,?,?)", suppliers)

    # (description, category, cost range, supplier, reorder point)
    catalog = [
        ("Steel plate 1/4in", "Raw material", (40, 60), 1, 200),
        ("Steel tube 3in", "Raw material", (25, 35), 1, 300),
        ("Angle iron 2in", "Raw material", (12, 18), 1, 250),
        ("Hex bolt M16", "Component", (0.4, 0.8), 3, 5000),
        ("Lock nut M16", "Component", (0.2, 0.4), 3, 5000),
        ("Bearing 6205", "Component", (6, 9), 6, 400),
        ("Gearbox 540rpm", "Component", (650, 800), 4, 20),
        ("Cast hub", "Component", (85, 110), 6, 60),
        ("Hydraulic cylinder 3x8", "Hydraulics", (180, 240), 2, 40),
        ("Hydraulic hose 3/8in", "Hydraulics", (15, 25), 2, 150),
        ("Hydraulic valve block", "Hydraulics", (300, 380), 2, 25),
        ("Wiring harness", "Electrical", (55, 75), 5, 60),
        ("LED work light", "Electrical", (35, 50), 5, 80),
        ("Control module", "Electrical", (220, 290), 5, 30),
        ("Paint, implement red (L)", "Raw material", (18, 24), 1, 120),
    ]
    finished = [
        ("Bale processor BP-500", 18500, 24900),
        ("Rotary mower RM-15", 9800, 14200),
        ("Feed wagon FW-300", 21000, 29500),
        ("Post pounder PP-200", 6200, 8900),
        ("Rock picker RP-12", 11800, 16800),
    ]
    parts = []
    pid = 1
    for desc, cat, (lo, hi), sup, rop in catalog:
        parts.append((pid, f"PI-{1000 + pid}", desc, cat, round(rng.uniform(lo, hi), 2), None, sup, rop))
        pid += 1
    first_fg = pid
    for desc, cost, price in finished:
        parts.append((pid, f"PI-{1000 + pid}", desc, "Finished good", float(cost), float(price), None, 3))
        pid += 1
    con.executemany("INSERT INTO parts VALUES (?,?,?,?,?,?,?,?)", parts)

    inv = []
    for p in parts:
        part_id, rop = p[0], p[7]
        for wh in ("Main plant", "Parts depot"):
            if wh == "Parts depot" and p[3] == "Raw material":
                continue  # raw material only sits at the plant
            # about a third of parts end up below their reorder point
            low = rng.random() < 0.33
            on_hand = rng.randint(0, max(1, rop // 2)) if low else rng.randint(rop // 2, rop * 2)
            alloc = rng.randint(0, on_hand // 3) if on_hand else 0
            inv.append((part_id, wh, on_hand, alloc))
    con.executemany("INSERT INTO inventory VALUES (?,?,?,?)", inv)

    year = date(2026, 1, 5)
    po_rows, po_lines = [], []
    bought = [p for p in parts if p[6] is not None]
    for po_id in range(1, 61):
        sup = rng.choice(suppliers)[0]
        order_day = rng.randint(0, 300)
        status = rng.choices(["Received", "Partially received", "Open", "Cancelled"], [55, 15, 25, 5])[0]
        po_rows.append((po_id, sup, d(year, order_day), status))
        options = [p for p in bought if p[6] == sup] or bought
        for line_no, part in enumerate(rng.sample(options, k=min(len(options), rng.randint(1, 3))), 1):
            qty = rng.randint(10, 500) if part[4] < 50 else rng.randint(2, 40)
            received = {"Received": qty, "Partially received": rng.randint(1, qty - 1) if qty > 1 else 0,
                        "Open": 0, "Cancelled": 0}[status]
            po_lines.append((po_id, line_no, part[0], qty, received, round(part[4] * rng.uniform(0.95, 1.08), 2)))
    con.executemany("INSERT INTO purchase_orders VALUES (?,?,?,?)", po_rows)
    con.executemany("INSERT INTO po_lines VALUES (?,?,?,?,?,?)", po_lines)

    fgs = [p for p in parts if p[0] >= first_fg]
    wos = []
    for wo_id in range(1, 41):
        fg = rng.choice(fgs)
        start = rng.randint(0, 320)
        status = rng.choices(["Complete", "In progress", "Planned", "On hold"], [50, 20, 25, 5])[0]
        wos.append((wo_id, fg[0], rng.randint(2, 12), d(year, start), d(year, start + rng.randint(7, 30)), status))
    con.executemany("INSERT INTO work_orders VALUES (?,?,?,?,?,?)", wos)

    sos, so_lines = [], []
    for so_id in range(1, 121):
        cust = rng.choice(customers)
        order_day = rng.randint(0, 320)
        status = rng.choices(["Shipped", "Open", "Cancelled"], [70, 25, 5])[0]
        ship = d(year, order_day + rng.randint(3, 25)) if status == "Shipped" else None
        sos.append((so_id, cust[0], d(year, order_day), ship, status))
        for line_no, fg in enumerate(rng.sample(fgs, k=rng.randint(1, 2)), 1):
            discount = 0.88 if cust[3] == "Dealer" else 1.0
            so_lines.append((so_id, line_no, fg[0], rng.randint(1, 4), round(fg[5] * discount * rng.uniform(0.97, 1.0), 2)))
    con.executemany("INSERT INTO sales_orders VALUES (?,?,?,?,?)", sos)
    con.executemany("INSERT INTO so_lines VALUES (?,?,?,?,?)", so_lines)


def write_dictionary() -> None:
    out = {
        t: {"description": s["description"],
            "columns": {c: desc for c, (_, desc) in s["columns"].items()}}
        for t, s in TABLES.items()
    }
    DICT_PATH.write_text(json.dumps(out, indent=2) + "\n")


def main() -> None:
    DB_PATH.unlink(missing_ok=True)
    con = sqlite3.connect(DB_PATH)
    create_schema(con)
    populate(con)
    con.commit()
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    con.close()
    write_dictionary()
    print(f"Built {DB_PATH.name}: " + ", ".join(f"{t}={n}" for t, n in counts.items()))
    print(f"Wrote {DICT_PATH.name}")


if __name__ == "__main__":
    main()
