// App shell: hash router, navigation, theme, health indicator.

import { api } from "./api.js";
import { clear, errorBox, h, recall, remember } from "./ui.js";

// Each page module exports render(container, params) and may return a cleanup function.
const ROUTES = [
  [/^#\/upload$/, "upload"],
  [/^#\/receipts$/, "receipts"],
  [/^#\/receipts\/(\d+)$/, "receipt", (m) => ({ id: Number(m[1]) })],
  [/^#\/dashboard$/, "dashboard"],
  [/^#\/chat$/, "chat"],
  [/^#\/lab$/, "lab"],
  [/^#\/eval$/, "eval"],
  [/^#\/system$/, "system"],
];

const view = document.getElementById("view");
let cleanup = null;

async function route() {
  const hash = location.hash || "#/upload";
  let match = null;
  for (const [pattern, page, params] of ROUTES) {
    const m = hash.split("?")[0].match(pattern);
    if (m) { match = { page, params: params ? params(m) : {} }; break; }
  }
  if (!match) { location.hash = "#/upload"; return; }

  if (typeof cleanup === "function") cleanup();
  cleanup = null;
  document.querySelectorAll(".nav a, .tabbar a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === (match.page === "receipt" ? "receipts" : match.page));
  });
  document.querySelector(".nav").classList.remove("open");
  document.querySelector(".tab-more").setAttribute("aria-expanded", "false");

  clear(view, h("div", { class: "empty" }, h("span", { class: "spinner" })));
  try {
    const module = await import(`./pages/${match.page}.js`);
    clear(view);
    cleanup = await module.render(view, match.params);
  } catch (error) {
    clear(view, errorBox(error));
    console.error(error);
  }
  view.focus({ preventScroll: true });
}

// ---------------------------------------------------------------- theme

function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}
applyTheme(recall("theme", null));
document.querySelector(".theme-toggle").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = dark ? "light" : "dark";
  applyTheme(next);
  remember("theme", next);
});

// Phones: "More" in the bottom bar opens the full page list at the top.
document.querySelector(".tab-more").addEventListener("click", (event) => {
  const nav = document.querySelector(".nav");
  nav.classList.toggle("open");
  event.currentTarget.setAttribute("aria-expanded", nav.classList.contains("open"));
  if (nav.classList.contains("open")) window.scrollTo({ top: 0, behavior: "smooth" });
});

document.querySelector(".nav-toggle").addEventListener("click", (event) => {
  const nav = document.querySelector(".nav");
  nav.classList.toggle("open");
  event.currentTarget.setAttribute("aria-expanded", nav.classList.contains("open"));
});

// ---------------------------------------------------------------- health

async function checkHealth() {
  const dot = document.querySelector(".health-dot");
  const banner = document.getElementById("banner");
  try {
    const health = await api.get("/api/system/health");
    dot.className = `health-dot ${health.ok ? "ok" : "bad"}`;
    dot.title = health.ok ? "All systems ready" : "Problem: see System page";
    const problems = [];
    if (!health.ollama.reachable) problems.push("Ollama is not running — receipts cannot be processed. Start Ollama.");
    else if (!health.ollama.models?.extract?.installed) problems.push(`Model ${health.ollama.models?.extract?.name} is not installed (ollama pull).`);
    if (!health.worker.alive) problems.push("The background worker is not running. Restart the server.");
    banner.hidden = problems.length === 0;
    banner.textContent = problems.join(" ");
  } catch {
    dot.className = "health-dot bad";
    banner.hidden = false;
    banner.textContent = "Cannot reach the app on your computer. Check that the computer is on and awake, "
      + "the app is running (Desktop shortcut), and on a phone that Tailscale is on.";
  }
}

// ---------------------------------------------------------------- installable app

// The service worker keeps a copy of the app (not of any data) so it opens even when the
// computer is off. Browsers allow it on https and on this computer only.
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch((error) => console.warn("Service worker:", error));
}

// Chrome/Edge (Android and desktop) offer installing; show our own button for it.
let installPrompt = null;
const installButton = document.querySelector(".install-app");
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  installButton.hidden = false;
});
installButton.addEventListener("click", async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  installButton.hidden = true;
});
window.addEventListener("appinstalled", () => { installButton.hidden = true; });

window.addEventListener("hashchange", route);
route();
checkHealth();
setInterval(checkHealth, 30000);
