# Phase 7 — Chat over the stored receipts

**Status:** done (2026-10-10)

## Goal

Answer questions about spending in plain English ("How much did I spend on groceries last month?") from the stored receipts, with answers that can be trusted: every number must come from the database, never from the language model.

Before the chat, three small validation fixes left over from Phase 4 were made (see the end of this report).

## What was done

| Part | File | What it does |
| --- | --- | --- |
| Date resolver | `app/chat/dates.py` | Turns time words into date ranges in Python: "last month", "this year", "in August", "since July", "past 30 days", "between August and September", "on 3 Oct", "before September", "all time". |
| Query functions | `app/chat/tools.py` | The 8 functions of the plan: `total_spend`, `spend_by_category`, `spend_by_vendor`, `spend_over_time`, `largest_purchases`, `search_items`, `list_receipts`, `receipt_details`. Fixed, parameterized SQL. |
| Agent | `app/chat/agent.py` | One qwen3:4b call picks the function and arguments; Python checks them, runs the query and writes the answer from a template. |
| API | `POST /api/chat` | `{message, history}` → `{answer, tool, arguments, rows, seconds, llm}`. 503 with a clear message when Ollama is down. |
| Chat page | `frontend/js/pages/chat.js` | Example questions, a conversation, and under each answer: the function, its arguments, the time taken and the database rows (receipt numbers link to the receipt). Follow-up questions work. |
| Chat test set | `eval/chat_questions.json`, `eval/chat_eval.py` | 32 questions with the expected function and arguments, and numbers each answer must contain. `python -m eval.run_eval chat --name X`; also runnable from the Evaluation page. |

## How it works

```text
Question ──► qwen3:4b (forced JSON schema) ──► {"function": "total_spend", "period": "last month", "category": "Grocery", ...}
                                                   │
                Python checks the arguments ◄──────┘
                  • dates: resolved from the question's own words (dates.py)
                  • vendor: matched to a stored vendor name ("mukuba" → MUKUBA SUPERMART)
                  • numbers: limits clamped to 1–50; receipt id read from the question
                                                   │
                Fixed SQL with parameters ─────────┤──► rows (one total per currency)
                                                   │
                Template answer from the rows ─────┘──► "You spent K1,382.76 (16 items on 2 receipts) on Grocery in September 2026."
```

1. **Choosing the function.** The model's reply is forced into a JSON schema (Ollama structured outputs) whose `function` field is a list of the 9 allowed names (the 8 functions plus `none`), and whose `category`, `group_by` and `status` fields are also fixed lists. The model cannot name a function or category that does not exist. The system prompt describes each function with example questions and never changes, so Ollama reuses its cached prompt.
2. **Dates come from the question, not the model.** The model only copies the time words; Python finds the time words in the question itself. If the question has none ("And on groceries?"), the time of the previous question is kept only when the model signals it carries over; otherwise the whole history is used. A period the model invents is ignored.
3. **Vendors** are matched ignoring case and punctuation, as a substring either way, then by closest spelling ("sunrize bakery" → SUNRISE BAKERY). An unknown shop gets "I could not find a shop called 'Shoprite'" plus a list of known shops, never an empty total.
4. **Currencies are never mixed.** Every function returns one row per currency; answers name the main currency first ("K350.00 (3 receipts) and $40.00 (1 receipt)"). Failed receipts are never counted (as on the dashboard); receipts without a total are mentioned.
5. **Templates** write the answer from the rows in a few milliseconds. The optional rewording by the model (`BILLS_CHAT_REPHRASE=true`, off by default, ~10–20 s more) is thrown away unless every number in the template answer appears unchanged in the rewording.
6. **Small repairs:** the number in "top 3"/"5 biggest" and the id in "receipt 12" are read from the question when the model leaves them out; a vendor ranking asked for one named vendor ("How much have I paid Quickride?") becomes that vendor's total.

## Why it was done this way

- **The model never writes SQL** (decided in Phase 0): a 4B model on CPU writes wrong SQL often enough that totals could be silently wrong. Choosing from 9 functions is a much easier task, and the SQL can be tested.
- **Forced JSON schema instead of Ollama's tool-calling API.** The plan said "tool calling"; the schema does the same job but guarantees a valid function name and valid enum values in every reply, and the same mechanism is already proven by extraction in this project.
- **Dates in Python.** Small models are unreliable at calendar arithmetic ("last week" on 10 October). Resolving in Python also means today's date is not in the prompt, so the prompt stays identical and cached.
- **Template answers** are instant and cannot change a number. Rewording is optional and checked.
- **Test database built from the ground truth.** The chat eval creates a fresh in-memory database from the 23 hand-checked receipts, so scores do not depend on what has been uploaded, and the expected numbers were computed by hand from the ground truth.

## Technology

qwen3:4b via Ollama (structured outputs, temperature 0, thinking off), SQLite (window functions for per-currency vendor rankings), Python `difflib` for vendor spelling, plain JavaScript for the page. No new dependencies.

## Results

**Chat test set** (32 questions: totals, categories, vendors, trends, biggest purchases, product search, receipt lists and details, 2 follow-ups, 2 off-topic):

| Run | Right function | Right function + all arguments | Answers with the correct numbers | Median time |
| --- | --- | --- | --- | --- |
| chat-v1 | 96.9% | 96.9% | 31/32 | 10.6 s |
| chat-v2 (vendor-ranking repair) | **100%** | **100%** | **32/32** | 10.8 s (max 12.4 s) |

- The one miss in v1: "How much have I paid Quickride?" chose the vendor ranking with vendor = Quickride; fixed by the general rule in step 6, not by changing the prompt.
- Caveat: the questions were written in this phase by the same person who wrote the prompt, so they are not a blind test. Phrasings far from the examples may do worse; the Chat page shows the chosen function and arguments under every answer so a wrong choice is visible.
- The first question after the model is loaded takes ~35 s (prompt not cached yet); after that ~10–13 s on this laptop, almost all of it the model writing the ~60-token JSON at ~6 tokens/s.
- A test with a "perfect model" (always the expected call) passes all 32 questions, which checks that the expected arguments and hand-computed numbers agree with the SQL.
- Checked in the browser (headless Chrome, live database, desktop and phone width): "How much did I spend last month?" → "And on groceries?" (follow-up keeps September) → "When did I last buy milk?", all correct.

**Automated tests:** 128 passing (34 new: dates, every query function against a hand-built database including currencies and failed receipts, vendor matching, follow-ups, invented periods ignored, SQL injection attempt in search text, rephrase guard, the endpoint, and the validation fixes).

## Validation fixes (before the chat)

| Fix | Receipts | Effect |
| --- | --- | --- |
| A `change` equal to paid − total is cleared unless a "Change" line is printed (the model calculated it) | 13, 02 | 13 no longer flagged "value not printed" |
| The totals check also accepts a subtotal already after the discount ("NET AMOUNT") | 17 | no longer a false "totals inconsistent" |
| A subtotal equal to the total is dropped when no Subtotal / Net Amount / Excl line is printed | 02, 13, 15, 16 | subtotal field now correct |

Full pipeline evaluation after the fixes (`phase7-fixes`, all 23 receipts, on AC power):

| Measure | Before (phase4-auto-v2) | After |
| --- | --- | --- |
| All fields correct, test set | 97.5% | **100%** |
| All fields correct, dev set | 99.2% | **100%** |
| Key fields, test set | 100% | 100% |
| Wrong totals accepted without a warning | 0 | 0 |
| Median time per receipt | 76 s | **53 s** (13 and 17 no longer trigger the VLM re-read) |

Still flagged, correctly: receipt 07 (OCR merged "x20 18.00" into "x208.00", so the line math does not add up) and receipt_1 (faded handwritten receipt; vendor and total wrong but flagged).

## Files

- `app/chat/dates.py`, `app/chat/tools.py`, `app/chat/agent.py`, `app/api/chat.py`
- `app/llm/prompts.py` (`CHAT_SYSTEM`), `app/config.py` (`chat_*` settings), `.env.example`
- `app/pipeline/validate.py` (the three fixes)
- `frontend/js/pages/chat.js`, `frontend/js/pages/eval.js` (chat reports), `frontend/css/styles.css`
- `eval/chat_questions.json`, `eval/chat_eval.py`, `eval/run_eval.py` (`chat` command), `app/api/evals.py`
- `tests/test_chat.py`, `tests/test_validate.py`
- Reports: `eval/results/*_extraction_phase7-fixes.json`, `*_chat_chat-v1.json`, `*_chat_chat-v2.json`
