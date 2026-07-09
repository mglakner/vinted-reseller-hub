from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, select

from .models import Expense, Item

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class Dashboard:
    total_bought: int = 0
    total_sold: int = 0
    total_active: int = 0
    total_invested: float = 0.0
    total_revenue: float = 0.0
    net_profit: float = 0.0
    overall_profit: float = 0.0  # efter div. omkostninger
    avg_roi: float | None = None
    avg_days_to_sale: float | None = None
    best_profit: float | None = None
    total_expenses: float = 0.0
    stock_value: float = 0.0        # bundet i usolgte varer
    potential_revenue: float = 0.0  # sum af listepriser på aktive
    sell_through: float | None = None
    top_items: list[Item] = field(default_factory=list)
    stale_items: list[Item] = field(default_factory=list)
    review_items: list[Item] = field(default_factory=list)
    monthly_profit: list[tuple[str, float]] = field(default_factory=list)  # ("jun 26", 1234.0)


def suggest_price(item: Item) -> float | None:
    """Prisjusteringsforslag til hyldevarmere: -10 %, rundet ned til nærmeste 5 kr,
    aldrig under indkøbspris + 20 kr."""
    if not item.list_price:
        return None
    dropped = int(item.list_price * 0.9 // 5) * 5
    floor = item.purchase_price + item.bump_cost + 20
    return max(dropped, floor) if dropped < item.list_price else None


def monthly_profit_series(sold: list[Item], months: int = 6) -> list[tuple[str, float]]:
    today = date.today()
    keys = []
    y, m = today.year, today.month
    for _ in range(months):
        keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    keys.reverse()
    sums = {k: 0.0 for k in keys}
    for i in sold:
        if i.sale_date and (i.sale_date.year, i.sale_date.month) in sums:
            sums[(i.sale_date.year, i.sale_date.month)] += i.net_profit or 0
    return [(f"{MONTH_NAMES[m - 1]} {str(y)[2:]}", v) for (y, m), v in sums.items()]


@dataclass
class GroupStats:
    name: str
    bought: int = 0
    sold: int = 0
    invested: float = 0.0
    profit: float = 0.0
    rois: list[float] = field(default_factory=list)
    days: list[int] = field(default_factory=list)

    @property
    def avg_roi(self) -> float | None:
        return sum(self.rois) / len(self.rois) if self.rois else None

    @property
    def avg_days(self) -> float | None:
        return sum(self.days) / len(self.days) if self.days else None

    @property
    def sell_through(self) -> float:
        return 100.0 * self.sold / self.bought if self.bought else 0.0


def group_stats(items: list[Item], key) -> list[GroupStats]:
    groups: dict[str, GroupStats] = {}
    for i in items:
        name = (key(i) or "").strip() or "(ukendt)"
        g = groups.setdefault(name, GroupStats(name=name))
        g.bought += 1
        g.invested += i.purchase_price + i.bump_cost
        if i.status == "sold" and i.sale_price is not None:
            g.sold += 1
            g.profit += i.net_profit or 0
            if i.roi is not None:
                g.rois.append(i.roi)
            if i.days_to_sale is not None:
                g.days.append(i.days_to_sale)
    return sorted(groups.values(), key=lambda g: g.profit, reverse=True)


def compute_dashboard(session: Session) -> Dashboard:
    items = list(session.exec(select(Item)))
    d = Dashboard()
    d.total_bought = len(items)
    d.total_expenses = sum(e.amount for e in session.exec(select(Expense)))

    sold = [i for i in items if i.status == "sold" and i.sale_price is not None]
    d.total_sold = len(sold)
    d.total_active = sum(1 for i in items if i.status in ("active", "offer"))
    d.total_invested = sum(i.purchase_price + i.bump_cost for i in items)
    d.total_revenue = sum(i.sale_price or 0 for i in sold)
    d.net_profit = sum(i.net_profit or 0 for i in sold)
    d.overall_profit = d.net_profit - d.total_expenses

    rois = [i.roi for i in sold if i.roi is not None]
    d.avg_roi = sum(rois) / len(rois) if rois else None
    days = [i.days_to_sale for i in sold if i.days_to_sale is not None]
    d.avg_days_to_sale = sum(days) / len(days) if days else None
    profits = [i.net_profit for i in sold if i.net_profit is not None]
    d.best_profit = max(profits) if profits else None

    unsold = [i for i in items if i.status in ("draft", "active", "offer")]
    d.stock_value = sum(i.purchase_price + i.bump_cost for i in unsold)
    d.potential_revenue = sum(i.list_price or i.expected_price or 0 for i in unsold)
    d.sell_through = 100.0 * d.total_sold / d.total_bought if d.total_bought else None
    d.monthly_profit = monthly_profit_series(sold)

    d.top_items = sorted(sold, key=lambda i: i.net_profit or 0, reverse=True)[:5]
    d.stale_items = sorted(
        (i for i in items if (i.days_listed or 0) >= 30 and i.offer_count == 0),
        key=lambda i: i.days_listed or 0,
        reverse=True,
    )[:8]
    d.review_items = [i for i in items if i.needs_review]
    return d
