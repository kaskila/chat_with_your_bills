import os
import pytesseract


# ---------------------------------------------------------
# TESSERACT CONFIGURATION
# ---------------------------------------------------------

# Tell pytesseract where the Tesseract executable is installed.
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


# ---------------------------------------------------------
# INPUT / OUTPUT
# ---------------------------------------------------------

# We tested both grayscale and threshold preprocessing.
#
# Grayscale performed better overall, so this is now our
# primary OCR input.
INPUT_FOLDER = "cleaned_bill_images/grayscale"

# All OCR results will be stored here.
OUTPUT_FILE = "extracted_text.txt"


# ---------------------------------------------------------
# OCR FUNCTION
# ---------------------------------------------------------

def perform_ocr(input_folder, output_file):

    # This stores OCR results from all receipts.
    all_extracted_text = ""


    # -----------------------------------------------------
    # CHECK INPUT FOLDER
    # -----------------------------------------------------

    if not os.path.exists(input_folder):

        print(
            f"ERROR: Input folder does not exist: "
            f"{input_folder}"
        )

        return


    # -----------------------------------------------------
    # PROCESS EACH IMAGE
    # -----------------------------------------------------

    for filename in os.listdir(input_folder):

        # Only process image files.
        if not filename.lower().endswith(
            (".jpg", ".jpeg", ".png")
        ):
            continue


        # Build the complete path to the image.
        image_path = os.path.join(
            input_folder,
            filename
        )


        try:

            # -------------------------------------------------
            # RUN TESSERACT
            # -------------------------------------------------
            #
            # PSM 4:
            #
            # Assume the image contains multiple columns or
            # blocks of text.
            #
            # This performed best overall on our receipt tests.

            text = pytesseract.image_to_string(
                image_path,
                config="--psm 4"
            )


            # -------------------------------------------------
            # CLEAN BASIC WHITESPACE
            # -------------------------------------------------

            cleaned_text = text.strip()


            # -------------------------------------------------
            # DISPLAY RESULT
            # -------------------------------------------------

            print("-" * 60)

            print(f"File: {filename}")

            print(cleaned_text)

            print("-" * 60)


            # -------------------------------------------------
            # ADD TO MASTER OCR FILE
            # -------------------------------------------------

            all_extracted_text += (
                f"\n-- Text from {filename} --\n"
                f"{cleaned_text}\n"
            )


        except Exception as e:

            print(
                f"Error processing {filename}: {e}"
            )


    # ---------------------------------------------------------
    # SAVE OCR RESULTS
    # ---------------------------------------------------------

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(all_extracted_text)


    print()
    print(
        f"Complete. OCR text saved to: {output_file}"
    )


# ---------------------------------------------------------
# PROGRAM ENTRY POINT
# ---------------------------------------------------------

if __name__ == "__main__":

    perform_ocr(
        INPUT_FOLDER,
        OUTPUT_FILE
    )