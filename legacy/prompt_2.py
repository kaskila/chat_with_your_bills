
# Predefined expense categories
CATEGORIES = [
    "Food",
    "Logistics",
    "Drinks",
    "Travel",
    "Grocery Expense",
    "Utilities",
    "Other",
]


def build_category_prompt(description_text: str) -> str:
    """
    Build a strict prompt for classifying an expense description
    into exactly one predefined category.

    Args:
        description_text (str):
            The expense or service description.

    Returns:
        str:
            A formatted classification prompt.
    """

    return f"""
/no_think

You are a strict expense classification system.

Your task is to classify the expense description into EXACTLY ONE
of the allowed categories below.

ALLOWED CATEGORIES:
- Food
- Logistics
- Drinks
- Travel
- Grocery Expense
- Utilities
- Other


CATEGORY DEFINITIONS:

Food:
- Prepared meals
- Restaurant meals
- Takeaway food
- Fast food
- Breakfast, lunch, or dinner
- Snacks
- Catering
- Food purchased to be eaten

Logistics:
- Delivery services
- Courier services
- Shipping
- Freight
- Transportation of goods
- Parcel delivery
- Moving or transporting products

Drinks:
- Soft drinks
- Bottled water
- Juice
- Coffee
- Tea
- Beer
- Wine
- Other beverages purchased as drinks

Travel:
- Air tickets
- Bus tickets
- Train tickets
- Taxi rides
- Travel fares
- Hotel accommodation while travelling
- Travel-related accommodation
- Travel expenses
- Business or personal travel costs

Grocery Expense:
- Supermarket purchases
- Groceries
- Raw food ingredients
- Cooking ingredients
- Fruits
- Vegetables
- Meat
- Household food items
- General grocery shopping

Utilities:
- Electricity bills
- Water bills
- Internet bills
- Telephone bills
- Mobile phone bills
- Waste collection
- Rent
- Rental payments
- Housing bills
- Recurring household or business bills

Other:
- Expenses that do not clearly belong to any category above
- Expenses where there is insufficient information to determine
  a more specific category


IMPORTANT CLASSIFICATION RULES:

1. Return EXACTLY ONE category.

2. Your response MUST be exactly one of these values:

Food
Logistics
Drinks
Travel
Grocery Expense
Utilities
Other

3. Return ONLY the category name.

4. Do NOT provide an explanation.

5. Do NOT provide reasoning.

6. Do NOT use quotes.

7. Do NOT use Markdown.

8. Do NOT add punctuation.

9. Do NOT return multiple categories.

10. Rent and rental payments MUST be classified as Utilities.

11. Electricity, water, internet, telephone, and waste collection
    MUST be classified as Utilities.

12. Restaurant meals and prepared food MUST be classified as Food.

13. Supermarket and grocery purchases MUST be classified as
    Grocery Expense.

14. Delivery and courier services MUST be classified as Logistics.

15. Travel tickets and travel accommodation MUST be classified
    as Travel.

16. Drinks purchased as beverages MUST be classified as Drinks.

17. If the description does not provide enough information to
    confidently select a category, return Other.


EXPENSE DESCRIPTION:
{description_text}


CATEGORY:
""".strip()
