// Health of every part the app depends on.

import { api } from "../api.js";
import { clear, errorBox, h, seconds, spinner, toast } from "../ui.js";

const yes = (ok, good = "Yes", bad = "No") => h("span", { class: `badge ${ok ? "verified" : "failed"}` }, ok ? `✓ ${good}` : `✕ ${bad}`);

export async function render(view) {
  const body = h("div", { class: "stack" }, spinner("Checking…"));
  let timer;

  async function load() {
    let st;
    try { st = await api.get("/api/system/health"); } catch (error) { clear(body, errorBox(error)); return; }
    const o = st.ollama;
    const models = o.models || {};
    clear(body,
      h("div", { class: `msg ${st.ok ? "ok" : "error"}` }, st.ok ? "Everything needed to process receipts is ready."
        : "Something needs attention before receipts can be processed — see below."),
      h("div", { class: "grid grid-2" },
        h("div", { class: "card" }, h("h2", {}, "Ollama (local models)"),
          h("dl", { class: "kv" },
            h("dt", {}, "Reachable"), h("dd", {}, yes(o.reachable), " ", h("span", { class: "muted small" }, o.host)),
            ...(o.reachable ? Object.entries(models).flatMap(([role, m]) => [
              h("dt", {}, role === "extract" ? "Extraction model" : "Vision model"),
              h("dd", {}, h("code", {}, m.name), " ", yes(m.installed, "installed", "missing"), " ",
                m.loaded ? h("span", { class: "badge info" }, "in memory") : h("span", { class: "badge neutral" }, "not loaded"),
                !m.installed ? h("div", { class: "small muted" }, "Install with: ", h("code", {}, `ollama pull ${m.name}`)) : null),
            ]) : [h("dt", {}, "Error"), h("dd", {}, o.error, h("div", { class: "small muted" }, "Start the Ollama app, then refresh."))])),
          h("div", { class: "row", style: "margin-top: 0.75rem" },
            h("button", { onclick: warm, disabled: st.warmup.running }, st.warmup.running ? spinner("Loading…") : "Warm up model"),
            h("span", { class: "muted small" }, st.warmup.error ? st.warmup.error
              : st.warmup.seconds !== null ? `Last warm-up took ${seconds(st.warmup.seconds)}.` : "Loads the extraction model so the first receipt is faster."))),
        h("div", { class: "card" }, h("h2", {}, "Processing"),
          h("dl", { class: "kv" },
            h("dt", {}, "Worker"), h("dd", {}, yes(st.worker.alive, "running", "stopped")),
            h("dt", {}, "Current job"), h("dd", {}, st.worker.current_job ? h("code", {}, st.worker.current_job.slice(0, 8)) : "idle"),
            h("dt", {}, "Queued"), h("dd", {}, st.worker.queued),
            h("dt", {}, "Database"), h("dd", { class: "small" }, st.database.path),
            h("dt", {}, "Schema"), h("dd", {}, `version ${st.database.schema_version}`),
            h("dt", {}, "Receipts"), h("dd", {}, Object.entries(st.database.receipts).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", ") || "none"),
            h("dt", {}, "Python"), h("dd", {}, st.versions.python)))),
      h("div", { class: "card" }, h("h2", {}, "Settings"),
        h("p", { class: "muted small" }, "Change these with BILLS_* environment variables or a .env file (see .env.example), then restart the server."),
        h("div", { class: "table-wrap" }, h("table", {}, h("tbody", {}, Object.entries(st.settings).map(([k, v]) =>
          h("tr", {}, h("td", {}, h("code", {}, k)), h("td", {}, String(v)))))))),
      h("div", { class: "msg note" }, "Tip: on a laptop, keep the charger plugged in. On battery Windows slows the CPU and a receipt can take ten times longer."));
    timer = setTimeout(load, 10000);
  }

  async function warm() {
    try { await api.post("/api/system/warmup"); toast("Loading the model…"); clearTimeout(timer); load(); } catch (error) { toast(error.message, "error"); }
  }

  clear(view, h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "System"), h("div", { class: "muted" }, "Is everything ready?"))), body);
  await load();
  return () => clearTimeout(timer);
}
