// Pipeline Lab: run one stage at a time on an image or on pasted text.

import { api } from "../api.js";
import { clear, errorBox, h, s, seconds, spinner, warningList } from "../ui.js";

export async function render(view) {
  let file = null;
  const fileInput = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp" });
  const imageOut = h("div");
  const ocrText = h("textarea", { rows: 14, placeholder: "OCR text appears here. You can also paste or edit text and run Extract on it." });
  const ocrInfo = h("div", { class: "muted small" });
  const extractOut = h("div");
  const busy = (el, text) => clear(el, spinner(text));

  const needFile = () => {
    if (!file) { clear(imageOut, h("div", { class: "msg warning" }, "Choose an image first.")); return false; }
    return true;
  };

  async function runPreprocess() {
    if (!needFile()) return;
    busy(imageOut, "Preprocessing…");
    const form = new FormData();
    form.append("file", file);
    try {
      const r = await fetchForm("/api/lab/preprocess", form);
      clear(imageOut,
        h("img", { class: "receipt-image", src: `data:image/jpeg;base64,${r.cropped_jpeg_base64}`, alt: "Cropped receipt" }),
        h("dl", { class: "kv", style: "margin-top: 0.6rem" },
          h("dt", {}, "Crop"), h("dd", {}, `${r.crop_method}, receipt is ${(r.receipt_fraction * 100).toFixed(0)}% of the photo, rotated ${r.rotation_deg}°`),
          h("dt", {}, "Size"), h("dd", {}, `${r.quality.width}×${r.quality.height} → ${r.cropped_size.join("×")}`),
          h("dt", {}, "Sharpness"), h("dd", {}, `${r.quality.blur_variance} (blurry below 60)`),
          h("dt", {}, "Brightness"), h("dd", {}, r.quality.brightness),
          h("dt", {}, "Warnings"), h("dd", {}, r.quality.warnings.join(", ") || "none"),
          h("dt", {}, "Time"), h("dd", {}, seconds(r.seconds))));
    } catch (error) { clear(imageOut, errorBox(error)); }
  }

  async function runOcr(engine) {
    if (!needFile()) return;
    busy(imageOut, engine === "vlm" ? "The vision model is reading the photo (about a minute)…" : "Running RapidOCR…");
    clear(ocrInfo);
    const form = new FormData();
    form.append("file", file);
    try {
      const r = await fetchForm(`/api/lab/ocr?engine=${engine}`, form);
      const [w, hgt] = r.image_size;
      const overlay = s("svg", { viewBox: `0 0 ${w} ${hgt}`, preserveAspectRatio: "none" },
        (r.lines || []).map((line) => s("rect", { x: line.box[0], y: line.box[1], width: line.box[2] - line.box[0], height: line.box[3] - line.box[1] },
          s("title", {}, `${line.text} (${(line.confidence * 100).toFixed(0)}%)`))));
      clear(imageOut, h("div", { class: "ocr-canvas-wrap" },
        h("img", { src: `data:image/jpeg;base64,${r.image_jpeg_base64}`, alt: "OCR input" }), overlay));
      ocrText.value = r.text;
      clear(ocrInfo, `${r.engine} · ${seconds(r.seconds)}`,
        r.mean_confidence ? ` · confidence ${(r.mean_confidence * 100).toFixed(1)}% · ${r.lines.length} lines (hover a box to see its text)` : "");
    } catch (error) { clear(imageOut, errorBox(error)); }
  }

  async function runExtract() {
    if (!ocrText.value.trim()) { clear(extractOut, h("div", { class: "msg warning" }, "Run OCR or paste text first.")); return; }
    busy(extractOut, "The model is extracting the data (30–90 s on CPU)…");
    try {
      const r = await api.post("/api/lab/extract", { text: ocrText.value });
      const rc = r.receipt;
      clear(extractOut,
        h("div", { class: "row" }, h("span", { class: `badge ${r.status}` }, r.status.replace("_", " ")),
          h("span", { class: "muted small" }, `${seconds(r.seconds)} · ${r.llm_stats?.output_tokens ?? "?"} tokens written`)),
        h("div", { style: "margin-top: 0.6rem" }, warningList(r.warnings)),
        ...(r.notes || []).map((n) => h("div", { class: "msg note" }, n)),
        h("div", { class: "table-wrap", style: "margin-top: 0.6rem" }, h("table", {},
          h("thead", {}, h("tr", {}, ["Description", "Qty", "Unit", "Amount", "Category"].map((t, i) => h("th", { class: i > 0 && i < 4 ? "num" : "" }, t)))),
          h("tbody", {}, rc.items.map((i) => h("tr", {}, h("td", {}, i.description), h("td", { class: "num" }, i.quantity ?? ""),
            h("td", { class: "num" }, i.unit_price ?? ""), h("td", { class: "num" }, i.amount), h("td", {}, i.category)))))),
        h("details", { style: "margin-top: 0.6rem" }, h("summary", {}, "All fields (JSON)"), h("pre", {}, JSON.stringify(rc, null, 2))),
        h("details", {}, h("summary", {}, "Raw model output"), h("pre", {}, r.raw)));
    } catch (error) { clear(extractOut, errorBox(error)); }
  }

  fileInput.addEventListener("change", () => {
    file = fileInput.files[0] || null;
    if (file) clear(imageOut, h("img", { class: "receipt-image", src: URL.createObjectURL(file), alt: "Selected photo" }));
  });

  clear(view,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Pipeline Lab"),
      h("div", { class: "muted" }, "Run one stage at a time to see exactly what each step produces. Nothing here is saved."))),
    h("div", { class: "split" },
      h("div", { class: "card stack" },
        h("h2", {}, "1. Image"), fileInput,
        h("div", { class: "row" }, h("button", { onclick: runPreprocess }, "Preprocess"),
          h("button", { onclick: () => runOcr("rapid") }, "RapidOCR"),
          h("button", { onclick: () => runOcr("vlm"), title: "glm-ocr vision model, about a minute on CPU" }, "VLM OCR")),
        imageOut),
      h("div", { class: "stack" },
        h("div", { class: "card stack" }, h("h2", {}, "2. Text"), ocrInfo, ocrText,
          h("button", { class: "primary", onclick: runExtract }, "Extract + check")),
        h("div", { class: "card" }, h("h2", {}, "3. Result"), extractOut))));
}

async function fetchForm(path, form) {
  const response = await fetch(path, { method: "POST", body: form });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `${response.status} ${response.statusText}`);
  return data;
}
