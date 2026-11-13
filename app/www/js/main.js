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
  const themeSelect = $("theme-select");
  function applyTheme(theme, persist) {
    document.body.dataset.theme = theme;
    themeToggle.textContent = theme === "dark" ? "Tema: Oscuro" : "Tema: Claro";
    if (themeSelect) themeSelect.value = theme;
    try { localStorage.setItem("txt-theme", theme); } catch (_) {}
    if (persist && window.pywebview && window.pywebview.api) {
      window.pywebview.api.set_theme(theme);
    }
  }
  themeToggle.addEventListener("click", () => {
    applyTheme(document.body.dataset.theme === "dark" ? "light" : "dark", true);
  });
  if (themeSelect) {
    themeSelect.addEventListener("change", () => {
      applyTheme(themeSelect.value, true);
    });
  }

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
    wrapSpeechWords();
  }

  $("editor").addEventListener("input", () => {
    if (document.querySelector(".page[data-page='preview']").classList.contains("active")) {
      schedulePreview();
    }
  });

  // ---- Speech word spans (T4) ---------------------------------------------
  const TOKEN = /\S+/g;

  function wrapSpeechWords() {
    const root = $("preview");
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => {
        const parent = node.parentElement;
        if (!parent || /^(script|style)$/i.test(parent.tagName)) return NodeFilter.FILTER_REJECT;
        return TOKEN.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    const textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);
    let index = 0;
    for (const node of textNodes) {
      const value = node.nodeValue;
      const fragment = document.createDocumentFragment();
      let lastIndex = 0;
      TOKEN.lastIndex = 0;
      let match;
      while ((match = TOKEN.exec(value)) !== null) {
        if (match.index > lastIndex) {
          fragment.appendChild(document.createTextNode(value.slice(lastIndex, match.index)));
        }
        const span = document.createElement("span");
        span.className = "sw";
        span.dataset.i = String(index++);
        span.textContent = match[0];
        fragment.appendChild(span);
        lastIndex = match.index + match[0].length;
      }
      if (lastIndex < value.length) {
        fragment.appendChild(document.createTextNode(value.slice(lastIndex)));
      }
      node.parentNode.replaceChild(fragment, node);
    }
  }

  function getSpeechWords() {
    return Array.from(document.querySelectorAll("#preview .sw"))
      .map((span) => span.textContent)
      .join("\n");
  }

  function setSpeechWordIndex(wordIndex) {
    const previous = document.querySelector("#preview .sw.speaking");
    if (previous) previous.classList.remove("speaking");
    const span = wordIndex >= 0
      ? document.querySelector(`#preview .sw[data-i="${wordIndex}"]`)
      : null;
    if (span) {
      span.classList.add("speaking");
      span.scrollIntoView({ block: "nearest" });
    }
  }

  function clearSpeechProgress() {
    document.querySelectorAll("#preview .sw.speaking")
      .forEach((span) => span.classList.remove("speaking"));
  }

  // Clicking a word restarts the reading from that word (legacy Move-SpeechToWord).
  $("preview").addEventListener("click", (e) => {
    const span = e.target.closest(".sw");
    if (!span || !window.pywebview || !window.pywebview.api) return;
    const index = parseInt(span.dataset.i, 10);
    if (!Number.isNaN(index)) {
      window.pywebview.api.speech_click(index, getSpeechTextFrom(index));
    }
  });

  // Legacy getSpeechTextFrom: words from the clicked one on, with block
  // changes as newlines so the Edge chunker still splits paragraphs.
  function speechBlockOf(node) {
    for (; node; node = node.parentNode) {
      if (node.tagName && /^(P|LI|H[1-6]|TD|TH|PRE|BLOCKQUOTE|DIV|DT|DD|BODY)$/i.test(node.tagName)) {
        return node;
      }
    }
    return null;
  }

  function getSpeechTextFrom(wordIndex) {
    const spans = document.querySelectorAll("#preview .sw");
    const parts = [];
    let previousBlock = null;
    for (let index = Math.max(0, wordIndex); index < spans.length; index++) {
      const span = spans[index];
      const currentBlock = speechBlockOf(span.parentNode);
      if (parts.length) parts.push(currentBlock === previousBlock ? " " : "\n");
      parts.push(span.textContent);
      previousBlock = currentBlock;
    }
    return parts.join("");
  }

  // ---- Speech controls -----------------------------------------------------
  let speechState = null;

  function applySpeechState(state) {
    if (!state) return;
    speechState = state;
    if (state.mode === "Playing" || state.mode === "Paused") {
      if (typeof state.highlight_word_index === "number") {
        setSpeechWordIndex(state.highlight_word_index);
      }
    } else {
      clearSpeechProgress();
    }
    $("speech-pause").textContent = state.mode === "Paused" ? "Continuar" : "Pausar";
    if (state.message) setStatus(state.message);
  }

  async function speechTick() {
    if (!window.pywebview || !window.pywebview.api) return;
    try {
      applySpeechState(await window.pywebview.api.speech_tick());
    } catch (_) { /* the tick is best effort */ }
  }

  $("speech-play").addEventListener("click", () => {
    if (!window.pywebview || !window.pywebview.api) return;
    window.pywebview.api.start_speech($("editor").value, getSpeechWords());
  });

  $("speech-pause").addEventListener("click", () => {
    if (!window.pywebview || !window.pywebview.api) return;
    if (speechState && speechState.mode === "Paused") {
      window.pywebview.api.resume_speech();
    } else {
      window.pywebview.api.pause_speech();
    }
  });

  $("speech-replay").addEventListener("click", () => {
    if (!window.pywebview || !window.pywebview.api) return;
    window.pywebview.api.replay_start(0);
  });

  // ---- Preview exports & clipboard (T6) -------------------------------------
  // Legacy Export-PreviewPdf / Export-SpeechMp3 / Copy MD / Copy TXT:
  // the Api works on the session preview text (what Vista previa shows),
  // not on the editor.
  async function withBusy(button, busyMessage, action) {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !button) return;
    button.disabled = true;
    setStatus(busyMessage);
    try {
      const result = await action(api);
      if (result && result.message) setStatus(result.message);
    } finally {
      button.disabled = false;
    }
  }

  $("export-pdf").addEventListener("click", () => {
    withBusy($("export-pdf"), "Generando PDF...", (api) => api.export_pdf());
  });

  $("export-mp3").addEventListener("click", () => {
    withBusy($("export-mp3"), `Generando MP3 con Elvira (es-ES)...`,
      (api) => api.export_mp3());
  });

  async function copyPreview(plain) {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    const text = plain
      ? await api.get_preview_plain_text()
      : await api.get_preview_text();
    if (!text || !text.trim()) {
      setStatus("No hay contenido para copiar.");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setStatus(plain
        ? "Texto sin formato copiado al portapapeles."
        : "Markdown copiado al portapapeles.");
    } catch (_) {
      setStatus("No se pudo copiar al portapapeles.");
    }
  }

  $("copy-md").addEventListener("click", () => copyPreview(false));
  $("copy-txt").addEventListener("click", () => copyPreview(true));

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

  // ---- Configuración (T10/S2) ---------------------------------------------
  const BRIDGE_GROUP_LABELS = ["Groq", "Claude", "Codex", "Gemini"];

  function applyModelCatalog(result) {
    const select = $("model-select");
    const previous = select.value || (select.options[0] && select.options[0].value) || "";
    select.innerHTML = "";
    const groups = {};
    for (const model of result.models || []) {
      const label = BRIDGE_GROUP_LABELS.includes(model.provider) ? model.provider : "Groq";
      (groups[label] = groups[label] || []).push(model);
    }
    for (const label of BRIDGE_GROUP_LABELS) {
      const models = groups[label];
      if (!models || !models.length) continue;
      const group = document.createElement("optgroup");
      if (label === "Groq") {
        group.label = "Groq";
      } else {
        const key = models[0].bridge;
        group.label = `${label} · ${result.bridge_status[key] || ""}`;
      }
      for (const model of models) {
        const option = document.createElement("option");
        option.value = model.id;
        option.textContent = model.name || model.id;
        option.dataset.provider = label;
        group.appendChild(option);
      }
      select.appendChild(group);
    }
    const hasPrevious = Array.from(select.options).some((o) => o.value === previous);
    if (hasPrevious) select.value = previous;
    select.disabled = false;
  }

  async function saveApiKey() {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    const key = $("api-key").value.trim();
    if (!key) {
      setStatus("Ingresá una API key de Groq.");
      $("api-key").focus();
      return;
    }
    const button = $("save-api-key");
    button.disabled = true;
    try {
      const result = await api.set_api_key(key);
      $("api-key").value = "";
      setStatus(result.masked ? `API key guardada (${result.masked}).` : "API key guardada.");
    } finally {
      button.disabled = false;
    }
  }

  $("save-api-key").addEventListener("click", saveApiKey);
  $("api-key").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      saveApiKey();
    }
  });

  $("update-models").addEventListener("click", async () => {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    const button = $("update-models");
    button.disabled = true;
    setStatus("Buscando modelos disponibles...");
    try {
      const result = await api.update_models();
      if (!result.ok) {
        setStatus(result.error || "Ingresá una API key de Groq.");
        return;
      }
      applyModelCatalog(result);
      setStatus(result.error || "Modelos actualizados.");
    } finally {
      button.disabled = false;
    }
  });

  $("model-select").addEventListener("change", async () => {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    const select = $("model-select");
    const result = await api.set_selected_model(select.value);
    try {
      $("attachment-summary").textContent = await api.get_attachment_summary();
    } catch (_) { /* the summary is best effort */ }
    const option = select.selectedOptions[0];
    const provider = (option && option.dataset.provider) || "Groq";
    setStatus(`Modelo: ${provider === "Groq" ? "Groq · " + select.value : (option ? option.textContent : select.value)}`);
  });

  // ---- In-app update (T11/S4) ---------------------------------------------
  // Legacy Update-AppUpdateControls / Install-AppUpdate messages: the three
  // task-worded states plus the legacy refusal details from txt.ps1.
  function updateStatusMessage(status) {
    if (status.updated) return status.detail; // "Actualizado a X. Reiniciá la aplicación."
    switch (status.state) {
      case "up_to_date": return "Estás en la última versión.";
      case "available":
        return `Nueva versión disponible: ${status.remote_version}. Tocá Actualizar.`;
      case "dirty":
        return "Hay cambios locales: la app no se actualiza sola.";
      default:
        return status.detail || "No se pudo comprobar si hay una versión nueva.";
    }
  }

  function applyUpdateStatus(status) {
    if (!status) return;
    const message = updateStatusMessage(status);
    $("update-status").textContent = message;
    $("apply-update").hidden = status.state !== "available";
    // The notice is also visible from other tabs (legacy startup MessageBox).
    if (status.state === "available" || status.updated) setStatus(message);
  }

  $("check-update").addEventListener("click", async () => {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    const button = $("check-update");
    button.disabled = true;
    $("apply-update").hidden = true;
    $("update-status").textContent = "Buscando una versión nueva en origin/main...";
    try {
      applyUpdateStatus(await api.check_for_updates());
    } catch (_) {
      $("update-status").textContent = "No se pudo comprobar si hay una versión nueva.";
    } finally {
      button.disabled = false;
    }
  });

  $("apply-update").addEventListener("click", async () => {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    const button = $("apply-update");
    button.disabled = true;
    $("check-update").disabled = true;
    $("update-status").textContent = "Aplicando la actualización..."; // legacy
    try {
      applyUpdateStatus(await api.apply_update());
    } catch (_) {
      $("update-status").textContent = "No se pudo aplicar la actualización.";
    } finally {
      button.disabled = false;
      $("check-update").disabled = false;
    }
  });

  window.addEventListener("pywebviewready", async () => {
    let theme = "dark";
    try { theme = localStorage.getItem("txt-theme") || "dark"; } catch (_) {}
    applyTheme(theme);
    const api = window.pywebview && window.pywebview.api;
    if (api) {
      // Persisted settings win over localStorage (legacy Import-AppSettings).
      try {
        const config = await api.get_settings();
        if (config && config.theme) applyTheme(config.theme);
      } catch (_) { /* settings are best effort */ }
    }
    const version = await api.app_version();
    // VERSION already carries the "v:" prefix (legacy $appVersion).
    $("version-badge").textContent = version;
    setStatus("Listo.");
    setInterval(speechTick, 120);
  });

  // ---- AI actions (T5) ------------------------------------------------------
  let speechLanguage = "es";

  const AI_BUSY_LABELS = {
    consult: "Consultando a la IA",
    summarize: "Creando resumen profesional",
    correct: "Corregiendo gramática y ortografía",
    translate_en_es: "Traduciendo con IA",
    translate_es_en: "Traduciendo con IA",
  };

  async function runAi(action) {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    const button = document.querySelector(`[data-ai-action="${action}"]`);
    if (button) button.disabled = true;
    try {
      const model = await api.get_selected_model();
      setStatus(`${AI_BUSY_LABELS[action] || "Consultando a la IA"} · ${model}...`);
      const result = await api.ask_ai(action, $("web-search").checked, $("editor").value);
      if (!result.ok) {
        setStatus(result.error);
        return;
      }
      if (result.editor_action === "replace") {
        $("editor").value = result.text;
      }
      if (result.clipboard && navigator.clipboard) {
        // Legacy Corregir copies the result; the browser clipboard is best effort.
        try { await navigator.clipboard.writeText(result.text); } catch (_) {}
      }
      if (result.speech_language) speechLanguage = result.speech_language;
      await renderPreviewNow();
      setTab("preview");
      setStatus(result.message);
    } finally {
      if (button) button.disabled = false;
    }
  }

  document.querySelectorAll("[data-ai-action]").forEach((button) => {
    button.addEventListener("click", () => runAi(button.dataset.aiAction));
  });

  $("editor").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      runAi("consult");
    }
  });

  // ---- Attachments (T5) ------------------------------------------------------
  function applyAttachments(result) {
    if (!result) return;
    if (result.summary) $("attachment-summary").textContent = result.summary;
    $("clear-attachments").hidden = result.summary.startsWith("Sin archivos");
    if (result.errors && result.errors.length) {
      setStatus(result.errors[0]);
    } else if (result.added && result.added.length) {
      setStatus("Los adjuntos visibles sobre el editor se enviarán en la próxima acción de IA.");
    }
  }

  $("attach-files").addEventListener("click", () => $("attach-input").click());

  $("attach-input").addEventListener("change", async () => {
    const files = Array.from($("attach-input").files || []);
    $("attach-input").value = "";
    const paths = files.map((file) => file.pywebviewFullPath).filter(Boolean);
    if (!window.pywebview || !window.pywebview.api) return;
    if (paths.length) {
      applyAttachments(await window.pywebview.api.add_attachments(paths));
    } else {
      // WebView flavors that hide full paths: resolve through the native dialog.
      applyAttachments(await window.pywebview.api.open_attachment_dialog());
    }
  });

  $("clear-attachments").addEventListener("click", async () => {
    if (!window.pywebview || !window.pywebview.api) return;
    const result = await window.pywebview.api.clear_attachments();
    applyAttachments(result);
    if (result.ok) setStatus(result.message);
  });

  // Exposed for future steps (T2 actions) and tests.
  window.txtUI = {
    setTab, setStatus, renderPreviewNow,
    wrapSpeechWords, getSpeechWords, getSpeechTextFrom,
    setSpeechWordIndex, clearSpeechProgress,
    runAi, applyAttachments, getSpeechLanguage: () => speechLanguage,
    copyPreview, withBusy,
    applyTheme, applyModelCatalog, saveApiKey,
    applyUpdateStatus,
  };
})();
