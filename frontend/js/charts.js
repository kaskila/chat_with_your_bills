// Minimal SVG charts: horizontal bars (ranking) and columns (over time).
// One series each, so no legend; the card title names what is plotted.
// Values sit at the bar tips; hover shows a tooltip; every chart has a table view.
// Pass `width` = the container's pixel width so text renders at its true size.

import { h, hideTooltip, s, showTooltip } from "./ui.js";

const GAP = 2; // surface gap between adjacent bars

function measure(text, size = 12) {
  // Rough text width for layout (avoids clipping labels); good enough for the system font.
  return String(text).length * size * 0.56;
}

/** Path for a bar with 4px rounded corners at the data end only (anchored square at the baseline). */
function hBarPath(x, y, w, hgt) {
  const r = Math.min(4, w / 2, hgt / 2);
  return `M${x},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + hgt - r} Q${x + w},${y + hgt} ${x + w - r},${y + hgt} H${x} Z`;
}

function vBarPath(x, y, w, hgt) {
  const r = Math.min(4, w / 2, hgt / 2);
  const base = y + hgt;
  return `M${x},${base} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${base} Z`;
}

function withTable(chartEl, rows, columns) {
  const table = h("div", { class: "table-wrap", hidden: true }, h("table", {},
    h("thead", {}, h("tr", {}, columns.map((c) => h("th", { class: c.num ? "num" : "" }, c.label)))),
    h("tbody", {}, rows.map((row) => h("tr", {}, columns.map((c) => h("td", { class: c.num ? "num" : "" }, c.format(row))))))));
  const toggle = h("button", { class: "small", onclick: () => {
    const showTable = table.hidden;
    table.hidden = !showTable;
    chartEl.hidden = showTable;
    toggle.textContent = showTable ? "Chart" : "Table";
  } }, "Table");
  return { toggle, body: h("div", {}, chartEl, table) };
}

/**
 * Horizontal bar ranking. data: [{label, value, detail?}] (already sorted).
 * format(value) for tip labels and tooltips.
 */
export function barChart(data, { format, valueLabel = "Amount", labelHeader = "Name", tooltip, width = 560 } = {}) {
  if (!data.length) return { toggle: null, body: h("div", { class: "empty" }, "No data for this period.") };
  const rowH = 28;
  const labelW = Math.min(180, width * 0.38, Math.max(...data.map((d) => measure(d.label))) + 8);
  const maxTip = Math.max(...data.map((d) => measure(format(d.value)))) + 10;
  const plotW = width - labelW - maxTip;
  const max = Math.max(...data.map((d) => d.value), 0) || 1;
  const height = data.length * rowH;

  const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": data.map((d) => `${d.label}: ${format(d.value)}`).join("; ") });
  data.forEach((d, i) => {
    const y = i * rowH;
    const w = Math.max(1, (d.value / max) * plotW);
    const maxChars = Math.max(6, Math.floor((labelW - 8) / (12 * 0.56)));
    const label = d.label.length > maxChars ? `${d.label.slice(0, maxChars - 1)}…` : d.label;
    const group = s("g", {},
      s("text", { x: labelW - 8, y: y + rowH / 2 + 4, "text-anchor": "end" }, label),
      s("path", { class: "bar", d: hBarPath(labelW, y + GAP / 2 + 3, w, rowH - GAP - 6) }),
      s("text", { class: "value", x: labelW + w + 6, y: y + rowH / 2 + 4 }, format(d.value)),
      // hit target: the whole row, larger than the bar
      s("rect", { class: "hit", x: 0, y, width, height: rowH,
        onmousemove: (e) => { group.classList.add("hover"); showTooltip(e, ...(tooltip ? tooltip(d) : [h("div", {}, d.label), h("b", {}, format(d.value))])); },
        onmouseleave: () => { group.classList.remove("hover"); hideTooltip(); } }));
    svg.append(group);
  });
  svg.prepend(s("line", { class: "axis", x1: labelW, x2: labelW, y1: 0, y2: height }));
  const chart = h("div", { class: "chart" }, svg);
  return withTable(chart, data, [
    { label: labelHeader, format: (d) => d.label },
    { label: valueLabel, num: true, format: (d) => format(d.value) },
    ...(data[0].detail !== undefined ? [{ label: "", format: (d) => d.detail }] : []),
  ]);
}

/** Columns over time. data: [{label, value, detail?}] in time order. */
export function columnChart(data, { format, shortFormat = format, valueLabel = "Amount", labelHeader = "Period", tooltip, width = 560 } = {}) {
  if (!data.length) return { toggle: null, body: h("div", { class: "empty" }, "No dated receipts in this period.") };
  const height = 220;
  const top = 22;
  const bottom = 24;
  const plotH = height - top - bottom;
  const band = width / Math.max(data.length, 4);
  const barW = Math.min(64, band - GAP - 16);
  const max = Math.max(...data.map((d) => d.value), 0) || 1;

  const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": data.map((d) => `${d.label}: ${format(d.value)}`).join("; ") });
  svg.append(s("line", { class: "axis", x1: 0, x2: width, y1: top + plotH, y2: top + plotH }));
  data.forEach((d, i) => {
    const x = i * band + (band - barW) / 2;
    const hgt = Math.max(1, (d.value / max) * plotH);
    const y = top + plotH - hgt;
    const group = s("g", {},
      s("path", { class: "bar", d: vBarPath(x, y, barW, hgt) }),
      s("text", { class: "value", x: x + barW / 2, y: y - 6, "text-anchor": "middle" }, shortFormat(d.value)),
      s("text", { x: x + barW / 2, y: height - 6, "text-anchor": "middle" }, d.label),
      s("rect", { class: "hit", x: i * band, y: 0, width: band, height,
        onmousemove: (e) => { group.classList.add("hover"); showTooltip(e, ...(tooltip ? tooltip(d) : [h("div", {}, d.label), h("b", {}, format(d.value))])); },
        onmouseleave: () => { group.classList.remove("hover"); hideTooltip(); } }));
    svg.append(group);
  });
  const chart = h("div", { class: "chart" }, svg);
  return withTable(chart, data, [
    { label: labelHeader, format: (d) => d.label },
    { label: valueLabel, num: true, format: (d) => format(d.value) },
    ...(data[0].detail !== undefined ? [{ label: "", format: (d) => d.detail }] : []),
  ]);
}
