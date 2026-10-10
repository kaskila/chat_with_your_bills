// A card that follows one processing job until it is done.

import { api } from "./api.js";
import { h, clear, money, seconds, statusBadge, WARNING_LABEL } from "./ui.js";

const STAGES = [
  ["queued", "Queued"], ["preprocess", "Prepare"], ["ocr", "OCR"], ["extract", "Extract"],
  ["validate", "Check"], ["vlm", "VLM re-read"], ["vlm_extract", "Re-extract"], ["saving", "Save"],
];
const ORDER = Object.fromEntries(STAGES.map(([key], i) => [key, i]));

/**
 * jobCard(jobId, title) -> { el, stop }. Polls /api/jobs/{id} every 1.5 s until done/failed.
 * onFinish(job) is called once at the end.
 */
export function jobCard(jobId, title, onFinish) {
  const started = Date.now();
  const stageRow = h("div", { class: "stages" });
  const bar = h("div", { style: "width: 2%" });
  const status = h("div", {}, statusBadge("queued"));
  const detail = h("div", { class: "muted small" }, "Waiting in the queue…");
  const result = h("div", { style: "grid-column: 1 / -1" });
  const el = h("div", { class: "card job" },
    h("div", {}, h("b", {}, title), " ", detail), status, stageRow, h("div", { class: "progress" }, bar), result);

  let timer = null;
  let stopped = false;
  let vlmSeen = false;

  function drawStages(stage) {
    if (stage === "vlm" || stage === "vlm_extract") vlmSeen = true;
    const current = ORDER[stage] ?? -1;
    clear(stageRow, STAGES
      .filter(([key]) => vlmSeen || (key !== "vlm" && key !== "vlm_extract"))
      .map(([key, label]) => {
        const i = ORDER[key];
        const cls = stage === "done" || i < current ? "done" : i === current ? "current" : "";
        return h("span", { class: `stage ${cls}` }, label);
      }));
  }

  async function poll() {
    if (stopped) return;
    let job;
    try {
      job = await api.get(`/api/jobs/${jobId}`);
    } catch (error) {
      clear(detail, `Lost contact with the server (${error.message}); retrying…`);
      timer = setTimeout(poll, 3000);
      return;
    }
    const elapsed = (Date.now() - started) / 1000;
    drawStages(job.stage);
    bar.style.width = `${Math.max(2, Math.round((job.progress || 0) * 100))}%`;

    if (job.stage === "queued") {
      clear(detail, job.queue_position ? `Waiting: ${job.queue_position} receipt(s) ahead.` : "Starting next…");
    } else if (job.stage !== "done" && job.stage !== "failed") {
      clear(status, statusBadge("processing"));
      const hint = job.stage === "extract" || job.stage === "vlm_extract" ? " The model is reading the receipt (30–90 s on CPU)."
        : job.stage === "vlm" ? " The vision model is re-reading the photo (about a minute)." : "";
      clear(detail, `${seconds(elapsed)} elapsed.${hint}`);
    }

    if (job.stage === "done" || job.stage === "failed") {
      const r = job.receipt || {};
      clear(status, statusBadge(job.stage === "failed" ? "failed" : r.status || "verified"));
      clear(detail, job.stage === "failed" ? "Processing failed." : `Finished in ${seconds(r.timings?.total_s ?? elapsed)}.`);
      clear(result,
        job.stage === "failed"
          ? h("div", { class: "msg error" }, job.error || r.error || "Unknown error")
          : h("div", { class: "row small" },
            h("span", {}, h("b", {}, r.vendor || "Unknown vendor"), ` · ${r.date || "no date"} · `, h("b", {}, money(r.total, r.currency))),
            r.warnings?.length ? h("span", { class: "muted" }, `· ${r.warnings.map((w) => WARNING_LABEL[w.code] || w.code).join(", ")}`) : null),
        job.receipt_id ? h("div", { class: "small", style: "margin-top: 0.35rem" },
          h("a", { href: `#/receipts/${job.receipt_id}` }, job.stage === "failed" ? "Open receipt to reprocess →" : "Review receipt →")) : null);
      bar.style.width = "100%";
      stopped = true;
      onFinish?.(job);
      return;
    }
    timer = setTimeout(poll, 1500);
  }

  drawStages("queued");
  poll();
  return { el, stop: () => { stopped = true; clearTimeout(timer); } };
}
