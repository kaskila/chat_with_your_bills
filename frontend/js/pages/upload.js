// Upload receipt photos and watch them being processed.

import { api } from "../api.js";
import { jobCard } from "../jobs.js";
import { clear, h, statusBadge, toast } from "../ui.js";

export async function render(view) {
  const cards = [];
  const list = h("div", { class: "stack" });
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", multiple: true, hidden: true });
  const zone = h("div", { class: "dropzone", tabindex: "0", role: "button", "aria-label": "Choose receipt photos" },
    h("div", { class: "big" }, "Drop receipt photos here, or click to choose"),
    h("div", { class: "muted small" }, "JPEG, PNG or WEBP, up to 15 MB each. Several at once is fine: they are processed one after another."));

  async function send(files) {
    if (!files.length) return;
    let results;
    try {
      results = await api.upload("/api/receipts", files);
    } catch (error) {
      toast(error.message, "error");
      return;
    }
    for (const r of results) {
      if (r.error) {
        list.prepend(h("div", { class: "card" }, h("b", {}, r.filename), " ", h("div", { class: "msg error" }, r.error)));
      } else if (r.duplicate) {
        list.prepend(h("div", { class: "card row" }, h("b", {}, r.filename), statusBadge(r.status),
          h("span", { class: "muted" }, "This photo is already stored."),
          h("a", { href: `#/receipts/${r.receipt_id}` }, `Open receipt #${r.receipt_id} →`)));
      } else {
        const card = jobCard(r.job_id, r.filename);
        cards.push(card);
        list.prepend(card.el);
      }
    }
  }

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { send([...input.files]); input.value = ""; });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); send([...e.dataTransfer.files]); });

  clear(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Upload receipts"),
      h("div", { class: "muted" }, "Each photo is read (OCR), turned into data by the local model, and checked. Receipts that fail the checks are re-read by the vision model."))),
    zone, input, h("div", { style: "margin-top: 1rem" }, list));

  // Jobs still running from earlier (e.g. after navigating away).
  try {
    const active = await api.get("/api/jobs?active=true");
    for (const job of active.reverse()) {
      const card = jobCard(job.id, `Receipt #${job.receipt_id}`);
      cards.push(card);
      list.prepend(card.el);
    }
  } catch { /* the banner reports server problems */ }

  return () => cards.forEach((c) => c.stop());
}
