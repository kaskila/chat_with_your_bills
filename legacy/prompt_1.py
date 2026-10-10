import json


JSON_SCHEMA = {
    "Invoice_No": "Invoice or receipt number, or Unknown.",
    "Issue_Date": "Explicitly stated invoice or receipt date, or Unknown.",
    "billed_to": "Explicitly identifiable customer/person being billed, or Unknown.",
    "billed_by": "Explicitly identifiable business/person issuing the bill, or Unknown.",
    "Description": "List of actual purchased goods or services.",
    "Amount": "Amount corresponding to each Description item.",
    "Grand_Total": "Explicitly stated final total, or Unknown."
}


def data_conversion(extracted_text: str) -> str:
    """
    Create a simple, conservative extraction prompt for Qwen.
    """

    schema_string = json.dumps(JSON_SCHEMA, indent=2)

    return f"""
/no_think

Extract invoice information from the OCR text below.

Return ONLY valid JSON.

Schema:
{schema_string}

IMPORTANT RULES:

1. Use ONLY information explicitly present in the OCR text.

2. NEVER guess, calculate, correct, or invent information.

3. If a field cannot be reliably identified, use:
   "Unknown"

4. Invoice_No:
   Only use a value explicitly associated with:
   Invoice No, Invoice Number, Invoice #,
   Receipt No, Receipt Number, Receipt #.

5. Issue_Date:
   Only use a date explicitly associated with:
   Date, Issue Date, Invoice Date, Receipt Date.

6. billed_to and billed_by:
   Only use a name when the OCR clearly identifies the party.
   Otherwise use "Unknown".

7. Description must contain ONLY actual goods or services.

8. NEVER use these as descriptions:
   Qty
   Quantity
   Unit
   Price
   Amount
   Description
   Subtotal
   VAT
   Tax
   Service Charge
   Discount
   Total
   Grand Total
   Change
   Paid Amount
   Balance

9. Numbers are NOT descriptions.

10. Amount must correspond one-to-one with Description.

11. Do NOT use quantity as Amount.

12. Do NOT use unit price as Amount when the receipt clearly provides
    a separate line amount.

13. Do NOT use VAT, tax, subtotal, service charge, discount,
    or change as an item Amount.

14. Do NOT calculate Grand_Total.

15. Grand_Total must only come from an explicitly stated total.

16. Description and Amount MUST have exactly the same number
    of elements.

17. If no reliable line items can be identified:
    "Description": []
    "Amount": []

18. Preserve OCR values. Do not silently correct OCR mistakes.

19. Do not add fields.

20. Do not output explanations or reasoning.

RAW OCR TEXT:

{extracted_text}

Return ONLY JSON.
"""
