// Chat arrives in Phase 7.

import { clear, h } from "../ui.js";

export function render(view) {
  clear(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Chat"), h("div", { class: "muted" }, "Ask questions about your spending."))),
    h("div", { class: "card empty" },
      h("p", {}, "Coming in Phase 7: questions like “How much did I spend on groceries in September?” answered from your stored receipts."),
      h("p", {}, "Meanwhile, the ", h("a", { href: "#/dashboard" }, "Dashboard"), " shows spending by category, vendor and month.")));
}
