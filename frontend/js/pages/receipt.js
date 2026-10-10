// One receipt: photo, editable data, warnings, notes, OCR comparison, timings, actions.

import { api } from "../api.js";
import { jobCard } from "../jobs.js";
import { clear, errorBox, h, money, seconds, statusBadge, toast, warningList } from "../ui.js";

const CATEGORIES = ["Food", "Drinks", "Grocery", "Utilities", "Travel", "Logistics", "Office & Stationery", "Other"];
const FIELDS = [
  ["vendor", "Vendor", "text"], ["receipt_no", "Receipt no.", "text"], ["date", "Date", "date"],
  ["time", "Time", "time"], ["currency", "Currency", "text"], ["payment_method", "Payment", "text"], ["recipient", "Paid to", "text"],
  ["subtotal", "Subtotal", "number"], ["discount", "Discount", "number"], ["service_charge", "Service charge", "number"],
  ["tax", "Tax", "number"], ["total", "Total", "number"], ["amount_paid", "Amount paid", "number"], ["change", "Change", "number"],
];
const TIMING_COLORS = { preprocess_s: "#9ec5f4", ocr_s: "#5598e7", extract_s: "#2a78d6", vlm_s: "#eb6834", extract2_s: "#d95926" };
const TIMING_LABELS = { preprocess_s: "Prepare", ocr_s: "OCR", extract_s: "Extract", vlm_s: "VLM re-read", extract2_s: "Re-extract" };

export async function render(view, { id }) {
  let stopJob = null;

  async function load() {
    stopJob?.();
    let r;
    try {
      r = await api.get(`/api/receipts/${id}`);
    } catch (error) {
      clear(view, errorBox(error), h("p", {}, h("a", { href: "#/receipts" }, "← All receipts")));
      return;
    }
    if (r.status === "processing" && r.latest_job && !["done", "failed"].includes(r.latest_job.stage)) {
      const card = jobCard(r.latest_job.id, `Receipt #${r.id}`, () => setTimeout(load, 800));
      stopJob = card.stop;
      clear(view, header(r), card.el);
      return;
    }
    clear(view, header(r), h("div", { class: "split" }, imagePanel(r), dataPanel(r, load)), ocrPanel(r));
  }

  await load();
  return () => stopJob?.();
}

function header(r) {
  return h("div", { class: "page-head" },
    h("div", {},
      h("div", { class: "small" }, h("a", { href: "#/receipts" }, "← All receipts")),
      h("h1", {}, r.vendor || r.original_filename || `Receipt #${r.id}`),
      h("div", { class: "row" }, statusBadge(r.status),
        r.user_edited ? h("span", { class: "badge info" }, "Edited by you") : null,
        r.models?.vlm ? h("span", { class: "badge neutral" }, "VLM re-read") : null,
        h("span", { class: "muted small" }, `#${r.id} · ${r.original_filename || ""}`))),
  );
}

function imagePanel(r) {
  const img = h("img", { class: "receipt-image", src: `/api/receipts/${r.id}/image`, alt: `Photo of receipt ${r.id}` });
  const buttons = ["original", "cropped"].map((variant) => h("button", {
    class: `seg small ${variant === "original" ? "on" : ""}`,
    onclick: (e) => {
      img.src = `/api/receipts/${r.id}/image?variant=${variant}`;
      buttons.forEach((b) => b.classList.toggle("on", b === e.currentTarget));
    },
  }, variant === "original" ? "Original" : "Cropped"));
  return h("div", { class: "card" }, h("div", { class: "row", style: "margin-bottom: 0.5rem" }, h("div", { class: "row", style: "gap: 0" }, buttons)),
    h("a", { href: `/api/receipts/${r.id}/image`, target: "_blank", rel: "noopener" }, img));
}

function flaggedFields(warnings) {
  const set = new Set();
  for (const w of warnings || []) {
    if (!w.field) continue;
    set.add(w.field.replace(/\.(amount|unit_price)$/, ""));
  }
  return set;
}

function dataPanel(r, reload) {
  const flagged = flaggedFields(r.warnings);
  const inputs = {};
  const fields = h("div", { class: "fields" }, FIELDS.map(([key, label, type]) => {
    const input = h("input", { type, value: r[key] ?? "", step: type === "number" ? "0.01" : undefined, name: key });
    inputs[key] = input;
    return h("label", { class: `field ${flagged.has(key) ? "flagged" : ""}` }, label, input);
  }));

  const itemsBody = h("tbody");
  const addRow = (item = {}, index = itemsBody.children.length) => {
    const cat = h("select", {}, CATEGORIES.map((c) => h("option", { value: c, selected: c === (item.category || "Other") }, c)));
    const tr = h("tr", { class: flagged.has(`items[${index}]`) ? "flagged" : "" },
      h("td", {}, h("input", { value: item.description ?? "", "aria-label": "Description", "data-k": "description" })),
      h("td", {}, h("input", { type: "number", step: "any", value: item.quantity ?? "", "aria-label": "Quantity", "data-k": "quantity", style: "width: 5rem" })),
      h("td", {}, h("input", { type: "number", step: "0.01", value: item.unit_price ?? "", "aria-label": "Unit price", "data-k": "unit_price", style: "width: 7rem" })),
      h("td", {}, h("input", { type: "number", step: "0.01", value: item.amount ?? "", "aria-label": "Amount", "data-k": "amount", style: "width: 7rem" })),
      h("td", {}, cat),
      h("td", {}, h("button", { class: "small danger", title: "Remove item", onclick: () => tr.remove() }, "✕")));
    cat.dataset.k = "category";
    itemsBody.append(tr);
  };
  (r.items || []).forEach((item, i) => addRow(item, i));

  const num = (v) => (v === "" || v === null ? null : Number(v));
  function collect() {
    const data = {};
    for (const [key, , type] of FIELDS) {
      const v = inputs[key].value.trim();
      data[key] = type === "number" ? num(v) : v || null;
    }
    data.items = [...itemsBody.children].map((tr) => {
      const get = (k) => tr.querySelector(`[data-k="${k}"]`).value;
      return { description: get("description").trim(), quantity: num(get("quantity")), unit_price: num(get("unit_price")),
        amount: num(get("amount")), category: get("category") };
    }).filter((i) => i.description && i.amount !== null);
    return data;
  }

  const save = h("button", { class: "primary", onclick: async () => {
    save.disabled = true;
    try {
      const updated = await api.patch(`/api/receipts/${r.id}`, collect());
      toast(updated.status === "verified" ? "Saved. All checks pass." : "Saved. Some checks still fail — see warnings.");
      reload();
    } catch (error) {
      toast(error.message, "error");
      save.disabled = false;
    }
  } }, "Save changes");

  // After checking every field and item against the photo: keep it as a test case for the evaluation.
  const testCase = h("button", { title: "Use this receipt, as corrected here, to measure accuracy (Evaluation, set 'real')",
    onclick: async () => {
      if (!confirm("Save as a test case?\n\nOnly do this after checking EVERY field and item against the photo: "
        + "the evaluation will treat these values as the correct answer.")) return;
      testCase.disabled = true;
      try {
        await api.patch(`/api/receipts/${r.id}`, collect());  // include unsaved corrections
        await api.post(`/api/receipts/${r.id}/test-case`);
        toast("Saved as a test case. It is scored in Evaluation → set 'real'.");
        reload();
      } catch (error) {
        toast(error.message, "error");
        testCase.disabled = false;
      }
    } }, r.test_case ? "Update test case" : "Save as test case");

  const reprocess = (forceVlm) => async () => {
    try {
      await api.post(`/api/receipts/${r.id}/reprocess${forceVlm ? "?force_vlm=true" : ""}`);
      toast(forceVlm ? "Queued with the vision model re-read." : "Queued for reprocessing.");
      reload();
    } catch (error) { toast(error.message, "error"); }
  };

  const remove = async () => {
    if (!confirm(`Delete receipt #${r.id} and its photo? This cannot be undone.`)) return;
    try {
      await api.del(`/api/receipts/${r.id}`);
      toast("Receipt deleted.");
      location.hash = "#/receipts";
    } catch (error) { toast(error.message, "error"); }
  };

  const itemsSum = (r.items || []).reduce((sum, i) => sum + (i.amount || 0), 0);
  return h("div", { class: "stack" },
    r.error ? h("div", { class: "msg error" }, h("b", {}, "Processing failed:"), r.error) : null,
    warningList(r.warnings),
    h("div", { class: "card" }, h("h2", {}, "Receipt"), fields),
    h("div", { class: "card" },
      h("div", { class: "row" }, h("h2", {}, "Items"), h("span", { class: "spacer" }),
        h("span", { class: "muted small" }, `Sum ${money(itemsSum, r.currency)}`)),
      h("div", { class: "table-wrap" }, h("table", { class: "edit" },
        h("thead", {}, h("tr", {}, h("th", {}, "Description"), h("th", {}, "Qty"), h("th", {}, "Unit price"), h("th", {}, "Amount"), h("th", {}, "Category"), h("th"))),
        itemsBody)),
      h("button", { class: "small", style: "margin-top: 0.5rem", onclick: () => addRow() }, "+ Add item")),
    h("div", { class: "row" }, save, testCase, r.test_case ? h("span", { class: "badge info" }, "✓ test case") : null,
      h("button", { onclick: reprocess(false) }, "Reprocess"),
      h("button", { onclick: reprocess(true), title: "Re-read the photo with the vision model (about a minute more)" }, "Reprocess with VLM"),
      h("span", { class: "spacer" }), h("button", { class: "danger", onclick: remove }, "Delete")),
    r.notes?.length ? h("div", { class: "card" }, h("h3", {}, "Notes"), r.notes.map((n) => h("div", { class: "msg note" }, n))) : null,
    timingsCard(r));
}

function timingsCard(r) {
  const t = r.timings;
  if (!t?.total_s) return null;
  const parts = Object.keys(TIMING_LABELS).filter((k) => t[k]);
  const total = parts.reduce((sum, k) => sum + t[k], 0) || 1;
  return h("div", { class: "card" },
    h("div", { class: "row" }, h("h3", {}, "Processing time"), h("span", { class: "spacer" }), h("b", {}, seconds(t.total_s))),
    h("div", { class: "timing-bar", role: "img", "aria-label": parts.map((k) => `${TIMING_LABELS[k]} ${seconds(t[k])}`).join(", ") },
      parts.map((k) => h("span", { style: `width: ${(t[k] / total) * 100}%; background: ${TIMING_COLORS[k]}`, title: `${TIMING_LABELS[k]}: ${seconds(t[k])}` }))),
    h("div", { class: "row small muted", style: "margin-top: 0.4rem" },
      parts.map((k) => h("span", { class: "row", style: "gap: 0.3rem" },
        h("span", { style: `width: 10px; height: 10px; border-radius: 2px; background: ${TIMING_COLORS[k]}` }), `${TIMING_LABELS[k]} ${seconds(t[k])}`))),
    h("div", { class: "small muted", style: "margin-top: 0.3rem" },
      `Models: ${Object.values(r.models || {}).join(", ")}${r.ocr_confidence ? ` · OCR confidence ${(r.ocr_confidence * 100).toFixed(1)}%` : ""}`));
}

function ocrPanel(r) {
  if (!r.ocr_text_rapid && !r.ocr_text_vlm) return null;
  const norm = (line) => line.replace(/\s+/g, " ").trim().toLowerCase();
  const linesA = (r.ocr_text_rapid || "").split("\n");
  const linesB = (r.ocr_text_vlm || "").split("\n");
  const setA = new Set(linesA.map(norm));
  const setB = new Set(linesB.map(norm));
  const render = (lines, other) => h("pre", {}, lines.map((line) =>
    other.size && line.trim() && !other.has(norm(line)) ? [h("span", { class: "diff" }, line), "\n"] : `${line}\n`));
  return h("div", { class: "card", style: "margin-top: 1rem" },
    h("h2", {}, "What the OCR read"),
    r.ocr_text_vlm ? h("p", { class: "muted small" }, "Lines that appear in only one reading are highlighted.") : null,
    h("div", { class: r.ocr_text_vlm ? "ocr-compare" : "" },
      h("div", {}, h("h3", {}, "RapidOCR (first reading)"), render(linesA, r.ocr_text_vlm ? setB : new Set())),
      r.ocr_text_vlm ? h("div", {}, h("h3", {}, "Vision model (second reading)"), render(linesB, setA)) : null));
}
