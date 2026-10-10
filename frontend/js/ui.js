// Small DOM and formatting helpers shared by all pages.

/** h("div", {class: "x", onclick}, child, "text", [more]) -> element. Text is never parsed as HTML. */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key in el && typeof value !== "string") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function clear(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

const SVG_NS = "http://www.w3.org/2000/svg";
export function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null) continue;
    if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

// ---------------------------------------------------------------- formatting

export function money(value, currency) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "–";
  const n = Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (!currency || currency === "unknown") return n;
  const symbol = { ZMW: "K", USD: "$", EUR: "€" }[currency];
  return symbol ? `${symbol}${n}` : `${n} ${currency}`;
}

export function shortMoney(value, currency) {
  const n = Number(value) || 0;
  const symbol = { ZMW: "K", USD: "$", EUR: "€" }[currency] || "";
  const compact = n >= 10000 ? `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}k` : n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return `${symbol}${compact}`;
}

export function date(value) {
  if (!value) return "–";
  const d = new Date(`${value}T00:00:00`);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function seconds(value) {
  if (value === null || value === undefined) return "–";
  return value >= 90 ? `${Math.floor(value / 60)} min ${Math.round(value % 60)} s` : `${Number(value).toFixed(value < 10 ? 1 : 0)} s`;
}

export function pct(value) {
  return value === null || value === undefined ? "–" : `${(value * 100).toFixed(1)}%`;
}

// ---------------------------------------------------------------- badges & messages

const STATUS_LABEL = {
  verified: "✓ Verified", needs_review: "! Needs review", failed: "✕ Failed",
  processing: "… Processing", queued: "… Queued", done: "✓ Done",
};

export function statusBadge(status) {
  const cls = status === "done" ? "verified" : status;
  return h("span", { class: `badge ${cls}` }, STATUS_LABEL[status] || status);
}

export const WARNING_LABEL = {
  VALUE_NOT_IN_TEXT: "Value not printed",
  PAYMENT_FAILED: "Transaction failed",
  AMOUNT_UNCLEAR: "Amount unclear",
  ITEMS_SUM_MISMATCH: "Items don't add up",
  TOTAL_MISMATCH: "Totals inconsistent",
  PAYMENT_MISMATCH: "Payment doesn't match",
  LINE_MATH_MISMATCH: "Qty × price ≠ amount",
  NO_ITEMS: "No items",
  NO_TOTAL: "No total",
  BAD_DATE: "Date problem",
  LOW_OCR_CONFIDENCE: "Low OCR confidence",
  IMAGE_QUALITY: "Photo quality",
  POSSIBLE_DUPLICATE: "Possible duplicate",
  OCR_DISAGREEMENT: "Readings disagree",
  FAILED: "Failed",
};

export function warningList(warnings) {
  if (!warnings?.length) return null;
  return h("div", {}, warnings.map((w) =>
    h("div", { class: "msg warning" }, h("b", {}, WARNING_LABEL[w.code] || w.code), w.message)));
}

export function toast(message, kind = "info", ms = 4000) {
  const el = h("div", { class: `toast ${kind}` }, message);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), ms);
}

export function spinner(text) {
  return h("span", { class: "row" }, h("span", { class: "spinner" }), text ? h("span", { class: "muted" }, text) : null);
}

export function errorBox(error) {
  return h("div", { class: "msg error" }, error?.message || String(error));
}

// ---------------------------------------------------------------- tooltip

const tip = () => document.getElementById("tooltip");

export function showTooltip(event, ...content) {
  const el = tip();
  clear(el, ...content);
  el.hidden = false;
  const pad = 14;
  const { innerWidth, innerHeight } = window;
  const rect = el.getBoundingClientRect();
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + rect.width > innerWidth - 8) x = event.clientX - rect.width - pad;
  if (y + rect.height > innerHeight - 8) y = event.clientY - rect.height - pad;
  el.style.left = `${Math.max(8, x)}px`;
  el.style.top = `${Math.max(8, y)}px`;
}

export function hideTooltip() {
  tip().hidden = true;
}

// ---------------------------------------------------------------- storage (per-viewer conveniences only)

export function remember(key, value) {
  try { localStorage.setItem(`bills.${key}`, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

export function recall(key, fallback) {
  try {
    const raw = localStorage.getItem(`bills.${key}`);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}
