
import sqlite3


# -------------------------------------------------------------
# DATABASE CONFIGURATION
# -------------------------------------------------------------

# Name of the SQLite database file.
DB_NAME = "ocr_master.db"


# -------------------------------------------------------------
# DATABASE CONNECTION
# -------------------------------------------------------------

connection = None

try:
    # Establish a connection to the SQLite database.
    #
    # If the database file does not exist, SQLite will
    # automatically create it.
    connection = sqlite3.connect(DB_NAME)

    # Create a cursor object.
    # The cursor is used to execute SQL statements.
    cursor = connection.cursor()


    # ---------------------------------------------------------
    # CREATE OCR LINE ITEMS TABLE
    # ---------------------------------------------------------
    #
    # This table stores the information extracted from
    # individual invoice line items after OCR processing.
    #
    # Each invoice can contain multiple line items.
    #
    # The combination of Invoice_No and line_item_id is used
    # as the primary key to uniquely identify each line item.
    # ---------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ocr_line_items (
            Invoice_No TEXT NOT NULL,
            line_item_id INTEGER NOT NULL,
            Issue_Date TEXT,
            billed_to TEXT,
            billed_by TEXT,
            Description TEXT,
            Category TEXT,
            Amount REAL,
            Grand_Total REAL,
            source_file TEXT,

            PRIMARY KEY (Invoice_No, line_item_id)
        )
    """)


    # ---------------------------------------------------------
    # SAVE CHANGES
    # ---------------------------------------------------------

    # Commit the transaction so that the table creation
    # is permanently saved to the database.
    connection.commit()

    print(
        f"Table 'ocr_line_items' successfully created "
        f"in '{DB_NAME}'."
    )


# -------------------------------------------------------------
# DATABASE ERROR HANDLING
# -------------------------------------------------------------

except sqlite3.Error as error:

    # Display the database error if something goes wrong.
    print(
        f"Database error: {error}"
    )


# -------------------------------------------------------------
# CLOSE DATABASE CONNECTION
# -------------------------------------------------------------

finally:

    # Close the database connection if it was successfully
    # established.
    if connection is not None:
        connection.close()

        print(
            "Database connection closed."
        )

### What I cleaned up

# * Changed `con` → `connection` and `cur` → `cursor` for readability.
# * Fixed comments and spelling.
# * Added clear sections for configuration, connection, table creation, commit, error handling, and closing.
# * Removed redundant comments like `#creating table: #creating table`.
# * Improved the success/error messages.
# * Kept your existing table structure and primary key unchanged.
# * Used `error` instead of the very short `e`, making the exception clearer.

# One small design point: **`Invoice_No + line_item_id` as the composite primary key is sensible** if `line_item_id` only needs to be unique *within an invoice*. If `line_item_id` is globally unique, the schema could be simplified later, but don't change it unless that matches how your OCR pipeline generates IDs.
