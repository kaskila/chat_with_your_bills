"""Shared data models.

``ReceiptData`` is the normalized form of a receipt: what the pipeline produces
after validation, what is stored in the database, and what the ground-truth
files in ``eval/ground_truth`` describe.
"""

from typing import Literal, get_args

from pydantic import BaseModel, Field

Category = Literal[
    "Food",
    "Drinks",
    "Grocery",
    "Utilities",
    "Travel",
    "Logistics",
    "Office & Stationery",
    "Other",
]
CATEGORIES: tuple[str, ...] = get_args(Category)


class LineItem(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    amount: float
    category: Category = "Other"


class ReceiptData(BaseModel):
    vendor: str | None = None
    vendor_tax_id: str | None = None
    receipt_no: str | None = None
    date: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    time: str | None = Field(default=None, description="24-hour HH:MM")
    currency: str | None = None
    items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    discount: float | None = None
    service_charge: float | None = None
    tax: float | None = None
    total: float | None = None
    amount_paid: float | None = None
    change: float | None = None
    payment_method: str | None = None
    recipient: str | None = None  # who was paid, for mobile money payments (the vendor is the provider)
