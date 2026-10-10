
# -------------------------------------------------------------
# IMPORT REQUIRED LIBRARIES AND FUNCTIONS
# -------------------------------------------------------------

# os is used to check whether the OCR output file exists.
import os

# json is used to format and display the final structured
# invoice data in a readable JSON format.
import json

# Agent 1:
# This function sends the OCR text to the extraction model
# and returns structured invoice information as a dictionary.
from ollama_1 import get_json_from_prompt

# Agent 2:
# This function takes an individual expense/service description
# and classifies it into one of the predefined expense categories.
from ollama_2 import get_category_from_ollama


# -------------------------------------------------------------
# OCR OUTPUT CONFIGURATION
# -------------------------------------------------------------

# This is the file produced by the OCR processing step.
#
# It contains the extracted text from all processed bills.
OCR_OUTPUT_FILE = "extracted_text.txt"


# -------------------------------------------------------------
# PARSE MULTIPLE INVOICES
# -------------------------------------------------------------

def parse_multiple_invoices():
    """
    Read the OCR output file, separate individual invoices,
    extract structured information from each invoice, and
    classify each invoice line item.

    Returns:
        list:
            A list containing the structured data for all
            successfully processed invoices.
    """

    # Display a message showing that invoice processing has started.
    print(f"Parsing started...")


    # ---------------------------------------------------------
    # CHECK WHETHER THE OCR FILE EXISTS
    # ---------------------------------------------------------

    # Before attempting to read the OCR output file, check
    # whether the file actually exists.
    if not os.path.exists(OCR_OUTPUT_FILE):

        # Display an error message if the file cannot be found.
        print(
            f"OCR file not found at {OCR_OUTPUT_FILE}"
        )

        # Return an empty list because there is no OCR data
        # available to process.
        return []


    # ---------------------------------------------------------
    # READ THE OCR OUTPUT FILE
    # ---------------------------------------------------------

    # Open the OCR text file using UTF-8 encoding.
    with open(
        OCR_OUTPUT_FILE,
        'r',
        encoding='utf8'
    ) as f:

        # Read the entire OCR file into memory.
        master_text = f.read()


    # ---------------------------------------------------------
    # SPLIT THE OCR TEXT INTO INDIVIDUAL BILLS
    # ---------------------------------------------------------

    # The OCR file contains a marker before each bill:
    #
    # -- Text from filename --
    #
    # We use this marker to separate the OCR text into
    # individual invoice sections.
    bill_section = master_text.split("-- Text from ")[1:]


    # Count how many individual bills were found.
    total_bills = len(bill_section)

    # Display the number of bills that will be processed.
    print(
        f"Total bills to process: {total_bills}"
    )


    # ---------------------------------------------------------
    # CREATE A LIST TO STORE ALL PROCESSED INVOICES
    # ---------------------------------------------------------

    # This list will contain the final structured data for
    # every successfully processed invoice.
    all_structured_list = []


    # ---------------------------------------------------------
    # PROCESS EACH BILL
    # ---------------------------------------------------------

    # Loop through every invoice section extracted from
    # the OCR output file.
    for section in bill_section:

        # Use try/except so that if one invoice causes an error,
        # processing can continue with the remaining invoices.
        try:

            # -------------------------------------------------
            # EXTRACT FILENAME AND BILL CONTENT
            # -------------------------------------------------

            # Extract the filename from the section.
            #
            # Example:
            # bill_1.png
            filename = section.split("--")[0].strip()


            # Extract the actual OCR text belonging to that bill.
            bill_text = section.split(
                "--",
                1
            )[1].strip()


            # Display which bill is currently being processed.
            print(
                f"\n🧠 Processing: {filename}"
            )


            # -------------------------------------------------
            # AGENT 1 — INVOICE DATA EXTRACTION
            # -------------------------------------------------

            # Send the OCR text to Agent 1.
            #
            # Agent 1 converts unstructured OCR text into
            # structured invoice information.
            structured_data_dict = get_json_from_prompt(
                bill_text
            )


            # -------------------------------------------------
            # PROCESS EXTRACTED DATA
            # -------------------------------------------------

            # Check whether Agent 1 successfully returned data.
            if structured_data_dict:

                # Extract the list of descriptions from the
                # structured invoice data.
                description_list = structured_data_dict.get(
                    'Description',
                    []
                )


                # Extract the corresponding list of amounts.
                amount_list = structured_data_dict.get(
                    'Amount',
                    []
                )


                # This list will contain the descriptions after
                # they have been enriched with their categories.
                enriched_descriptions = []


                # -------------------------------------------------
                # AGENT 2 — EXPENSE CATEGORIZATION
                # -------------------------------------------------

                # Each description is paired with its corresponding
                # amount using zip().
                #
                # Example:
                #
                # Description:
                # ["Electricity", "Lunch"]
                #
                # Amount:
                # [500, 150]
                #
                # zip() creates:
                #
                # ("Electricity", 500)
                # ("Lunch", 150)
                for desc_item_raw, amt in zip(
                    description_list,
                    amount_list
                ):

                    # Convert the description to a string and
                    # remove unnecessary spaces.
                    #
                    # This ensures the classification model receives
                    # clean text.
                    service_name = str(
                        desc_item_raw
                    ).strip()


                    # Display the expense currently being classified.
                    print(
                        f"   > Categorizing: {service_name}"
                    )


                    # Send the expense description to Agent 2.
                    #
                    # Agent 2 uses Qwen to classify the expense
                    # into one of the predefined categories.
                    category_label = get_category_from_ollama(
                        service_name
                    )


                    # -------------------------------------------------
                    # CREATE ENRICHED LINE ITEM
                    # -------------------------------------------------

                    # Combine the original description, amount,
                    # and AI-generated category into one dictionary.
                    enriched_item = {

                        # Original expense/service description.
                        'service_description': service_name,

                        # Amount associated with this line item.
                        'Amount': amt,

                        # Category assigned by Agent 2.
                        'Category': category_label
                    }


                    # Add the enriched line item to the list.
                    enriched_descriptions.append(
                        enriched_item
                    )


                # -------------------------------------------------
                # UPDATE THE STRUCTURED INVOICE DATA
                # -------------------------------------------------

                # Replace the original Description list with the
                # enriched list containing:
                #
                # - service description
                # - amount
                # - category
                structured_data_dict['Description'] = (
                    enriched_descriptions
                )


                # Store the original invoice filename so we know
                # which OCR file produced this invoice.
                structured_data_dict['source_file'] = (
                    filename
                )


                # Add the completed invoice to the master list.
                all_structured_list.append(
                    structured_data_dict
                )


            # -------------------------------------------------
            # HANDLE EXTRACTION FAILURE
            # -------------------------------------------------

            else:

                # Agent 1 did not return structured data.
                print(
                    f"❌ Failed to extract data for {filename}"
                )


        # ---------------------------------------------------------
        # HANDLE ERRORS FOR INDIVIDUAL BILLS
        # ---------------------------------------------------------

        except Exception as e:

            # Display the error but continue processing
            # the remaining invoices.
            print(
                f"⚠️ Error processing section: {e}"
            )


    # ---------------------------------------------------------
    # RETURN ALL PROCESSED INVOICES
    # ---------------------------------------------------------

    # Return the complete list of structured and categorized
    # invoices.
    return all_structured_list


# -------------------------------------------------------------
# PROGRAM ENTRY POINT
# -------------------------------------------------------------

# This block runs only when this Python file is executed
# directly.
#
# It will NOT run if the file is imported into another Python
# program.
if __name__ == "__main__":

    # Start the invoice parsing and categorization process.
    final_extracted_data = parse_multiple_invoices()


    # ---------------------------------------------------------
    # DISPLAY FINAL RESULTS
    # ---------------------------------------------------------

    # Confirm that processing has completed.
    print(
        "\n✅ Final List of Bills Generated!"
    )


    # Convert the Python list/dictionaries into nicely formatted
    # JSON and print the result.
    #
    # indent=4 makes the output easier to read.
    print(
        json.dumps(
            final_extracted_data,
            indent=4
        )
    )