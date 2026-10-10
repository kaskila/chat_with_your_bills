
import sqlite3

# -------------------------------------------------------------
# DATABASE CONFIGURATION
# -------------------------------------------------------------

DB_NAME = "ocr_master.db"


# -------------------------------------------------------------
# CONNECT TO DATABASE
# -------------------------------------------------------------

connection = sqlite3.connect(DB_NAME)
cursor = connection.cursor()


# -------------------------------------------------------------
# CHECK TABLES
# -------------------------------------------------------------

tables = cursor.execute(
    "SELECT name FROM sqlite_master WHERE type='table';"
).fetchall()

print("Tables in database:")

for table in tables:
    print(f"- {table[0]}")


# -------------------------------------------------------------
# CHECK OCR LINE ITEMS TABLE
# -------------------------------------------------------------

columns = cursor.execute(
    "PRAGMA table_info(ocr_line_items);"
).fetchall()

print("\nColumns in ocr_line_items:")

for column in columns:

    column_id = column[0]
    column_name = column[1]
    data_type = column[2]
    not_null = column[3]
    primary_key = column[5]

    print(
        f"{column_id}: "
        f"{column_name} | "
        f"{data_type} | "
        f"NOT NULL={not_null} | "
        f"PRIMARY KEY={primary_key}"
    )


# -------------------------------------------------------------
# CLOSE DATABASE
# -------------------------------------------------------------

connection.close()

print("\nDatabase connection closed.")

