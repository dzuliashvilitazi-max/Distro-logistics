"""Distributor reports: completed orders, unified analytics, invoices and finance.

Pure functions over order documents. Commission always comes from the fee frozen on each order
(agreed per store/distributor at order time), so historical figures never change when agreements do.
"""
import csv
import io
from datetime import date, timedelta
from typing import Optional

import money as moneylib

PAYMENT_STATUS_KA = {
    "paid": "გადახდილი", "unpaid": "გადაუხდელი", "partially_paid": "ნაწილობრივ გადახდილი", "overdue": "ვადაგადაცილებული",
}
COMMISSION_STATUS_KA = {
    "settled_at_checkout": "დაკავებულია გადახდისას", "invoiced": "საკომისიო ინვოისში შეტანილია",
    "accrued": "დარიცხულია, ინვოისი ჯერ არ არის", "cancelled": "გაუქმებულია",
}


def _day(value) -> Optional[str]:
    return moneylib.to_platform_day(value)


def _in_range(value, start, end) -> bool:
    day = _day(value)
    if day is None:
        return not start and not end
    return (not start or day >= start) and (not end or day <= end)


def commission_state(order: dict) -> str:
    if order.get("status") == "Cancelled" or order.get("commission_status") == "Cancelled":
        return "cancelled"
    if order.get("commission_settled") or order.get("paid_at_checkout"):
        return "settled_at_checkout"
    return "invoiced" if order.get("invoice_id") else "accrued"


def order_items(order: dict) -> list:
    rows = []
    for item in order.get("items", []):
        quantity = int(item.get("quantity", 0) or 0)
        unit = moneylib.q(item.get("unit_price", 0) or 0)
        list_price = moneylib.q(item.get("list_price") or item.get("unit_price") or 0)
        rows.append({
            "product_id": item.get("product_id"), "name": item.get("name", ""), "sku": item.get("sku", ""),
            "quantity": quantity, "returned_quantity": int(item.get("returned_quantity", 0) or 0),
            "unit_price": moneylib.as_json(unit), "list_price": moneylib.as_json(max(list_price, unit)),
            "line_total": moneylib.as_json(moneylib.q(unit * quantity)),
        })
    return rows


def order_row(order: dict, view: dict, store_name: str) -> dict:
    net = moneylib.order_net_total(order)
    fee = moneylib.order_fee(order)
    items = order_items(order)
    return {
        "id": order["id"], "order_no": order.get("order_no", ""), "store_id": order.get("retailer_id"),
        "store_name": store_name or order.get("retailer_name", ""),
        "created_at": order.get("created_at"), "completed_at": view.get("delivered_at"),
        "status": order.get("status"), "items": items, "quantity": sum(i["quantity"] for i in items),
        "total": moneylib.as_json(moneylib.q(order.get("total"))),
        "returned_total": moneylib.as_json(moneylib.order_returned_total(order)),
        "net_total": moneylib.as_json(net),
        "payment_status": view.get("payment_status"), "payment_method": order.get("payment_method", ""),
        "amount_paid": view.get("amount_paid", 0), "balance_due": view.get("balance_due", 0),
        "payment_due_date": view.get("payment_due_date"),
        "commission": moneylib.as_json(fee), "commission_type": order.get("fee_type"),
        "commission_value": order.get("fee_value"), "commission_state": commission_state(order),
        "net_after_commission": moneylib.as_json(max(moneylib.ZERO, net - fee)),
        "invoice_no": order.get("order_no", ""), "commission_invoice_id": order.get("invoice_id"),
        "delivery_address": order.get("delivery_address", ""), "notes": order.get("notes", ""),
    }


def filter_completed(rows, start=None, end=None, store_id=None, product=None, order_no=None, payment_status=None):
    product_text = (product or "").strip().casefold()
    number = (order_no or "").strip().casefold()
    seen, out = set(), []
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        if (start or end) and not _in_range(row["completed_at"], start, end):
            continue
        if store_id and row["store_id"] != store_id:
            continue
        if number and number not in str(row["order_no"]).casefold():
            continue
        if payment_status and payment_status != "all" and row["payment_status"] != payment_status:
            continue
        if product_text and not any(
            item["product_id"] == product or product_text in str(item["name"]).casefold() for item in row["items"]
        ):
            continue
        out.append(row)
    return out


def completed_summary(rows) -> dict:
    return {
        "count": len(rows),
        "total": moneylib.as_json(moneylib.total_sum(r["net_total"] for r in rows)),
        "commission": moneylib.as_json(moneylib.total_sum(r["commission"] for r in rows)),
        "net_after_commission": moneylib.as_json(moneylib.total_sum(r["net_after_commission"] for r in rows)),
        "paid": moneylib.as_json(moneylib.total_sum(r["amount_paid"] for r in rows)),
        "outstanding": moneylib.as_json(moneylib.total_sum(r["balance_due"] for r in rows)),
    }


# ---------------- analytics ----------------
def _order_parts(order: dict, product_id: Optional[str]):
    """(sales, quantity, commission, per-product lines) of one order, honouring a product filter."""
    net = moneylib.order_net_total(order)
    fee = moneylib.order_fee(order)
    lines = []
    for item in order.get("items", []):
        if product_id and item.get("product_id") != product_id:
            continue
        quantity = max(0, int(item.get("quantity", 0) or 0) - int(item.get("returned_quantity", 0) or 0))
        amount = moneylib.q(moneylib.dec(item.get("unit_price", 0) or 0) * quantity)
        if quantity:
            lines.append((item, quantity, amount))
    if not product_id:
        return net, sum(q for _, q, _ in lines), fee, lines
    sales = moneylib.total_sum(a for _, _, a in lines)
    part_fee = moneylib.q(fee * sales / net) if net > 0 else moneylib.ZERO
    return sales, sum(q for _, q, _ in lines), part_fee, lines


def _summarise(orders, store_id, product_id):
    kpi = {"sales": moneylib.ZERO, "orders": 0, "completed": 0, "quantity": 0, "commission": moneylib.ZERO}
    products, stores, days = {}, {}, {}
    for order in orders:
        if order.get("status") == "Cancelled" or (store_id and order.get("retailer_id") != store_id):
            continue
        sales, quantity, fee, lines = _order_parts(order, product_id)
        if product_id and not lines:
            continue
        kpi["sales"] += sales
        kpi["orders"] += 1
        kpi["completed"] += 1 if order.get("status") == "Delivered" else 0
        kpi["quantity"] += quantity
        kpi["commission"] += fee
        store = stores.setdefault(order.get("retailer_id"), {
            "store_id": order.get("retailer_id"), "store_name": order.get("retailer_name", ""),
            "orders": 0, "quantity": 0, "sales": moneylib.ZERO, "commission": moneylib.ZERO, "last_order_at": None,
        })
        store["orders"] += 1
        store["quantity"] += quantity
        store["sales"] += sales
        store["commission"] += fee
        if not store["last_order_at"] or str(order.get("created_at", "")) > store["last_order_at"]:
            store["last_order_at"] = order.get("created_at")
        total_net = moneylib.order_net_total(order)
        for item, line_quantity, amount in lines:
            product = products.setdefault(item.get("product_id") or item.get("name"), {
                "product_id": item.get("product_id"), "name": item.get("name", ""),
                "quantity": 0, "sales": moneylib.ZERO, "orders": 0, "commission": moneylib.ZERO,
            })
            product["quantity"] += line_quantity
            product["sales"] += amount
            product["orders"] += 1
            if total_net > 0:
                product["commission"] += moneylib.q(moneylib.order_fee(order) * amount / total_net)
        day = _day(order.get("created_at"))
        if day:
            bucket = days.setdefault(day, {"sales": moneylib.ZERO, "orders": 0, "commission": moneylib.ZERO})
            bucket["sales"] += sales
            bucket["orders"] += 1
            bucket["commission"] += fee
    return kpi, products, stores, days


def _kpi_json(kpi: dict) -> dict:
    return {
        "total_sales": moneylib.as_json(kpi["sales"]), "orders": kpi["orders"], "completed_orders": kpi["completed"],
        "average_order_value": moneylib.as_json(moneylib.divide(kpi["sales"], kpi["orders"])),
        "quantity": kpi["quantity"], "commission": moneylib.as_json(kpi["commission"]),
        "net_revenue": moneylib.as_json(max(moneylib.ZERO, kpi["sales"] - kpi["commission"])),
    }


def _change(current, previous):
    if not previous:
        return None
    return round((float(current) - float(previous)) / float(previous) * 100, 1)


def previous_period(start: Optional[str], end: Optional[str]):
    if not start or not end:
        return None
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    length = (last - first).days + 1
    return (first - timedelta(days=length)).isoformat(), (first - timedelta(days=1)).isoformat()


def build_analytics(orders, previous_orders, start, end, store_id=None, product_id=None) -> dict:
    kpi, products, stores, days = _summarise(orders, store_id, product_id)
    current = _kpi_json(kpi)
    previous = change = None
    if previous_orders is not None:
        previous_kpi, _, _, _ = _summarise(previous_orders, store_id, product_id)
        previous = _kpi_json(previous_kpi)
        change = {key: _change(current[key], previous[key] or 0) for key in current if current[key] is not None}
    monthly = not start or not end or (date.fromisoformat(end) - date.fromisoformat(start)).days > 92
    series = {}
    for day, bucket in sorted(days.items()):
        key = day[:7] if monthly else day
        item = series.setdefault(key, {"period": key, "sales": moneylib.ZERO, "orders": 0, "commission": moneylib.ZERO})
        item["sales"] += bucket["sales"]
        item["orders"] += bucket["orders"]
        item["commission"] += bucket["commission"]
    product_rows = sorted((
        {**p, "sales": moneylib.as_json(p["sales"]), "commission": moneylib.as_json(p["commission"])}
        for p in products.values()
    ), key=lambda p: (-float(p["sales"]), p["name"]))
    store_rows = sorted((
        {**s, "sales": moneylib.as_json(s["sales"]), "commission": moneylib.as_json(s["commission"]),
         "net_revenue": moneylib.as_json(max(moneylib.ZERO, s["sales"] - s["commission"]))}
        for s in stores.values()
    ), key=lambda s: (-float(s["sales"]), s["store_name"]))
    return {
        "kpis": current, "previous": previous, "change": change,
        "previous_range": dict(zip(("start_date", "end_date"), previous_period(start, end) or (None, None))),
        "granularity": "monthly" if monthly else "daily",
        "series": [{**v, "sales": moneylib.as_json(v["sales"]), "commission": moneylib.as_json(v["commission"])}
                   for v in series.values()],
        "top_products": sorted(product_rows, key=lambda p: -p["quantity"])[:10],
        "products": product_rows[:300], "stores": store_rows[:300],
        "most_active_stores": sorted(store_rows, key=lambda s: (-s["orders"], -float(s["sales"])))[:10],
    }


# ---------------- invoices & finance ----------------
def invoice_row(order: dict, view: dict, store_name: str) -> dict:
    fee = moneylib.order_fee(order)
    return {
        "id": order["id"], "invoice_no": order.get("order_no", ""), "order_no": order.get("order_no", ""),
        "store_id": order.get("retailer_id"), "store_name": store_name or order.get("retailer_name", ""),
        "created_at": order.get("created_at"), "due_date": view.get("payment_due_date"),
        "total": moneylib.as_json(moneylib.q(order.get("total"))), "paid": view.get("amount_paid", 0),
        "balance": view.get("balance_due", 0), "payment_status": view.get("payment_status"),
        "order_status": order.get("status"), "commission": moneylib.as_json(fee),
        "commission_type": order.get("fee_type"), "commission_value": order.get("fee_value"),
        "commission_state": commission_state(order),
    }


def filter_invoices(rows, status=None, start=None, end=None, store_id=None, invoice_no=None, min_amount=None, max_amount=None):
    number = (invoice_no or "").strip().casefold()
    out = []
    for row in rows:
        if status and status != "all" and row["payment_status"] != status:
            continue
        if (start or end) and not _in_range(row["created_at"], start, end):
            continue
        if store_id and row["store_id"] != store_id:
            continue
        if number and number not in str(row["invoice_no"]).casefold():
            continue
        if min_amount is not None and float(row["total"]) < min_amount:
            continue
        if max_amount is not None and float(row["total"]) > max_amount:
            continue
        out.append(row)
    return out


def finance_summary(rows, completed_orders) -> dict:
    """Completed sales vs customer payments vs platform commission, each reported separately."""
    sales = moneylib.total_sum(moneylib.order_net_total(o) for o in completed_orders)
    commission = moneylib.total_sum(moneylib.order_fee(o) for o in completed_orders)
    agreements = {}
    for order in completed_orders:
        if moneylib.order_fee(order) <= 0:
            continue
        key = (order.get("fee_type") or "", order.get("fee_value"))
        agreements[key] = agreements.get(key, 0) + 1
    states = {"settled_at_checkout": moneylib.ZERO, "invoiced": moneylib.ZERO, "accrued": moneylib.ZERO}
    for order in completed_orders:
        state = commission_state(order)
        if state in states:
            states[state] += moneylib.order_fee(order)
    return {
        "completed_sales": moneylib.as_json(sales),
        "commission": moneylib.as_json(commission),
        "commission_percent": moneylib.as_json(moneylib.divide(commission * 100, sales)) if sales > 0 else None,
        "commission_agreements": [
            {"fee_type": k[0], "fee_value": k[1], "orders": n} for k, n in sorted(agreements.items(), key=lambda x: -x[1])
        ],
        "commission_by_state": {k: moneylib.as_json(v) for k, v in states.items()},
        "net_after_commission": moneylib.as_json(max(moneylib.ZERO, sales - commission)),
        "invoiced_total": moneylib.as_json(moneylib.total_sum(r["total"] for r in rows)),
        "paid": moneylib.as_json(moneylib.total_sum(r["paid"] for r in rows)),
        "unpaid": moneylib.as_json(moneylib.total_sum(r["balance"] for r in rows)),
        "invoice_count": len(rows),
    }


def settlement_events(orders, payouts, commission_invoices, store_names, start=None, end=None) -> list:
    """Three separate ledgers: customer payments, gateway payouts recorded by the backend, platform commission invoices."""
    events = []
    for order in orders:
        for entry in order.get("payment_entries", []) or []:
            events.append({
                "kind": "customer_payment", "at": entry.get("recorded_at"), "order_no": order.get("order_no", ""),
                "store_name": store_names.get(order.get("retailer_id"), order.get("retailer_name", "")),
                "amount": moneylib.as_json(moneylib.q(entry.get("amount") or 0)),
                "method": entry.get("method", ""), "reference": entry.get("reference", ""), "status": "recorded",
            })
    for payout in payouts:
        events.append({
            "kind": "payout", "at": payout.get("created_at"), "order_no": payout.get("order_no", ""),
            "store_name": payout.get("retailer_name", ""),
            "amount": moneylib.as_json(moneylib.q(payout.get("supplier_payout") or 0)),
            "commission": moneylib.as_json(moneylib.q(payout.get("commission") or 0)),
            "method": payout.get("method", ""), "reference": payout.get("checkout_id", ""),
            "status": payout.get("status", ""),
        })
    for invoice in commission_invoices:
        events.append({
            "kind": "commission_invoice", "at": invoice.get("paid_at") or invoice.get("issue_date"),
            "order_no": invoice.get("invoice_no", ""), "store_name": "",
            "amount": moneylib.as_json(moneylib.q(invoice.get("amount") or 0)), "method": invoice.get("paid_via") or "",
            "reference": invoice.get("period_label", ""), "status": invoice.get("status", ""),
        })
    events = [e for e in events if _in_range(e["at"], start, end)]
    return sorted(events, key=lambda e: str(e["at"] or ""), reverse=True)[:500]


# ---------------- exports ----------------
def _safe_cell(value):
    # Spreadsheet formulas typed into names/notes must not execute when the file is opened.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def to_csv(sheets: dict) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for index, (title, (columns, rows)) in enumerate(sheets.items()):
        if index:
            writer.writerow([])
        if len(sheets) > 1:
            writer.writerow([title])
        writer.writerow([label for _, label in columns])
        for row in rows:
            writer.writerow([_safe_cell(row.get(key, "")) for key, _ in columns])
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")  # BOM so Excel reads Georgian text


def to_xlsx(sheets: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, (columns, rows) in sheets.items():
        sheet = workbook.create_sheet(title[:31])
        sheet.append([label for _, label in columns])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append([_safe_cell(row.get(key, "")) for key, _ in columns])
        for index, (_, label) in enumerate(columns, start=1):
            sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = max(14, len(label) + 2)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _ka_status(row, key="payment_status"):
    return PAYMENT_STATUS_KA.get(row.get(key), row.get(key) or "")


def completed_sheets(rows) -> dict:
    flat = []
    for row in rows:
        for item in row["items"] or [{}]:
            flat.append({
                **row, "product": item.get("name", ""), "quantity_line": item.get("quantity", ""),
                "unit_price": item.get("unit_price", ""), "line_total": item.get("line_total", ""),
                "payment_ka": _ka_status(row), "commission_ka": COMMISSION_STATUS_KA.get(row["commission_state"], ""),
                "created_day": _day(row["created_at"]) or "", "completed_day": _day(row["completed_at"]) or "",
            })
    columns = [
        ("order_no", "შეკვეთა"), ("store_name", "მაღაზია"), ("created_day", "შეკვეთის თარიღი"),
        ("completed_day", "დასრულების თარიღი"), ("product", "პროდუქტი"), ("quantity_line", "რაოდენობა"),
        ("unit_price", "ერთეულის ფასი"), ("line_total", "პროდუქტის ჯამი"), ("net_total", "შეკვეთის ჯამი"),
        ("payment_ka", "გადახდის სტატუსი"), ("commission", "საკომისიო"), ("commission_ka", "საკომისიოს მდგომარეობა"),
        ("net_after_commission", "ნეტო საკომისიოს შემდეგ"), ("invoice_no", "ინვოისი"),
    ]
    return {"დასრულებული შეკვეთები": (columns, flat)}


def analytics_sheets(data: dict) -> dict:
    kpi_labels = [
        ("total_sales", "ჯამური გაყიდვები"), ("orders", "შეკვეთები"), ("completed_orders", "დასრულებული"),
        ("average_order_value", "საშუალო შეკვეთა"), ("quantity", "გაყიდული რაოდენობა"),
        ("commission", "Distro საკომისიო"), ("net_revenue", "ნეტო შემოსავალი"),
    ]
    kpi_rows = [{"metric": label, "current": data["kpis"].get(key), "previous": (data["previous"] or {}).get(key, ""),
                 "change": (data["change"] or {}).get(key, "")} for key, label in kpi_labels]
    return {
        "მაჩვენებლები": ([("metric", "მაჩვენებელი"), ("current", "მიმდინარე"), ("previous", "წინა პერიოდი"), ("change", "ცვლილება %")], kpi_rows),
        "პროდუქტები": ([("name", "პროდუქტი"), ("quantity", "რაოდენობა"), ("orders", "შეკვეთები"), ("sales", "გაყიდვები"), ("commission", "საკომისიო")], data["products"]),
        "მაღაზიები": ([("store_name", "მაღაზია"), ("orders", "შეკვეთები"), ("quantity", "რაოდენობა"), ("sales", "გაყიდვები"), ("commission", "საკომისიო"), ("net_revenue", "ნეტო")], data["stores"]),
        "ტრენდი": ([("period", "პერიოდი"), ("orders", "შეკვეთები"), ("sales", "გაყიდვები"), ("commission", "საკომისიო")], data["series"]),
    }


def invoice_sheets(rows, summary, events) -> dict:
    invoice_rows = [{**r, "status_ka": _ka_status(r), "created_day": _day(r["created_at"]) or "",
                     "due_day": _day(r["due_date"]) or "", "commission_ka": COMMISSION_STATUS_KA.get(r["commission_state"], "")}
                    for r in rows]
    kinds = {"customer_payment": "მაღაზიის გადახდა", "payout": "ჩაწერილი ანგარიშსწორება", "commission_invoice": "საკომისიო ინვოისი"}
    event_rows = [{**e, "kind_ka": kinds.get(e["kind"], e["kind"]), "day": _day(e["at"]) or ""} for e in events]
    summary_rows = [{"metric": label, "value": summary.get(key)} for key, label in [
        ("completed_sales", "დასრულებული გაყიდვები"), ("commission", "Distro საკომისიო"),
        ("commission_percent", "ფაქტობრივი საკომისიო %"), ("net_after_commission", "ნეტო საკომისიოს შემდეგ"),
        ("paid", "გადახდილი"), ("unpaid", "გადაუხდელი"),
    ]]
    return {
        "ინვოისები": ([("invoice_no", "ინვოისი"), ("order_no", "შეკვეთა"), ("store_name", "მაღაზია"),
                       ("created_day", "შექმნა"), ("due_day", "გადახდის ვადა"), ("total", "თანხა"), ("paid", "გადახდილი"),
                       ("balance", "ნაშთი"), ("status_ka", "სტატუსი"), ("commission", "საკომისიო"),
                       ("commission_ka", "საკომისიოს მდგომარეობა")], invoice_rows),
        "ფინანსები": ([("metric", "მაჩვენებელი"), ("value", "მნიშვნელობა")], summary_rows),
        "ანგარიშსწორებები": ([("day", "თარიღი"), ("kind_ka", "ტიპი"), ("order_no", "შეკვეთა / ინვოისი"),
                              ("store_name", "მაღაზია"), ("amount", "თანხა"), ("method", "მეთოდი"),
                              ("status", "სტატუსი"), ("reference", "რეფერენსი")], event_rows),
    }
