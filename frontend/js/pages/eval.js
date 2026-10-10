// Run the evaluation set and compare reports.

import { api } from "../api.js";
import { clear, errorBox, h, pct, seconds, toast } from "../ui.js";

export async function render(view) {
  const kind = h("select", {}, h("option", { value: "extraction" }, "Full pipeline (extraction)"), h("option", { value: "ocr" }, "OCR only"),
    h("option", { value: "chat" }, "Chat questions"));
  const sets = ["tuning", "dev", "test"].map((name) =>
    h("label", { class: "row small" }, h("input", { type: "checkbox", value: name, checked: name === "test" }), name));
  const statusBox = h("div");
  const results = h("div");
  let timer = null;

  async function refreshStatus() {
    let st;
    try { st = await api.get("/api/eval/status"); } catch (error) { clear(statusBox, errorBox(error)); return; }
    if (!st.running && st.exit_code === undefined) { clear(statusBox); return; }
    clear(statusBox, h("div", { class: "card" },
      h("div", { class: "row" }, h("b", {}, st.name), st.running ? h("span", { class: "badge processing" }, "… Running")
        : h("span", { class: `badge ${st.exit_code === 0 ? "verified" : "failed"}` }, st.exit_code === 0 ? "✓ Finished" : `✕ Exit ${st.exit_code}`),
        h("span", { class: "muted small" }, `started ${st.started}`)),
      h("pre", { style: "margin-top: 0.5rem; max-height: 14rem" }, (st.log || []).join("\n") || "Starting…")));
    if (st.running) timer = setTimeout(refreshStatus, 3000);
    else loadResults();
  }

  async function run() {
    const chosen = sets.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    if (!chosen.length) { toast("Choose at least one set.", "error"); return; }
    try {
      await api.post("/api/eval/run", { kind: kind.value, sets: chosen });
      toast(kind.value === "chat" ? "Chat evaluation started: about 15 s per question."
        : "Evaluation started. Full-pipeline runs take about a minute per receipt.");
      clearTimeout(timer);
      refreshStatus();
    } catch (error) { toast(error.message, "error"); }
  }

  async function loadResults() {
    let rows;
    try { rows = await api.get("/api/eval/results"); } catch (error) { clear(results, errorBox(error)); return; }
    const ext = rows.filter((r) => r.kind === "extraction");
    const ocr = rows.filter((r) => r.kind === "ocr");
    const chat = rows.filter((r) => r.kind === "chat");
    clear(results,
      h("div", { class: "card" }, h("h2", {}, "Chat reports"),
        chat.length ? h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, ["Run", "When", "Questions", "Right function", "Right function + arguments", "Answers correct", "Median time"]
            .map((t, i) => h("th", { class: i > 1 ? "num" : "" }, t)))),
          h("tbody", {}, chat.map((r) => h("tr", { class: "clickable", onclick: () => showChatReport(r.file) },
            h("td", {}, h("b", {}, r.name)), h("td", { class: "muted small" }, r.created?.replace("T", " ")),
            h("td", { class: "num" }, r.summary.questions), h("td", { class: "num" }, pct(r.summary.function_accuracy)),
            h("td", { class: "num" }, pct(r.summary.function_and_arguments_accuracy)),
            h("td", { class: "num" }, r.summary.answers_correct), h("td", { class: "num" }, seconds(r.summary.seconds_median)))))))
          : h("div", { class: "empty" }, "No chat reports yet.")),
      h("div", { class: "card" }, h("h2", {}, "Extraction reports"),
        ext.length ? h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, ["Run", "When", "Receipts", "Key fields", "All fields", "Item F1", "Categories", "Wrong totals unflagged", "Median time"]
            .map((t, i) => h("th", { class: i > 1 ? "num" : "" }, t)))),
          h("tbody", {}, ext.map((r) => [
            h("tr", { class: "clickable", onclick: () => showReport(r.file) },
              h("td", {}, h("b", {}, r.name)), h("td", { class: "muted small" }, r.created?.replace("T", " ")),
              h("td", { class: "num" }, r.summary.receipts), h("td", { class: "num" }, pct(r.summary.key_field_accuracy)),
              h("td", { class: "num" }, pct(r.summary.all_field_accuracy)), h("td", { class: "num" }, r.summary.item_f1?.toFixed(2)),
              h("td", { class: "num" }, pct(r.summary.category_accuracy)),
              h("td", { class: "num" }, r.summary.wrong_totals_unflagged === 0 ? "0 ✓" : `${r.summary.wrong_totals_unflagged} ✕`),
              h("td", { class: "num" }, seconds(r.summary.seconds_per_receipt_median))),
            ...Object.entries(r.summary_by_set || {}).map(([set, sm]) => h("tr", { class: "small muted" },
              h("td", { style: "padding-left: 1.5rem" }, `└ ${set}`), h("td"), h("td", { class: "num" }, sm.receipts),
              h("td", { class: "num" }, pct(sm.key_field_accuracy)), h("td", { class: "num" }, pct(sm.all_field_accuracy)),
              h("td", { class: "num" }, sm.item_f1?.toFixed(2)), h("td", { class: "num" }, pct(sm.category_accuracy)),
              h("td", { class: "num" }, sm.wrong_totals_unflagged), h("td"))),
          ])))) : h("div", { class: "empty" }, "No extraction reports yet.")),
      h("div", { class: "card" }, h("h2", {}, "OCR reports"),
        ocr.length ? h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, ["Run", "When", "Receipts", "Character error rate", "Words found", "Key values", "s/receipt"]
            .map((t, i) => h("th", { class: i > 1 ? "num" : "" }, t)))),
          h("tbody", {}, ocr.map((r) => h("tr", {},
            h("td", {}, h("b", {}, r.name)), h("td", { class: "muted small" }, r.created?.replace("T", " ")),
            h("td", { class: "num" }, r.summary.receipts), h("td", { class: "num" }, pct(r.summary.mean_cer)),
            h("td", { class: "num" }, pct(r.summary.mean_token_recall)),
            h("td", { class: "num" }, `${r.summary.key_values_found}/${r.summary.key_values_total}`),
            h("td", { class: "num" }, r.summary.seconds_per_receipt ?? "–")))))) : h("div", { class: "empty" }, "No OCR reports yet.")),
      h("div", { id: "report-detail" }));
  }

  async function showChatReport(file) {
    const target = document.getElementById("report-detail");
    clear(target, h("div", { class: "card" }, h("span", { class: "spinner" })));
    let report;
    try { report = await api.get(`/api/eval/results/${encodeURIComponent(file)}`); } catch (error) { clear(target, errorBox(error)); return; }
    clear(target, h("div", { class: "card" }, h("h2", {}, `Per question: ${report.name}`),
      h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Question"), h("th", {}, "Function"), h("th", {}, "Problems"), h("th", { class: "num" }, "Time"))),
        h("tbody", {}, Object.entries(report.questions).map(([id, q]) => h("tr", { class: q.problems.length ? "flagged" : "" },
          h("td", {}, h("div", {}, h("b", {}, id), " ", q.question), h("div", { class: "muted small" }, q.answer)),
          h("td", {}, q.tool),
          h("td", { class: "small" }, q.problems.length ? q.problems.map((p) => h("div", {}, p)) : h("span", { class: "muted" }, "none")),
          h("td", { class: "num" }, seconds(q.seconds)))))))));
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function showReport(file) {
    const target = document.getElementById("report-detail");
    clear(target, h("div", { class: "card" }, h("span", { class: "spinner" })));
    let report;
    try { report = await api.get(`/api/eval/results/${encodeURIComponent(file)}`); } catch (error) { clear(target, errorBox(error)); return; }
    clear(target, h("div", { class: "card" }, h("h2", {}, `Per receipt: ${report.name}`),
      h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Receipt"), h("th", { class: "num" }, "Items matched"), h("th", {}, "Wrong fields"), h("th", {}, "Flagged"))),
        h("tbody", {}, Object.entries(report.receipts).map(([image, r]) => {
          const wrong = Object.entries(r.fields).filter(([, f]) => f.status === "wrong");
          const pred = report.predictions?.[image] || {};
          return h("tr", {},
            h("td", {}, image.split("/").pop()),
            h("td", { class: "num" }, `${r.items.matched}/${r.items.expected}` + (r.items.predicted !== r.items.expected ? ` (${r.items.predicted} found)` : "")),
            h("td", { class: "small" }, wrong.length ? wrong.map(([name, f]) => h("div", {}, h("b", {}, name), `: ${f.predicted ?? "–"} (expected ${f.expected ?? "–"})`)) : h("span", { class: "muted" }, "none")),
            h("td", {}, pred.status ? h("span", { class: `badge ${pred.status}` }, pred.status.replace("_", " ")) : ""));
        }))))));
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  clear(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Evaluation"),
      h("div", { class: "muted" }, "Score the pipeline against hand-checked answers. Tune on dev; report test."))),
    h("div", { class: "card row" }, kind, ...sets, h("span", { class: "spacer" }), h("button", { class: "primary", onclick: run }, "Run evaluation")),
    h("div", { style: "margin: 1rem 0" }, statusBox),
    results);
  refreshStatus();
  await loadResults();
  return () => clearTimeout(timer);
}
