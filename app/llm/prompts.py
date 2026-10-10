"""Prompts for the local LLM.

The extraction system prompt is identical on every call so Ollama can reuse its
cached prompt prefix while the model stays loaded.
"""

CATEGORY_GUIDE = """\
- Drinks: soft drinks, water, juice, milkshakes, smoothies, coffee, tea, beer, wine, any beverage.
- Food: prepared meals, restaurant or takeaway food, snacks, catering.
- Grocery: supermarket shopping, raw ingredients, fruit, vegetables, meat, household food items.
- Utilities: electricity, water, internet, phone/airtime, waste collection, rent.
- Travel: bus/train/air tickets, taxi, fuel for travel, hotel accommodation.
- Logistics: delivery, courier, shipping, freight, transporting goods.
- Office & Stationery: printing, binding, paper, pens, office supplies, photocopies.
- Other: everything that is not food, drinks, groceries, utilities, travel, logistics or stationery, e.g.
  medicine and pharmacy items, hardware, paint and tools, clothing and shoes, phones, electronics and
  accessories, beauty and salon services, repairs and labour, cinema and entertainment tickets,
  or when the description is too vague to tell (e.g. "goods")."""

EXTRACTION_SYSTEM = f"""\
You read OCR text from a photographed shop receipt or invoice and return its data as JSON.
The OCR text may contain reading errors and lines in a jumbled order.

Rules:
1. Use only information printed on the receipt. Use null for anything not printed. Never invent values.
2. Copy numbers exactly as printed, without currency symbols. Never change digits.
   You may fix obvious OCR letter mistakes in words (e.g. "LIMTTED" -> "LIMITED", "Payabie" -> "Payable").
3. Never calculate anything: do not multiply, add or round. Every number you return must appear in the text.
4. items: every line that charges money for goods or services, including fees such as waiting time,
   labour or delivery. Never list totals, subtotal, tax, VAT, service charge, discounts or promotions,
   cash paid, change, balance, payment type or item counts as items.
5. amount: the money amount printed on that item's line (usually the last number on the line), copied as is.
   quantity and unit_price: only when printed; otherwise null.
6. vendor: the business name printed at the top of the receipt (often the first line, in large letters).
   Not a street address, shop or unit number, phone number or website.
7. vendor_tax_id: only a number labelled TPIN, TIN, VAT No or Tax ID; otherwise null.
8. receipt_no: the main receipt or invoice number (labelled Receipt #, Receipt No, Invoice No, NO:).
9. date and time: copy as printed.
10. currency: as printed (e.g. "K", "ZMW", "USD"), or null.
11. subtotal: only an amount labelled Subtotal, Net Amount or Excl Total; if no such line is printed, null.
    tax: the total tax/VAT amount printed. service_charge: only if printed.
    discount: a printed discount or promotion, as a positive number (even if printed as -79.00).
12. total: the final amount payable as printed (labelled Total, Sale Total, Payable, Amount Due, Grand Total).
    Not the cash handed over, the change, or an item count (a "Total" followed by a small whole number
    equal to the number of items is a count). If no final amount is printed, use null.
13. amount_paid: money handed over (Cash, Paid Amount, Tendered). change: change given back. null if not printed.
14. payment_method: Cash, Card, Mobile Money, etc. if printed; otherwise null.
15. category: choose one per item. Every beverage is Drinks, even in a restaurant (milkshakes, juice, soda).
{CATEGORY_GUIDE}"""


def extraction_user_message(ocr_text: str) -> str:
    return f"OCR text of the receipt:\n<<<\n{ocr_text.strip()}\n>>>"
