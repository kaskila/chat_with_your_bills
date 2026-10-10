// Upload receipt photos and watch them being processed.

import { api } from "../api.js";
import { webcamPanel, webcamSupported } from "../camera.js";
import { jobCard } from "../jobs.js";
import { shrinkPhoto } from "../resize.js";
import { clear, h, spinner, statusBadge, toast } from "../ui.js";

export async function render(view) {
  const cards = [];
  const list = h("div", { class: "stack" });
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", multiple: true, hidden: true });
  const touch = matchMedia("(pointer: coarse)").matches;
  const zone = h("div", { class: "dropzone", tabindex: "0", role: "button", "aria-label": "Choose receipt photos" },
    h("div", { class: "big" }, touch ? "Tap to choose photos" : "Drop receipt photos here, or click to choose"),
    h("div", { class: "muted small" }, "JPEG, PNG or WEBP, up to 15 MB each. Several at once is fine: they are processed one after another."));

  // Phone/tablet: open the device camera app directly. Laptop: live webcam panel.
  const cameraInput = h("input", { type: "file", accept: "image/*", capture: "environment", hidden: true });
  const cameraSlot = h("div");
  let webcam = null;
  const closeWebcam = () => { webcam?.stop(); webcam = null; clear(cameraSlot); };
  const openWebcam = () => {
    closeWebcam();
    webcam = webcamPanel({ onPhoto: (file) => { closeWebcam(); send([file]); }, onClose: closeWebcam });
    clear(cameraSlot, webcam.el);
  };
  const sources = h("div", { class: "row capture-buttons" },
    touch ? h("button", { class: "primary", type: "button", onclick: () => cameraInput.click() }, "Take photo") : null,
    webcamSupported() ? h("button", { type: "button", onclick: openWebcam }, "Use webcam") : null);
  cameraInput.addEventListener("change", () => { send([...cameraInput.files]); cameraInput.value = ""; });

  const progress = h("div", { class: "upload-progress", hidden: true, "aria-live": "polite" });

  async function send(files) {
    if (!files.length) return;
    let results;
    const plural = files.length > 1 ? `${files.length} photos` : "photo";
    progress.hidden = false;
    try {
      clear(progress, spinner(`Preparing ${plural}…`));
      const small = await Promise.all(files.map(shrinkPhoto));
      const kb = Math.round(small.reduce((sum, f) => sum + f.size, 0) / 1024);
      clear(progress, spinner(`Uploading ${plural} (${kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`})…`));
      results = await api.upload("/api/receipts", small);
    } catch (error) {
      toast(error.message, "error");
      return;
    } finally {
      progress.hidden = true;
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
    zone, input, cameraInput, sources.childElementCount ? sources : null, progress, cameraSlot,
    h("div", { style: "margin-top: 1rem" }, list));

  // Jobs still running from earlier (e.g. after navigating away).
  try {
    const active = await api.get("/api/jobs?active=true");
    for (const job of active.reverse()) {
      const card = jobCard(job.id, `Receipt #${job.receipt_id}`);
      cards.push(card);
      list.prepend(card.el);
    }
  } catch { /* the banner reports server problems */ }

  return () => { cards.forEach((c) => c.stop()); closeWebcam(); };
}
