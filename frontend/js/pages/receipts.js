// All stored receipts with filters.

import { api, query } from "../api.js";
import { clear, date, errorBox, h, money, recall, remember, statusBadge } from "../ui.js";

const CATEGORIES = ["Food", "Drinks", "Grocery", "Utilities", "Travel", "Logistics", "Office & Stationery", "Other"];

export async function render(view) {
  const saved = recall("receiptFilters", {});
  const status = h("select", {}, h("option", { value: "" }, "Any status"),
    ["verified", "needs_review", "failed", "processing"].map((s) => h("option", { value: s }, s.replace("_", " "))));
  const category = h("select", {}, h("option", { value: "" }, "Any category"), CATEGORIES.map((c) => h("option", { value: c }, c)));
  const search = h("input", { type: "search", placeholder: "Vendor, item or receipt no." });
  const from = h("input", { type: "date", "aria-label": "From date" });
  const to = h("input", { type: "date", "aria-label": "To date" });
  const controls = { status, category, q: search, from, to };
  for (const [key, el] of Object.entries(controls)) el.value = saved[key] || "";

  const body = h("div");
  const count = h("span", { class: "muted" });

  async function load() {
    const filters = Object.fromEntries(Object.entries(controls).map(([k, el]) => [k, el.value]));
    remember("receiptFilters", filters);
    let rows;
    try {
      rows = await api.get(`/api/receipts${query(filters)}`);
    } catch (error) {
      clear(body, errorBox(error));
      return;
    }
    clear(count, `${rows.length} receipt${rows.length === 1 ? "" : "s"}`);
    if (!rows.length) {
      clear(body, h("div", { class: "empty" }, "No receipts match. ", h("a", { href: "#/upload" }, "Upload some →")));
      return;
    }
    clear(body, h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, "Date"), h("th", {}, "Vendor"),
        h("th", { class: "num" }, "Total"), h("th", { class: "num" }, "Items"), h("th", {}, "Status"), h("th", {}, "Issues"))),
      h("tbody", {}, rows.map((r) => h("tr", {
        class: "clickable", tabindex: "0",
        onclick: () => { location.hash = `#/receipts/${r.id}`; },
        onkeydown: (e) => { if (e.key === "Enter") location.hash = `#/receipts/${r.id}`; },
      },
      h("td", { class: "muted" }, r.id),
      h("td", {}, date(r.date)),
      h("td", {}, r.vendor || h("span", { class: "muted" }, r.original_filename || "–"), r.user_edited ? h("span", { class: "badge info", style: "margin-left: 0.4rem" }, "edited") : null),
      h("td", { class: "num" }, money(r.total, r.currency)),
      h("td", { class: "num" }, r.item_count),
      h("td", {}, statusBadge(r.status)),
      h("td", { class: "muted small" }, r.warnings?.length ? `${r.warnings.length} warning${r.warnings.length > 1 ? "s" : ""}` : "")))))));
  }

  let debounce;
  for (const el of Object.values(controls)) {
    el.addEventListener(el === search ? "input" : "change", () => { clearTimeout(debounce); debounce = setTimeout(load, 250); });
  }

  clear(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Receipts"), count),
      h("a", { class: "btn", href: "#/upload" }, "+ Upload")),
    h("div", { class: "card" },
      h("div", { class: "row", style: "margin-bottom: 0.75rem" }, search, status, category,
        h("label", { class: "row small muted" }, "From", from), h("label", { class: "row small muted" }, "to", to),
        h("button", { class: "small", onclick: () => { for (const el of Object.values(controls)) el.value = ""; load(); } }, "Clear")),
      body));
  await load();
}
