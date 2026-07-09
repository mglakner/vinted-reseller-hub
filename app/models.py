from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel

# Status values: draft (bought, not listed), active, offer, sold, kept
STATUSES = ["draft", "active", "offer", "sold", "kept"]
STATUS_LABELS = {
    "draft": "Not listed",
    "active": "Active",
    "offer": "Offer received",
    "sold": "Sold",
    "kept": "Kept",
}


class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    brand: str = ""
    category: str = ""
    condition: str = ""
    purchase_price: float = 0.0
    purchase_date: Optional[date] = None
    purchase_date_raw: str = ""  # original tekst hvis datoen ikke kunne tolkes
    bump_cost: float = 0.0  # penge brugt på Vinted-bump

    expected_price: Optional[float] = None
    list_price: Optional[float] = None
    listed_date: Optional[date] = None

    vinted_id: Optional[str] = Field(default=None, index=True)
    vinted_url: str = ""
    status: str = Field(default="draft", index=True)
    views: int = 0
    likes: int = 0
    offer_count: int = 0
    highest_offer: Optional[float] = None

    sale_price: Optional[float] = None
    sale_date: Optional[date] = None
    vinted_fee: float = 0.0
    shipping_cost: float = 0.0

    needs_review: bool = False
    review_note: str = ""
    notes: str = ""
    created_at: datetime = Field(default_factory=datetime.now)

    @property
    def net_profit(self) -> Optional[float]:
        if self.sale_price is None:
            return None
        return self.sale_price - self.purchase_price - self.bump_cost - self.vinted_fee - self.shipping_cost

    @property
    def roi(self) -> Optional[float]:
        p = self.net_profit
        cost = self.purchase_price + self.bump_cost
        if p is None or cost <= 0:
            return None
        return 100.0 * p / cost

    @property
    def days_to_sale(self) -> Optional[int]:
        if self.sale_date and self.listed_date and self.sale_date >= self.listed_date:
            return (self.sale_date - self.listed_date).days
        return None

    @property
    def days_listed(self) -> Optional[int]:
        if self.status in ("active", "offer") and self.listed_date:
            return (date.today() - self.listed_date).days
        return None

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


class ItemImage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: int = Field(index=True, foreign_key="item.id")
    kind: str = "raw"  # raw | generated
    filename: str = ""
    shot_key: str = ""  # hvilken shot-type (kun for genererede), fx "01_flat_lay"
    gen_status: str = "none"  # none | pending | generating | done | error
    gen_error: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


class Expense(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    amount: float
    spent_date: Optional[date] = None


class JobRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_name: str = Field(index=True)
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    ok: Optional[bool] = None
    message: str = ""


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str = ""
