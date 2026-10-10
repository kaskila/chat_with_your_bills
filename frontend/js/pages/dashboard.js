// Spending overview for one currency and a date range.

import { api, query } from "../api.js";
import { barChart, columnChart } from "../charts.js";
import { clear, date, errorBox, h, money, recall, remember, shortMoney } from "../ui.js";

function iso(d) {
  return d.toISOString().slice(0, 10);
}

function monthLabel(month) {
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

const PRESETS = {
  all: () => ["", ""],
  month: () => { const n = new Date(); return [iso(new Date(n.getFullYear(), n.getMonth(), 1)), ""]; },
  "3m": () => { const n = new Date(); return [iso(new Date(n.getFullYear(), n.getMonth() - 2, 1)), ""]; },
  year: () => [`${new Date().getFullYear()}-01-01`, ""],
};

export async function render(view) {
  const saved = recall("dashboard", { preset: "all", currency: "" });
  const from = h("input", { type: "date", "aria-label": "From date" });
  const to = h("input", { type: "date", "aria-label": "To date" });
  const currency = h("select", { "aria-label": "Currency" });
  const presetButtons = Object.entries({ all: "All time", month: "This month", "3m": "Last 3 months", year: "This year" })
    .map(([key, label]) => h("button", { class: "seg small", dataset: { preset: key }, onclick: () => setPreset(key) }, label));
  const body = h("div", { class: "stack" });

  function setPreset(key) {
    [from.value, to.value] = PRESETS[key]();
    presetButtons.forEach((b) => b.classList.toggle("on", b.dataset.preset === key));
    saved.preset = key;
    load();
  }

  async function load() {
    remember("dashboard", { ...saved, currency: currency.value });
    let data;
    try {
      data = await api.get(`/api/stats/summary${query({ from: from.value, to: to.value, currency: currency.value })}`);
    } catch (error) {
      clear(body, errorBox(error));
      return;
    }
    // currency options come from the data
    const current = currency.value || data.currency;
    clear(currency, data.currencies.map((c) => h("option", { value: c.currency, selected: c.currency === current },
      `${c.currency} (${c.receipts})`)));
    const cur = data.currency;
    const fmt = (v) => money(v, cur);
    // Draw charts at their real pixel width (card padding 2 x 16 px); half width side by side.
    const full = Math.max(300, body.clientWidth - 34);
    const half = body.clientWidth > 900 ? Math.max(300, (body.clientWidth - 16) / 2 - 34) : full;

    if (!data.receipts) {
      clear(body, h("div", { class: "card empty" }, "No receipts in this period. ", h("a", { href: "#/upload" }, "Upload some →")));
      return;
    }

    const categories = barChart(data.by_category.map((c) => ({ label: c.category, value: c.amount, detail: `${c.items} item${c.items > 1 ? "s" : ""}` })),
      { format: fmt, width: half, labelHeader: "Category", tooltip: (d) => [h("div", {}, d.label), h("b", {}, fmt(d.value)), h("div", {}, d.detail)] });
    const vendors = barChart(data.by_vendor.map((v) => ({ label: v.vendor, value: v.amount, detail: `${v.receipts} receipt${v.receipts > 1 ? "s" : ""}` })),
      { format: fmt, width: half, labelHeader: "Vendor", tooltip: (d) => [h("div", {}, d.label), h("b", {}, fmt(d.value)), h("div", {}, d.detail)] });
    const months = columnChart(data.by_month.map((m) => ({ label: monthLabel(m.month), value: m.amount, detail: `${m.receipts} receipt${m.receipts > 1 ? "s" : ""}` })),
      { format: fmt, width: full, shortFormat: (v) => shortMoney(v, cur), labelHeader: "Month", tooltip: (d) => [h("div", {}, d.label), h("b", {}, fmt(d.value)), h("div", {}, d.detail)] });

    const chartCard = (title, subtitle, chart) => h("div", { class: "card" },
      h("div", { class: "chart-head" }, h("h2", {}, title), h("span", { class: "muted small" }, subtitle), h("span", { class: "spacer" }), chart.toggle),
      chart.body);

    clear(body,
      h("div", { class: "tiles" },
        h("div", { class: "card tile" }, h("div", { class: "label" }, "Total spent"), h("div", { class: "value" }, fmt(data.total)),
          h("div", { class: "sub" }, `${date(data.first_date)} – ${date(data.last_date)}`)),
        h("div", { class: "card tile" }, h("div", { class: "label" }, "Receipts"), h("div", { class: "value" }, data.receipts),
          h("div", { class: "sub" }, `average ${fmt(data.total / data.receipts)}`)),
        h("div", { class: "card tile" }, h("div", { class: "label" }, "Largest category"),
          h("div", { class: "value", style: "font-size: 1.35rem" }, data.by_category[0]?.category || "–"),
          h("div", { class: "sub" }, data.by_category[0] ? fmt(data.by_category[0].amount) : "")),
        h("div", { class: "card tile" }, h("div", { class: "label" }, "Need review"), h("div", { class: "value" }, data.needs_review),
          h("div", { class: "sub" }, data.needs_review ? h("a", { href: "#/receipts", onclick: () => remember("receiptFilters", { status: "needs_review" }) }, "Check them →") : "all verified"))),
      data.needs_review ? h("div", { class: "msg warning" }, `${data.needs_review} receipt(s) in these totals still need review; their numbers may be wrong until corrected.`) : null,
      h("div", { class: "grid grid-2" },
        chartCard("Spending by category", "item amounts", categories),
        chartCard("Top vendors", "receipt totals", vendors)),
      chartCard("Spending by month", "receipt totals", months),
      h("p", { class: "muted small" }, data.note));
  }

  currency.addEventListener("change", load);
  from.addEventListener("change", () => { presetButtons.forEach((b) => b.classList.remove("on")); load(); });
  to.addEventListener("change", () => { presetButtons.forEach((b) => b.classList.remove("on")); load(); });

  clear(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Dashboard"), h("div", { class: "muted" }, "Where the money went."))),
    h("div", { class: "card row", style: "margin-bottom: 1rem" },
      h("div", { class: "row", style: "gap: 0" }, presetButtons),
      h("label", { class: "row small muted" }, "From", from), h("label", { class: "row small muted" }, "to", to),
      h("span", { class: "spacer" }), h("label", { class: "row small muted" }, "Currency", currency)),
    body);

  if (saved.currency) currency.append(h("option", { value: saved.currency, selected: true }, saved.currency));
  setPreset(saved.preset || "all");

  // Redraw at the new width when the window is resized.
  let lastWidth = body.clientWidth;
  let resizeTimer;
  const onResize = () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (Math.abs(body.clientWidth - lastWidth) > 40) { lastWidth = body.clientWidth; load(); } }, 250);
  };
  window.addEventListener("resize", onResize);
  return () => window.removeEventListener("resize", onResize);
}
