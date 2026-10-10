import os
import pytesseract


# ---------------------------------------------------------
# TESSERACT
# ---------------------------------------------------------

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


# ---------------------------------------------------------
# INPUT
# ---------------------------------------------------------

INPUT_FOLDER = "cleaned_bill_images/grayscale"


# ---------------------------------------------------------
# OCR TEST
# ---------------------------------------------------------

def test_psm_modes(input_folder):

    # These are the Tesseract page segmentation modes
    # we want to compare.
    psm_modes = [4, 6, 11]


    # -----------------------------------------------------
    # PROCESS EACH IMAGE
    # -----------------------------------------------------

    for filename in os.listdir(input_folder):

        if not filename.lower().endswith(
            (".jpg", ".jpeg", ".png")
        ):
            continue


        image_path = os.path.join(
            input_folder,
            filename
        )


        print()
        print("=" * 70)
        print(f"FILE: {filename}")
        print("=" * 70)


        # -------------------------------------------------
        # TEST EACH PSM MODE
        # -------------------------------------------------

        for psm in psm_modes:

            print()
            print("-" * 70)
            print(f"PSM {psm}")
            print("-" * 70)


            try:

                text = pytesseract.image_to_string(
                    image_path,
                    config=f"--psm {psm}"
                )


                print(text.strip())


            except Exception as e:

                print(
                    f"Error using PSM {psm}: {e}"
                )


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

if __name__ == "__main__":

    test_psm_modes(INPUT_FOLDER)