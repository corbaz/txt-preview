// TXT Preview frontend: tabs, theme, live markdown preview, embedded browser.
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  function setTab(name) {
    document.querySelectorAll(".seg").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.dataset.page === name));
    if (name === "preview") schedulePreview();
  }

  document.getElementById("segmented").addEventListener("click", (e) => {
    const btn = e.target.closest(".seg");
    if (btn) setTab(btn.dataset.tab);
  });

  // ---- Theme -------------------------------------------------------------
  const themeToggle = $("theme-toggle");
  function applyTheme(theme) {
    document.body.dataset.theme = theme;
    themeToggle.textContent = theme === "dark" ? "Tema: Oscuro" : "Tema: Claro";
    try { localStorage.setItem("txt-theme", theme); } catch (_) {}
  }
  themeToggle.addEventListener("click", () => {
    applyTheme(document.body.dataset.theme === "dark" ? "light" : "dark");
  });

  // ---- Live markdown preview ---------------------------------------------
  let previewTimer = null;
  function schedulePreview() {
    if (previewTimer) return;
    previewTimer = setTimeout(() => {
      previewTimer = null;
      renderPreviewNow();
    }, 150);
  }

  async function renderPreviewNow() {
    const text = $("editor").value;
    if (!window.pywebview || !window.pywebview.api) return;
    const html = await window.pywebview.api.render_preview(text);
    $("preview").innerHTML = html;
  }

  $("editor").addEventListener("input", () => {
    if (document.querySelector(".page[data-page='preview']").classList.contains("active")) {
      schedulePreview();
    }
  });

  // ---- Embedded browser ---------------------------------------------------
  function normalizeAddress(raw) {
    const value = raw.trim();
    if (!value) return "";
    if (/^https?:\/\//i.test(value)) return value;
    return "https://" + value;
  }

  $("browser-go").addEventListener("click", () => {
    const url = normalizeAddress($("browser-address").value);
    if (url) $("browser-frame").src = url;
  });

  $("browser-address").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const url = normalizeAddress($("browser-address").value);
      if (url) $("browser-frame").src = url;
    }
  });

  function setStatus(message) {
    $("status-message").textContent = message;
  }

  window.addEventListener("pywebviewready", async () => {
    let theme = "dark";
    try { theme = localStorage.getItem("txt-theme") || "dark"; } catch (_) {}
    applyTheme(theme);
    const version = await window.pywebview.api.app_version();
    $("version-badge").textContent = "v" + version;
    setStatus("Listo.");
  });

  // Exposed for future steps (T4 speech, T2 actions).
  window.txtUI = { setTab, setStatus, renderPreviewNow };
})();
