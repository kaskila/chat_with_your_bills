// Webcam capture: live preview with a receipt guide, capture at the camera's full
// resolution, a quick quality check (same checks as the pipeline), then use or retake.
// Browsers only allow the camera on http://127.0.0.1 / localhost or https.

import { api } from "./api.js";
import { clear, h } from "./ui.js";

export const webcamSupported = () => Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia);

const QUALITY_TEXT = {
  BLURRY: "The photo is blurry: hold the receipt still and let the camera focus.",
  TOO_DARK: "The photo is too dark: add light.",
  OVEREXPOSED: "The photo is washed out: avoid direct light or glare.",
  LOW_RESOLUTION: "The image is very small: move the receipt closer.",
};

/** Returns {el, stop}. onPhoto(file) is called with the accepted JPEG. */
export function webcamPanel({ onPhoto, onClose }) {
  const video = h("video", { autoplay: true, playsinline: true, muted: true });
  const guide = h("div", { class: "camera-guide", "aria-hidden": "true" });
  const stage = h("div", { class: "camera-stage" }, video, guide);
  const info = h("div", { class: "muted small" }, "Starting the camera…");
  const select = h("select", { "aria-label": "Camera", hidden: true });
  const captureButton = h("button", { class: "primary", type: "button", disabled: true }, "Capture");
  const controls = h("div", { class: "row" }, captureButton, select, h("span", { class: "spacer" }),
    h("button", { type: "button", onclick: () => { stop(); onClose?.(); } }, "Close"));
  const body = h("div", { class: "stack" }, stage, info, controls);
  const el = h("div", { class: "card camera" }, h("h2", {}, "Webcam"), body);
  let stream = null;

  function stop() {
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  async function start(deviceId) {
    stop();
    captureButton.disabled = true;
    try {
      // Ask for the highest resolution the camera has: small print needs pixels.
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: {
        ...(deviceId ? { deviceId: { exact: deviceId } } : { facingMode: "environment" }),
        width: { ideal: 3840 }, height: { ideal: 2160 } } });
    } catch (error) {
      clear(info, h("div", { class: "msg error" }, error.name === "NotAllowedError"
        ? "Camera access was blocked. Allow the camera for this site in the browser's address bar, then try again."
        : error.name === "NotFoundError" ? "No camera was found." : `Camera error: ${error.message}`));
      return;
    }
    video.srcObject = stream;
    await video.play().catch(() => {});
    await new Promise((resolve) => (video.videoWidth ? resolve() : video.addEventListener("loadedmetadata", resolve, { once: true })));
    const w = video.videoWidth, hgt = video.videoHeight;
    clear(info, `Camera: ${w} × ${hgt}. Fill the frame with the receipt, flat and well lit.`,
      Math.min(w, hgt) < 1080 ? h("div", { class: "msg warning", style: "margin-top: 0.5rem" },
        "This webcam has a low resolution: hold the receipt close so it fills the frame. A phone photo reads small print better.") : null);
    captureButton.disabled = false;

    const cameras = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
    const current = stream.getVideoTracks()[0]?.getSettings().deviceId;
    select.hidden = cameras.length < 2;
    clear(select, cameras.map((c, i) => h("option", { value: c.deviceId, selected: c.deviceId === current }, c.label || `Camera ${i + 1}`)));
  }

  async function capture() {
    const canvas = h("canvas", { width: video.videoWidth, height: video.videoHeight });
    canvas.getContext("2d").drawImage(video, 0, 0);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    const file = new File([blob], `webcam-${stamp}.jpg`, { type: "image/jpeg" });
    stop();
    review(file, URL.createObjectURL(blob));
  }

  async function review(file, url) {
    const checks = h("div", {}, h("span", { class: "row" }, h("span", { class: "spinner" }), h("span", { class: "muted" }, "Checking the photo…")));
    const use = h("button", { class: "primary", type: "button", onclick: () => { URL.revokeObjectURL(url); onPhoto(file); } }, "Use photo");
    const retake = h("button", { type: "button", onclick: () => { URL.revokeObjectURL(url); clear(body, stage, info, controls); start(select.value || undefined); } }, "Retake");
    clear(body, h("img", { class: "camera-shot", src: url, alt: "Captured photo" }), checks, h("div", { class: "row" }, use, retake));
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await (await fetch("/api/lab/preprocess", { method: "POST", body: form })).json();
      const problems = (result.quality?.warnings || []).map((w) => QUALITY_TEXT[w] || w);
      if (result.crop_method && result.crop_method !== "none" && result.receipt_fraction < 0.3) {
        problems.push("The receipt fills only a small part of the photo: move it closer.");
      }
      clear(checks, problems.length
        ? problems.map((p) => h("div", { class: "msg warning" }, p))
        : h("div", { class: "msg ok" }, "Photo looks good."));
    } catch {
      clear(checks); // the check is only a help; the pipeline checks again
    }
  }

  captureButton.addEventListener("click", capture);
  select.addEventListener("change", () => start(select.value));
  start();
  return { el, stop };
}
