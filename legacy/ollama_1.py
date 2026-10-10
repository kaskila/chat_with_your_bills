
# Import the data_conversion function from prompt_1.py.
#
# This function is responsible for creating the prompt that
# will be sent to the Ollama language model.
from prompt_1 import data_conversion


# subprocess allows Python to run external programs/commands.
#
# We use it to start Ollama and communicate with the local model.
import subprocess


# re (Regular Expressions) is used to find and extract
# useful parts of the model's response.
#
# In this file we mainly use it to:
# - remove Markdown code fences
# - locate the beginning/end of JSON
import re


# json provides functions for converting JSON text into
# Python dictionaries.
import json


# Any allows us to describe dictionaries whose values can
# contain different Python data types.
from typing import Any


def extract_json_object(model_output: str) -> str:
    """
    Extract the JSON object from Ollama's response.

    Ollama may return something like:

        Thinking...
        I need to inspect the invoice...
        ...done thinking.

        {
            "Invoice_No": "1234567",
            "Description": ["Item 1"],
            "Amount": [100]
        }

    json.loads() cannot process the text before the '{'.

    This function therefore searches for the actual JSON object
    and returns only that portion.

    Args:
        model_output (str):
            Raw text returned by Ollama.

    Returns:
        str:
            Extracted JSON object as a string.

    Raises:
        ValueError:
            If no JSON object can be found.
    """

    # ---------------------------------------------------------
    # STEP 1: Remove unnecessary whitespace
    # ---------------------------------------------------------
    cleaned_output = model_output.strip()

    if not cleaned_output:
        raise ValueError(
            "Ollama returned an empty response."
        )


    # ---------------------------------------------------------
    # STEP 2: Remove Markdown code fences
    # ---------------------------------------------------------
    #
    # Sometimes an LLM returns:
    #
    # ```json
    # {
    #     ...
    # }
    # ```
    #
    # These ``` markers are not part of JSON itself.
    #
    # We therefore remove them before trying to locate the
    # JSON object.

    cleaned_output = re.sub(
        r"```(?:json)?",
        "",
        cleaned_output,
        flags=re.IGNORECASE
    )

    cleaned_output = cleaned_output.replace("```", "").strip()


    # ---------------------------------------------------------
    # STEP 3: Find the first JSON object
    # ---------------------------------------------------------
    #
    # A JSON object begins with:
    #
    # {
    #
    # and ends with:
    #
    # }
    #
    # The model may have produced text before the JSON, such as:
    #
    # Thinking...
    # Here is the extracted invoice...
    #
    # We do NOT want that text.
    #
    # We therefore find the first '{'.

    first_brace = cleaned_output.find("{")

    if first_brace == -1:
        raise ValueError(
            "No JSON object was found in Ollama's response."
        )


    # ---------------------------------------------------------
    # STEP 4: Find the matching closing brace
    # ---------------------------------------------------------
    #
    # We cannot simply use:
    #
    #     cleaned_output.rfind("}")
    #
    # because we want a more controlled extraction.
    #
    # Instead, we walk through the response and keep track
    # of opening and closing braces.
    #
    # This also helps when JSON contains nested objects.

    brace_count = 0

    in_string = False
    escape_next = False

    json_end = None


    for index in range(first_brace, len(cleaned_output)):

        character = cleaned_output[index]


        # -----------------------------------------------------
        # Handle escaped characters inside JSON strings.
        # -----------------------------------------------------
        #
        # Example:
        #
        # "description": "Product \"A\""
        #
        # The escaped quote should not terminate the string.

        if escape_next:
            escape_next = False
            continue


        if character == "\\" and in_string:
            escape_next = True
            continue


        # -----------------------------------------------------
        # Detect whether we are currently inside a JSON string.
        # -----------------------------------------------------
        if character == '"':
            in_string = not in_string
            continue


        # -----------------------------------------------------
        # Ignore braces that appear inside strings.
        # -----------------------------------------------------
        if in_string:
            continue


        # -----------------------------------------------------
        # Count opening braces.
        # -----------------------------------------------------
        if character == "{":
            brace_count += 1


        # -----------------------------------------------------
        # Count closing braces.
        # -----------------------------------------------------
        elif character == "}":
            brace_count -= 1


            # When the count returns to zero, we have found
            # the end of the JSON object.
            if brace_count == 0:
                json_end = index + 1
                break


    # ---------------------------------------------------------
    # STEP 5: Make sure a complete JSON object was found.
    # ---------------------------------------------------------

    if json_end is None:
        raise ValueError(
            "A JSON object started in Ollama's response, "
            "but no matching closing brace was found."
        )


    # ---------------------------------------------------------
    # STEP 6: Extract only the JSON portion.
    # ---------------------------------------------------------

    json_string = cleaned_output[first_brace:json_end].strip()


    # ---------------------------------------------------------
    # STEP 7: Return the extracted JSON string.
    # ---------------------------------------------------------

    return json_string


def get_json_from_prompt(raw_invoice_text: str) -> dict[str, Any]:
    """
    Send invoice text to Ollama and convert the model's
    response into a Python dictionary.

    Args:
        raw_invoice_text (str):
            OCR text extracted from an invoice.

    Returns:
        dict[str, Any]:
            Structured invoice information returned by Ollama.

    Raises:
        RuntimeError:
            If Ollama itself fails.

        ValueError:
            If Ollama does not return valid JSON.
    """


    # ---------------------------------------------------------
    # STEP 1: Create the LLM prompt
    # ---------------------------------------------------------
    #
    # The OCR invoice text is passed to data_conversion().
    #
    # That function contains the instructions that tell
    # the LLM how the invoice should be converted into JSON.

    prompt = data_conversion(raw_invoice_text)


    # ---------------------------------------------------------
    # STEP 2: Start Ollama
    # ---------------------------------------------------------
    #
    # We run the same model currently being used by your
    # classification system:
    #
    #     qwen3:0.6b
    #
    # stdin  -> sends the prompt to Ollama
    # stdout -> receives the model's response
    # stderr -> receives Ollama error messages

    try:

        process = subprocess.Popen(
            [
                "ollama",
                "run",
                "qwen3:4b",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    except FileNotFoundError:

        raise RuntimeError(
            "Ollama was not found in PATH. "
            "Make sure Ollama is installed and available."
        )

    except Exception as error:

        raise RuntimeError(
            f"Failed to start Ollama: {error}"
        )


    # ---------------------------------------------------------
    # STEP 3: Send the prompt to Ollama
    # ---------------------------------------------------------
    #
    # communicate() sends the prompt to Ollama and waits
    # until the model finishes generating its response.

    try:

        output, error = process.communicate(
            input=prompt
        )

    except Exception as error:

        try:
            process.kill()
        except Exception:
            pass

        raise RuntimeError(
            f"Failed while communicating with Ollama: {error}"
        )


    # ---------------------------------------------------------
    # STEP 4: Check whether Ollama executed successfully
    # ---------------------------------------------------------

    if process.returncode != 0:

        raise RuntimeError(
            f"Ollama failed with exit code "
            f"{process.returncode}.\n\n"
            f"Ollama error:\n{error.strip()}"
        )


    # ---------------------------------------------------------
    # STEP 5: Make sure Ollama returned something
    # ---------------------------------------------------------

    if not output or not output.strip():

        raise ValueError(
            "Ollama returned an empty response."
        )


    # ---------------------------------------------------------
    # STEP 6: Extract the JSON object
    # ---------------------------------------------------------
    #
    # This is the important fix.
    #
    # Instead of assuming the entire Ollama response is JSON,
    # we search for the actual JSON object.
    #
    # This allows responses such as:
    #
    # Thinking...
    # ...done thinking.
    #
    # {
    #     ...
    # }
    #
    # to be processed correctly.

    try:

        json_string = extract_json_object(output)

    except ValueError as error:

        raise ValueError(
            f"Could not extract JSON from Ollama response: "
            f"{error}\n\n"
            f"Raw output:\n{output}"
        )


    # ---------------------------------------------------------
    # STEP 7: Convert JSON text into a Python object
    # ---------------------------------------------------------

    try:

        result = json.loads(json_string)

    except json.JSONDecodeError as error:

        raise ValueError(
            f"Invalid JSON returned by Ollama: {error}\n\n"
            f"Extracted JSON:\n{json_string}\n\n"
            f"Raw output:\n{output}"
        )


    # ---------------------------------------------------------
    # STEP 8: Make sure the result is actually a dictionary
    # ---------------------------------------------------------
    #
    # Our application expects invoice data in dictionary form.
    #
    # For example:
    #
    # {
    #     "Invoice_No": "123456",
    #     "Description": [...],
    #     "Amount": [...]
    # }
    #
    # If the model somehow returns a JSON list instead,
    # that should not be passed further into the pipeline.

    if not isinstance(result, dict):

        raise ValueError(
            "Ollama returned valid JSON, but the JSON value "
            "is not an object/dictionary.\n\n"
            f"Returned value:\n{result}"
        )


    # ---------------------------------------------------------
    # STEP 9: Return the structured invoice dictionary
    # ---------------------------------------------------------

    return result


# -------------------------------------------------------------
# STEP 10: Test this file directly
# -------------------------------------------------------------
#
# This block only runs when:
#
#     python ollama_1.py
#
# It does NOT run when parser.py imports this file.
# -------------------------------------------------------------

if __name__ == "__main__":

    # ---------------------------------------------------------
    # Sample invoice text
    # ---------------------------------------------------------
    #
    # In the real application this information comes from OCR.

    SAMPLE_INVOICE_TEXT = """
    Invoice No.: 98765
    Issue Date: 12/25/2025
    Description: Product shipment, Consulting Fee
    Amount: 500.00, 150.00
    Grand Total: $650.00
    """


    # ---------------------------------------------------------
    # Send the sample invoice to Ollama
    # ---------------------------------------------------------

    try:

        result_dict = get_json_from_prompt(
            SAMPLE_INVOICE_TEXT
        )


        # -----------------------------------------------------
        # Display the result
        # -----------------------------------------------------

        print("\nStructured invoice data:")
        print(
            json.dumps(
                result_dict,
                indent=4
            )
        )


    except Exception as error:

        print("\nERROR:")
        print(error)

