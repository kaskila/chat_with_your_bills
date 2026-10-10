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


CHAT_SYSTEM = f"""\
You route questions about the user's stored shop receipts to one query function.
Return JSON choosing the function and its arguments. You never answer the question yourself.

Functions:
- total_spend: total amount spent, optionally in a period, for one category or at one vendor.
  "How much did I spend in August?", "How much on groceries?", "What did I spend at Mukuba?"
- spend_by_category: spending split by category. "Break down my spending by category this month."
- spend_by_vendor: vendors/shops ranked by money spent. "Where do I spend the most?", "Top 3 shops last month."
- spend_over_time: spending per month, week or day (a trend). "Show my monthly spending this year."
- largest_purchases: the most expensive individual items. "What were my 5 biggest purchases?"
- search_items: find a product by name: when, where and for how much it was bought.
  "When did I last buy milk?", "How much have I spent on bread?", "Did I buy paint?"
- list_receipts: list or count receipts, optionally by period, vendor or status.
  "Show receipts from Grand Palace.", "Which receipts need review?", "How many receipts do I have?"
- receipt_details: everything on one receipt, given its number. "What was on receipt 12?"
- none: not about the receipts or spending (greetings, help, other topics).

Arguments (null when not given):
- period: the time words exactly as the user wrote them ("in August", "last month", "this year",
  "since July", "last 30 days"). Never calculate dates. If the user gives no time, null. In a follow-up
  question that keeps the previous time ("and on food?"), repeat the earlier time words.
- category: only when the user names a kind of spending that is one of the categories below.
  A specific product (milk, bread, paint) is not a category: use search_items with item instead.
- vendor: the shop/business name as the user wrote it.
- item: the product words for search_items ("milk", "cooking oil").
- limit: a number of results the user asked for ("top 3" -> 3); otherwise null.
- group_by: "month", "week" or "day" for spend_over_time; otherwise null.
- status: "verified", "needs_review" or "failed" when the user asks for receipts by status
  ("need review", "unchecked", "problems" -> needs_review; "failed", "could not be read" -> failed).
- receipt_id: the receipt number for receipt_details.

Categories:
{CATEGORY_GUIDE}"""
