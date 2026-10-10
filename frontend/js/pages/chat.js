// Chat over the stored receipts. Each answer shows which query function ran,
// its arguments, the result rows and the response time.

import { api } from "../api.js";
import { clear, date, h, money, seconds, statusBadge } from "../ui.js";

const EXAMPLES = [
  "How much did I spend last month?",
  "Break down my spending by category this month",
  "Where do I spend the most?",
  "Show my monthly spending this year",
  "What were my 5 biggest purchases?",
  "When did I last buy milk?",
  "Which receipts need review?",
];

// Kept while the app is open, so leaving the page and coming back keeps the conversation.
const conversation = []; // {question, result?, error?}
let busy = false;
let refresh = null; // redraws the page currently shown (the answer may arrive after leaving and coming back)

const MONEY_COLUMNS = new Set(["total", "amount", "unit_price", "tax"]);
const HIDDEN_ARGUMENTS = new Set(["call"]);

function cell(key, value, row) {
  if (value === null || value === undefined) return h("td", { class: "muted" }, "–");
  if (MONEY_COLUMNS.has(key)) return h("td", { class: "num" }, money(value, row.currency));
  if (key === "receipt_id") return h("td", {}, h("a", { href: `#/receipts/${value}` }, `#${value}`));
  if (key === "date") return h("td", {}, date(value));
  if (key === "status") return h("td", {}, statusBadge(value));
  if (typeof value === "number") return h("td", { class: "num" }, Number.isInteger(value) ? value : value.toFixed(2));
  return h("td", {}, String(value));
}

function rowsTable(rows) {
  if (!rows.length) return h("div", { class: "muted small" }, "No rows.");
  const columns = Object.keys(rows[0]);
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, columns.map((c) =>
      h("th", { class: MONEY_COLUMNS.has(c) || typeof rows[0][c] === "number" ? "num" : "" }, c.replace(/_/g, " "))))),
    h("tbody", {}, rows.map((row) => h("tr", {}, columns.map((c) => cell(c, row[c], row)))))));
}

function argumentChips(args) {
  const entries = Object.entries(args).filter(([k, v]) => !HIDDEN_ARGUMENTS.has(k) && v !== null && v !== undefined);
  if (!entries.length) return null;
  return h("div", { class: "chat-args" }, entries.map(([k, v]) =>
    h("span", { class: "badge neutral" }, `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : v}`)));
}

function answerCard(turn) {
  if (turn.error) return h("div", { class: "chat-answer" }, h("div", { class: "msg error" }, turn.error));
  if (!turn.result) {
    const timer = h("span", { class: "muted small" }, "0 s");
    const started = Date.now();
    const id = setInterval(() => {
      if (!timer.isConnected) { clearInterval(id); return; }
      timer.textContent = `${Math.round((Date.now() - started) / 1000)} s`;
    }, 1000);
    return h("div", { class: "chat-answer" }, h("span", { class: "row" }, h("span", { class: "spinner" }),
      h("span", { class: "muted" }, "Choosing a query… (about 10–30 s on this CPU)"), timer));
  }
  const r = turn.result;
  const rows = r.rows || [];
  return h("div", { class: "chat-answer" },
    h("p", {}, r.answer),
    h("div", { class: "chat-meta" },
      h("span", { class: "badge info" }, r.tool === "none" ? "no query" : r.tool),
      argumentChips(r.arguments || {}),
      h("span", { class: "muted small" }, seconds(r.seconds))),
    rows.length ? h("details", {},
      h("summary", { class: "small" }, `${rows.length} row${rows.length === 1 ? "" : "s"} from the database`),
      rowsTable(rows)) : null);
}

function history() {
  // Earlier questions with the call chosen for each, for follow-ups ("and in July?").
  const turns = [];
  for (const turn of conversation.slice(-4)) {
    if (!turn.result) continue;
    turns.push({ role: "user", content: turn.question });
    turns.push({ role: "assistant", tool: turn.result.tool, call: turn.result.arguments?.call || {} });
  }
  return turns;
}

export function render(view) {
  const log = h("div", { class: "chat-log", "aria-live": "polite" });
  const input = h("input", { type: "text", placeholder: "Ask about your spending…", maxlength: 500,
    "aria-label": "Question", autocomplete: "off" });
  const send = h("button", { class: "primary", type: "submit" }, "Ask");
  const clearButton = h("button", { type: "button", onclick: () => { conversation.length = 0; draw(); } }, "Clear");
  function draw() {
    send.disabled = input.disabled = busy;
    clearButton.hidden = !conversation.length;
    if (!conversation.length) {
      clear(log, h("div", { class: "card" },
        h("p", { class: "muted" }, "Questions are answered from your stored receipts. The model only picks a query; "
          + "the numbers come straight from the database."),
        h("div", { class: "chat-examples" }, EXAMPLES.map((q) =>
          h("button", { type: "button", class: "small", onclick: () => ask(q) }, q)))));
      return;
    }
    clear(log, conversation.map((turn) => h("div", { class: "chat-turn" },
      h("div", { class: "chat-question" }, turn.question),
      answerCard(turn))));
    log.lastElementChild?.scrollIntoView({ block: "end", behavior: "smooth" });
  }

  async function ask(question) {
    question = question.trim();
    if (!question || busy) return;
    busy = true;
    const turn = { question };
    const previous = history();
    conversation.push(turn);
    input.value = "";
    draw();
    try {
      turn.result = await api.post("/api/chat", { message: question, history: previous });
    } catch (error) {
      turn.error = error.message;
    }
    busy = false;
    refresh?.();
  }

  const form = h("form", { class: "card chat-form", onsubmit: (event) => { event.preventDefault(); ask(input.value); } },
    input, send, clearButton);

  clear(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Chat"),
      h("div", { class: "muted" }, "Ask questions about your spending."))),
    log, form);
  refresh = () => { draw(); input.focus(); };
  refresh();
  return () => { refresh = null; };
}
