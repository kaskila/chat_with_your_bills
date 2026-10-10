
# Import the function responsible for building the
# expense classification prompt and the predefined categories.
from prompt_2 import build_category_prompt, CATEGORIES

import subprocess
import time
import re


def clean_model_response(output: str) -> str:
    """
    Clean the raw response returned by Ollama.

    Ollama may return:
    - Thinking/reasoning text
    - ANSI terminal control characters
    - Quotes
    - Markdown formatting
    - Extra whitespace

    This function removes those unnecessary parts and attempts
    to extract the final category.

    Args:
        output (str):
            Raw response returned by Ollama.

    Returns:
        str:
            Cleaned response.
    """

    # ---------------------------------------------------------
    # STEP 1: Remove ANSI terminal escape sequences
    # ---------------------------------------------------------
    #
    # Ollama can return terminal control characters such as:
    #
    #     \x1b[K
    #     \x1b[9D
    #     \x1b[5D
    #
    # These are used to update the terminal display and should
    # not be part of our classification result.
    # ---------------------------------------------------------

    cleaned = re.sub(
        r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])",
        "",
        output
    )

    # ---------------------------------------------------------
    # STEP 2: Remove the "Thinking..." section
    # ---------------------------------------------------------
    #
    # qwen3 may return something like:
    #
    # Thinking...
    #
    # [long reasoning]
    #
    # ...done thinking.
    #
    # Utilities
    #
    # We only want:
    #
    # Utilities
    # ---------------------------------------------------------

    if "...done thinking." in cleaned:
        cleaned = cleaned.split("...done thinking.", 1)[1]

    elif "...done thinking..." in cleaned:
        cleaned = cleaned.split("...done thinking...", 1)[1]

    # ---------------------------------------------------------
    # STEP 3: Remove common formatting characters
    # ---------------------------------------------------------

    cleaned = re.sub(r'["\'`]', '', cleaned)

    cleaned = cleaned.replace("*", "")

    # ---------------------------------------------------------
    # STEP 4: Remove unnecessary whitespace
    # ---------------------------------------------------------

    cleaned = cleaned.strip()

    return cleaned


def extract_category(cleaned_response: str) -> str | None:
    """
    Extract a valid category from the cleaned Ollama response.

    The function first attempts an exact match.

    If the model still returns extra text, it searches for one
    of the predefined categories.

    Args:
        cleaned_response (str):
            Cleaned Ollama response.

    Returns:
        str | None:
            A valid category, or None if no category was found.
    """

    # ---------------------------------------------------------
    # STEP 1: Exact match
    # ---------------------------------------------------------

    for category in CATEGORIES:

        if cleaned_response.lower() == category.lower():
            return category

    # ---------------------------------------------------------
    # STEP 2: Check each line
    # ---------------------------------------------------------
    #
    # Sometimes the model may return:
    #
    # Category:
    # Utilities
    #
    # In that situation, inspect each line separately.
    # ---------------------------------------------------------

    lines = cleaned_response.splitlines()

    for line in lines:

        line = line.strip()

        for category in CATEGORIES:

            if line.lower() == category.lower():
                return category

    # ---------------------------------------------------------
    # STEP 3: Look for a category at the end of the response
    # ---------------------------------------------------------
    #
    # This is useful if the model returns something such as:
    #
    # The correct category is Utilities.
    #
    # We check the ending of the response rather than accepting
    # arbitrary text containing a category.
    # ---------------------------------------------------------

    for category in sorted(
        CATEGORIES,
        key=len,
        reverse=True
    ):

        pattern = rf"\b{re.escape(category)}\b\s*[.!]?\s*$"

        if re.search(
            pattern,
            cleaned_response,
            flags=re.IGNORECASE
        ):
            return category

    return None


def get_category_from_ollama(description_text: str) -> str:
    """
    Classify an expense/service description using Ollama.

    Args:
        description_text (str):
            The expense or service description.

    Returns:
        str:
            One of the predefined expense categories.
    """

    # ---------------------------------------------------------
    # STEP 1: Validate the input
    # ---------------------------------------------------------

    if not description_text or not description_text.strip():
        return "Other"

    description_text = description_text.strip()

    # ---------------------------------------------------------
    # STEP 2: Build the classification prompt
    # ---------------------------------------------------------

    prompt = build_category_prompt(description_text)

    # ---------------------------------------------------------
    # STEP 3: Start Ollama
    # ---------------------------------------------------------

    try:

        process = subprocess.Popen(
            [
                "ollama",
                "run",
                "qwen3:0.6b",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    except FileNotFoundError:

        print("ERROR: Ollama was not found in PATH.")

        return "Uncategorized LLM Error"

    except Exception as error:

        print(f"ERROR: Failed to start Ollama: {error}")

        return "Uncategorized LLM Error"

    # ---------------------------------------------------------
    # STEP 4: Send the prompt to Ollama
    # ---------------------------------------------------------

    try:

        output, error = process.communicate(
            input=prompt
        )

    except Exception as error:

        print(
            f"ERROR: Failed while communicating "
            f"with Ollama: {error}"
        )

        try:
            process.kill()
        except Exception:
            pass

        return "Uncategorized LLM Error"

    # ---------------------------------------------------------
    # STEP 5: Check Ollama exit status
    # ---------------------------------------------------------

    if process.returncode != 0:

        print(
            "ERROR: Ollama returned a non-zero exit code."
        )

        if error:
            print(
                f"Ollama error: {error.strip()}"
            )

        return "Uncategorized LLM Error"

    # ---------------------------------------------------------
    # STEP 6: Check for an empty response
    # ---------------------------------------------------------

    if not output or not output.strip():

        print(
            "ERROR: Ollama returned an empty response."
        )

        return "Other"

    # ---------------------------------------------------------
    # STEP 7: Clean the Ollama response
    # ---------------------------------------------------------

    cleaned_response = clean_model_response(output)

    # ---------------------------------------------------------
    # STEP 8: Extract the category
    # ---------------------------------------------------------

    final_category = extract_category(
        cleaned_response
    )

    # ---------------------------------------------------------
    # STEP 9: Return the category
    # ---------------------------------------------------------

    if final_category is not None:

        return final_category

    # ---------------------------------------------------------
    # STEP 10: Invalid response
    # ---------------------------------------------------------

    print(
        "WARNING: Ollama returned an invalid "
        f"category: {cleaned_response!r}"
    )

    return "Other"


# -------------------------------------------------------------
# TESTING
# -------------------------------------------------------------

if __name__ == "__main__":

    description_text = "Paying for my rental bills"

    print("=" * 60)
    print("EXPENSE CLASSIFICATION TEST")
    print("=" * 60)

    print(
        f"Expense: {description_text}"
    )

    # Start timer.
    start_time = time.time()

    # Classify the expense.
    category = get_category_from_ollama(
        description_text
    )

    # Calculate processing time.
    elapsed_time = time.time() - start_time

    print(
        f"Category: {category}"
    )

    print(
        f"Processing time: {elapsed_time:.2f} seconds"
    )

    print("=" * 60)

# Now run the same command:

# ```powershell
# & C:\Python314\python.exe c:/Users/USER/dev/chat_with_your_bills/ollama_2.py
# ```

### Expected result

# You should now get something like:

# ```text
# ============================================================
# EXPENSE CLASSIFICATION TEST
# ============================================================
# Expense: Paying for my rental bills
# Category: Utilities
# Processing time: 10.xx seconds
# ============================================================
# ```

# Notice something important: **the 10.99 seconds is a separate problem**. We've now isolated the classification/output problem. Once `Utilities` works, we'll tackle why `qwen3:0.6b` is taking ~11 seconds and, importantly, how to stop the `Thinking...` output from being generated in the first place rather than merely cleaning it afterward.
