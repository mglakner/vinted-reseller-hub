"""Export the whole ledger to a single xlsx file (for taxes/backup)."""
import io
from datetime import datetime

import openpyxl
from openpyxl.styles import Font
from sqlmodel import Session, select

from .metrics import compute_dashboard
from .models import Expense, Item

HEADERS = [
    "Item", "Brand", "Category", "Condition", "Date bought", "Purchase price", "Bump cost",
    "List price", "Listing date", "Status", "Views", "Likes", "Offers", "Highest offer",
    "Sale price", "Sale date", "Vinted fee", "Shipping", "Net profit", "ROI %",
]


def export_xlsx(session: Session) -> bytes:
    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "Items"
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for i in session.exec(select(Item).order_by(Item.id)):
        ws.append([
            i.name, i.brand, i.category, i.condition, i.purchase_date,
            i.purchase_price, i.bump_cost, i.list_price, i.listed_date,
            i.status_label, i.views, i.likes, i.offer_count, i.highest_offer,
            i.sale_price, i.sale_date, i.vinted_fee, i.shipping_cost,
            round(i.net_profit, 2) if i.net_profit is not None else None,
            round(i.roi, 1) if i.roi is not None else None,
        ])
    ws.freeze_panes = "A2"

    ws2 = wb.create_sheet("Expenses")
    ws2.append(["Item", "Amount"])
    ws2["A1"].font = ws2["B1"].font = Font(bold=True)
    for e in session.exec(select(Expense).order_by(Expense.id)):
        ws2.append([e.name, e.amount])

    d = compute_dashboard(session)
    ws3 = wb.create_sheet("Summary")
    rows = [
        ("Exported", datetime.now().strftime("%d-%m-%Y %H:%M")),
        ("Total bought", d.total_bought),
        ("Sold", d.total_sold),
        ("Active listings", d.total_active),
        ("Total invested", round(d.total_invested, 2)),
        ("Total revenue", round(d.total_revenue, 2)),
        ("Net profit", round(d.net_profit, 2)),
        ("Other expenses", round(d.total_expenses, 2)),
        ("Overall profit", round(d.overall_profit, 2)),
    ]
    for label, value in rows:
        ws3.append([label, value])
        ws3[f"A{ws3.max_row}"].font = Font(bold=True)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
