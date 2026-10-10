import cv2
import os


# ---------------------------------------------------------
# FOLDERS
# ---------------------------------------------------------

input_folder = "bill_image"

# We will create two different preprocessing outputs.
grayscale_folder = "cleaned_bill_images/grayscale"
threshold_folder = "cleaned_bill_images/threshold"


# ---------------------------------------------------------
# CREATE OUTPUT FOLDERS
# ---------------------------------------------------------

os.makedirs(grayscale_folder, exist_ok=True)
os.makedirs(threshold_folder, exist_ok=True)


def image_cleaning(input_folder, grayscale_folder, threshold_folder):

    # Supported image formats
    valid_extensions = (".jpg", ".jpeg", ".png")

    converted_count = 0


    # -----------------------------------------------------
    # LOOP THROUGH ALL IMAGES
    # -----------------------------------------------------

    for filename in os.listdir(input_folder):

        if not filename.lower().endswith(valid_extensions):
            continue


        input_path = os.path.join(
            input_folder,
            filename
        )


        try:

            # -------------------------------------------------
            # STEP 1: READ IMAGE
            # -------------------------------------------------

            color_image = cv2.imread(input_path)


            if color_image is None:

                print(f"Could not read: {filename}")
                continue


            # -------------------------------------------------
            # STEP 2: CONVERT TO GRAYSCALE
            # -------------------------------------------------

            gray_image = cv2.cvtColor(
                color_image,
                cv2.COLOR_BGR2GRAY
            )


            # -------------------------------------------------
            # STEP 3: UPSCALE THE IMAGE
            # -------------------------------------------------
            #
            # Your receipt images are relatively small.
            #
            # Upscaling does NOT create new information,
            # but it gives OCR more pixels to work with.
            #
            # INTER_CUBIC is useful for enlarging text.

            upscaled_image = cv2.resize(
                gray_image,
                None,
                fx=2,
                fy=2,
                interpolation=cv2.INTER_CUBIC
            )


            # -------------------------------------------------
            # STEP 4: IMPROVE LOCAL CONTRAST
            # -------------------------------------------------
            #
            # CLAHE = Contrast Limited Adaptive Histogram
            # Equalization.
            #
            # This can help reveal faint receipt characters
            # without aggressively destroying the background.

            clahe = cv2.createCLAHE(
                clipLimit=2.0,
                tileGridSize=(8, 8)
            )

            enhanced_image = clahe.apply(
                upscaled_image
            )


            # -------------------------------------------------
            # STEP 5: LIGHT DENOISING
            # -------------------------------------------------
            #
            # We use a very small median filter.
            #
            # Unlike your previous Gaussian blur, we don't
            # want to heavily soften the characters.

            denoised_image = cv2.medianBlur(
                enhanced_image,
                3
            )


            # -------------------------------------------------
            # STEP 6: ADAPTIVE THRESHOLD
            # -------------------------------------------------
            #
            # Receipts often have:
            #
            # - shadows
            # - folds
            # - uneven lighting
            # - grey paper
            #
            # A global Otsu threshold can therefore remove
            # faint characters.
            #
            # Adaptive threshold calculates the threshold
            # locally.

            binary_image = cv2.adaptiveThreshold(
                denoised_image,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                10
            )


            # -------------------------------------------------
            # STEP 7: SAVE GRAYSCALE VERSION
            # -------------------------------------------------
            #
            # This version keeps more information.
            #
            # This is important because sometimes Tesseract
            # performs better on grayscale than binary images.

            grayscale_output_path = os.path.join(
                grayscale_folder,
                filename
            )

            cv2.imwrite(
                grayscale_output_path,
                denoised_image
            )


            # -------------------------------------------------
            # STEP 8: SAVE BINARY VERSION
            # -------------------------------------------------
            #
            # This version has stronger separation between
            # text and background.

            threshold_output_path = os.path.join(
                threshold_folder,
                filename
            )

            cv2.imwrite(
                threshold_output_path,
                binary_image
            )


            converted_count += 1

            print(
                f"Processed {converted_count}: {filename}"
            )


        except Exception as e:

            print(
                f"Failed to process {filename}: {e}"
            )


# ---------------------------------------------------------
# RUN PROGRAM
# ---------------------------------------------------------

if __name__ == "__main__":

    image_cleaning(
        input_folder,
        grayscale_folder,
        threshold_folder
    )

    print()
    print("Image preprocessing completed.")