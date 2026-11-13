// TXT Preview frontend: original-layout tabs, context bar, bottom control
// deck, theme, live markdown preview, embedded browser (T15/S8 parity).
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  function setTab(name) {
    document.querySelectorAll(".seg").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.dataset.page === name));
    if (name === "preview") schedulePreview();
  }

  // Configuración is a top-bar tab like the original; every .seg is a tab.
  document.querySelectorAll(".seg").forEach((btn) => {
    btn.addEventListener("click", () => setTab(btn.dataset.tab));
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
    // Editing the editor invalidates the AI response shown in Vista previa
    // (legacy Copy MD/TXT rule: editor content until the preview shows an AI
    // response again).
    previewHasAiResponse = false;
    if (document.querySelector(".page[data-page='preview']").classList.contains("active")) {
      schedulePreview();
    }
  });

  // Legacy copy rule state: true while Vista previa shows an AI response.
  let previewHasAiResponse = false;

  // ---- Speech word spans (T4) ---------------------------------------------
  const TOKEN = /\S+/g;

  function wrapSpeechWords() {
    const root = $("preview");
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => {
        const parent = node.parentElement;
        if (!parent || /^(script|style)$/i.test(parent.tagName)) return NodeFilter.FILTER_REJECT;
        // TOKEN is /\S+/g: reset lastIndex so .test() is deterministic and
        // does not depend on the walker's previous calls (S10).
        TOKEN.lastIndex = 0;
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

  // Clicking a word restarts the reading from that word (legacy Move-SpeechToWord),
  // but only while a reading is active: once it finished (last known mode
  // "Idle") a click must not start the audio by itself (S12).
  $("preview").addEventListener("click", (e) => {
    const span = e.target.closest(".sw");
    if (!span || !window.pywebview || !window.pywebview.api) return;
    if (!speechState || speechState.mode === "Idle") return;
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

  // ---- Speech controls (bottom deck rows 3-4) ------------------------------
  let speechState = null;

  // Legacy label format: m:ss ("0:00").
  function fmtSeconds(totalSeconds) {
    const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    const minutes = Math.floor(seconds / 60);
    const rest = seconds % 60;
    return minutes + ":" + (rest < 10 ? "0" : "") + rest;
  }

  function paintSlider(slider) {
    const min = Number(slider.min) || 0;
    const max = Number(slider.max) || 0;
    if (max <= min) return;
    const pct = ((Number(slider.value) - min) / (max - min)) * 100;
    slider.style.setProperty("--fill", pct + "%");
  }

  let seekDragging = false;

  function updateSeekLabel(seconds, total) {
    $("seek-time").textContent = fmtSeconds(seconds) + " / " + fmtSeconds(total);
  }

  function applySpeechState(state) {
    if (!state) return;
    speechState = state;
    if (state.mode === "Idle") {
      // Legacy KeepHighlight: a speed/voice restart regenerates without
      // clearing where the reading got to.
      clearSpeechProgress();
    } else if (typeof state.highlight_word_index === "number") {
      setSpeechWordIndex(state.highlight_word_index);
    }
    $("speech-pause").textContent = state.mode === "Paused" ? "Continuar" : "Pausar";
    // Replay slider mirrors speech_tick: duration → max, position → value.
    if (typeof state.replay_duration === "number") {
      const seek = $("seek");
      seek.max = String(Math.max(1, Math.round(state.replay_duration * 10)));
      if (!seekDragging) {
        seek.value = String(Math.round((state.replay_position || 0) * 10));
      }
      updateSeekLabel(state.replay_position || 0, state.replay_duration);
      paintSlider(seek);
    }
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

  $("speech-stop").addEventListener("click", () => {
    if (!window.pywebview || !window.pywebview.api) return;
    window.pywebview.api.stop_speech();
    setStatus("Lectura detenida.");
  });

  // Dragging the replay slider only shows the target position; on release
  // the reading restarts there (legacy replaySlider scroll/scrollend).
  $("seek").addEventListener("input", () => {
    seekDragging = true;
    const seek = $("seek");
    updateSeekLabel(Number(seek.value) / 10, Number(seek.max) / 10);
    paintSlider(seek);
  });

  $("seek").addEventListener("change", () => {
    seekDragging = false;
    paintSlider($("seek"));
    if (!window.pywebview || !window.pywebview.api) return;
    if (speechState && speechState.provider === "Replay") {
      window.pywebview.api.replay_start(Number($("seek").value) / 10);
    }
  });

  // ---- Speed slider (bottom deck row 4) ------------------------------------
  const speedSlider = $("speed");
  const speedValue = $("speed-value");

  function speedLabel(percent) {
    return (Number(percent) / 100).toFixed(2).replace(".", ",") + "x";
  }

  speedSlider.addEventListener("input", () => {
    speedValue.textContent = speedLabel(speedSlider.value);
    paintSlider(speedSlider);
  });

  speedSlider.addEventListener("change", () => {
    paintSlider(speedSlider);
    if (!window.pywebview || !window.pywebview.api) return;
    window.pywebview.api.set_speech_speed(Number(speedSlider.value));
  });

  // ---- Editor tools (bottom deck row 2) ------------------------------------
  $("paste-editor").addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text || !text.trim()) {
        setStatus("El portapapeles no contiene texto.");
        return;
      }
      $("editor").value = text;
      $("editor").setSelectionRange(text.length, text.length);
      setStatus("Texto pegado desde el portapapeles.");
    } catch (_) {
      setStatus("No se pudo leer el portapapeles.");
    }
  });

  // Legacy Copy MD/Copy TXT: use the preview content while Vista previa
  // shows an AI response, otherwise the editor text. fetchText picks the
  // preview source (api.get_preview_text / api.get_preview_plain_text).
  async function copyMain(plain, fetchText) {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    let text = "";
    if (previewHasAiResponse) {
      text = await fetchText(api);
    }
    if (!text || !text.trim()) text = $("editor").value;
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

  $("copy-md").addEventListener("click", async () => {
    await copyMain(false, (api) => api.get_preview_text());
  });
  $("copy-txt").addEventListener("click", async () => {
    await copyMain(true, (api) => api.get_preview_plain_text());
  });

  $("clear-chat").addEventListener("click", () => {
    if (!window.pywebview || !window.pywebview.api) return;
    $("editor").value = "";
    $("preview").innerHTML = "";
    previewHasAiResponse = false;
    window.pywebview.api.clear_attachments();
    $("attachment-summary").textContent = "Sin archivos adjuntos para la próxima solicitud";
    $("clear-attachments").hidden = true;
    setTab("editor");
    setStatus("Editor y adjuntos limpiados.");
  });

  // ---- Micrófono (legacy Win+H dictation) -----------------------------------
  $("mic-button").addEventListener("click", async () => {
    if (!window.pywebview || !window.pywebview.api) return;
    try {
      const result = await window.pywebview.api.start_dictation();
      if (result && result.message) setStatus(result.message);
    } catch (_) {
      setStatus("No se pudo activar el dictado.");
    }
  });

  // ---- Cerrar (legacy $form.Close) -------------------------------------------
  $("close-app").addEventListener("click", () => {
    if (!window.pywebview || !window.pywebview.api) return;
    window.pywebview.api.close_app();
  });

  // ---- Preview exports (bottom deck row 2) ----------------------------------
  // Legacy Export-PreviewPdf / Export-SpeechMp3: the Api works on the session
  // preview text (what Vista previa shows), not on the editor.
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
    withBusy($("export-mp3"), "Generando MP3...", (api) => api.export_mp3());
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

  // ---- Configuración (T10/S2) ---------------------------------------------
  const BRIDGE_GROUP_LABELS = ["Groq", "Claude", "Codex", "Gemini"];

  // S11: conservative capability map by exact official model ID (mirrors
  // txt_core/models.py). Unknown IDs stay all-false/unclassified until the
  // catalog — which carries the full capabilities dict — overrides it.
  const MODEL_CAPABILITIES = {
    "llama-3.1-8b-instant": { chat: true, reasoning: false, web: false, vision: false, text_files: true },
    "llama-3.3-70b-versatile": { chat: true, reasoning: false, web: false, vision: false, text_files: true },
    "openai/gpt-oss-120b": { chat: true, reasoning: true, web: true, vision: false, text_files: true },
    "openai/gpt-oss-20b": { chat: true, reasoning: true, web: true, vision: false, text_files: true },
    "qwen/qwen3.8-27b": { chat: true, reasoning: true, web: false, vision: true, text_files: true },
    "minimaxai/minimax-m2.7": { chat: true, reasoning: true, web: false, vision: false, text_files: true },
    "meta-models/muse-spark-open": { chat: true, reasoning: true, web: false, vision: true, text_files: true },
  };
  const FALLBACK_CAPABILITIES = { chat: false, reasoning: false, web: false, vision: false, text_files: false };
  const CAP_TITLES = {
    chat: "Chat de texto",
    reasoning: "Razonamiento",
    web: "Navegación y búsqueda web",
    vision: "Visión: entiende imágenes",
    text_files: "Adjuntar documentos: texto, PDF, Word y PowerPoint",
  };

  // Capabilities of every catalog entry (Groq and bridges): kept by id so a
  // selection can read the live dict instead of guessing.
  const catalogCapabilities = {};
  let lastCapabilityModel = null;
  // The model the session currently points at; a rejected change reverts to it.
  let selectedModelId = "openai/gpt-oss-120b";

  function capabilitiesFor(modelId) {
    return catalogCapabilities[modelId] || MODEL_CAPABILITIES[modelId] || FALLBACK_CAPABILITIES;
  }

  // S11: live capability badges/gates for the selected model — icon states
  // and tooltips, the web checkbox, and the attachment button.
  function applySelectedModelCapabilities(modelId) {
    const caps = capabilitiesFor(modelId);
    document.querySelectorAll(".cap[data-capability]").forEach((span) => {
      const key = span.dataset.capability;
      const supported = !!caps[key];
      span.classList.toggle("off", !supported);
      span.title = `${CAP_TITLES[key]} — ${supported ? "disponible en este modelo" : "no disponible en este modelo"}`;
    });
    if (modelId === lastCapabilityModel) return; // same model: keep the user's choice
    lastCapabilityModel = modelId;
    const webSupported = !!caps.web;
    const webCheckbox = $("web-search");
    webCheckbox.disabled = !webSupported;
    webCheckbox.checked = webSupported; // web model: checked by default; otherwise gated off
    const attachButton = $("attach-files");
    const canAttach = !!caps.text_files || !!caps.vision;
    attachButton.disabled = !canAttach;
    attachButton.title = canAttach
      ? "Adjuntar archivos al contexto"
      : "El modelo elegido no admite archivos adjuntos";
  }

  // S9: preferredModel preselects the persisted model (startup load); without
  // it the catalog keeps whatever the selector already shows.
  function applyModelCatalog(result, preferredModel) {
    const select = $("model-select");
    // S11: catalog entries carry the full capabilities dict; remember them.
    for (const model of result.models || []) {
      if (model.capabilities) catalogCapabilities[model.id] = model.capabilities;
    }
    const previous = preferredModel || select.value
      || (select.options[0] && select.options[0].value) || "";
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
    if (previous && !hasPrevious) {
      // A persisted model missing from the catalog stays selectable.
      const option = document.createElement("option");
      option.value = previous;
      option.textContent = previous;
      select.appendChild(option);
    }
    if (previous) select.value = previous;
    select.disabled = select.options.length === 0;
    // The catalog may have resolved the capabilities of the shown model.
    applySelectedModelCapabilities(select.value);
  }

  // S9: startup model load — the persisted model is preselected and the
  // catalog arrives without visiting Configuración or clicking Actualizar
  // modelos. update_models already caches and returns fallback models on a
  // Groq error.
  async function loadStartupModels(selectedModel) {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    const select = $("model-select");
    if (selectedModel) {
      if (!Array.from(select.options).some((o) => o.value === selectedModel)) {
        const option = document.createElement("option");
        option.value = selectedModel;
        option.textContent = selectedModel;
        select.appendChild(option);
      }
      select.value = selectedModel;
    }
    const status = $("status-message");
    const wasReady = !status.textContent || status.textContent === "Listo.";
    if (wasReady) setStatus("Cargando modelos...");
    try {
      const result = await api.update_models();
      if (result.ok) {
        applyModelCatalog(result, selectedModel);
        applySelectedModelCapabilities(select.value);
        selectedModelId = select.value;
        if (wasReady && status.textContent === "Cargando modelos...") {
          setStatus("Listo.");
        }
        return;
      }
      // No API key: keep the default option.
      setStatus(result.error || "No se pudo cargar el catálogo de modelos.");
    } catch (_) {
      // Keep the default option; the selector only becomes usable when there
      // is more than one known model.
    } finally {
      if (select.options.length > 1) select.disabled = false;
    }
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
      applySelectedModelCapabilities($("model-select").value);
      selectedModelId = $("model-select").value;
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
    if (!result.ok) {
      // S11: a rejected selection (non-chat/unknown) reverts to the session
      // model and surfaces the reason.
      setStatus(result.error);
      select.value = selectedModelId;
      applySelectedModelCapabilities(selectedModelId);
      return;
    }
    selectedModelId = select.value;
    applySelectedModelCapabilities(select.value);
    try {
      $("attachment-summary").textContent = await api.get_attachment_summary();
    } catch (_) { /* the summary is best effort */ }
    const option = select.selectedOptions[0];
    const provider = (option && option.dataset.provider) || "Groq";
    setStatus(`Modelo: ${provider === "Groq" ? "Groq · " + select.value : (option ? option.textContent : select.value)}`);
  });

  // ---- Voz Edge (T4/S6) -----------------------------------------------------
  // Legacy voice catalog: es/en voices from edge-tts; the Hombre/Mujer and
  // Español/Inglés toggles filter the catalog client-side and the selection
  // persists through set_speech_voice.
  const VOICE_GROUP_LABELS = { es: "Español", en: "English" };
  let voiceCatalog = [];

  function applyVoiceCatalog(result, selectedVoice) {
    const select = $("voice-select");
    if (!select) return;
    voiceCatalog = result.voices || [];
    const previous = selectedVoice || select.value;
    select.innerHTML = "";
    const groups = {};
    for (const voice of voiceCatalog) {
      const language = (voice.culture || "").slice(0, 2);
      (groups[language] = groups[language] || []).push(voice);
    }
    for (const language of Object.keys(groups).sort()) {
      const group = document.createElement("optgroup");
      group.label = VOICE_GROUP_LABELS[language] || language;
      for (const voice of groups[language]) {
        const option = document.createElement("option");
        option.value = voice.name;
        option.textContent = voice.display_name;
        group.appendChild(option);
      }
      select.appendChild(group);
    }
    const hasPrevious = Array.from(select.options).some((o) => o.value === previous);
    if (previous && !hasPrevious) {
      // A persisted voice missing from the catalog stays selectable.
      const option = document.createElement("option");
      option.value = previous;
      option.textContent = previous;
      select.appendChild(option);
    }
    if (previous) select.value = previous;
    select.disabled = false;
  }

  async function refreshVoices(force, selectedVoice) {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    const button = $("update-voices");
    if (button) button.disabled = true;
    try {
      const result = await api.list_voices(!!force);
      if (!result.ok) {
        setStatus(result.error || "No se pudo cargar el catálogo de voces Edge.");
        return;
      }
      applyVoiceCatalog(result, selectedVoice);
      if (result.warning) setStatus(result.warning);
    } finally {
      if (button) button.disabled = false;
    }
  }

  $("update-voices").addEventListener("click", () => refreshVoices(true));

  // Gender/language toggles (legacy radio groups): pick the first catalog
  // voice matching gender + culture and persist it.
  function voiceFilterActive(toggleId) {
    return $(toggleId).getAttribute("aria-pressed") === "true";
  }

  function selectedVoiceFilter() {
    const gender = voiceFilterActive("gender-male") ? "Male" : "Female";
    const culture = voiceFilterActive("lang-es") ? "es" : "en";
    return { gender, culture };
  }

  async function selectVoiceByFilter() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !voiceCatalog.length) return;
    const { gender, culture } = selectedVoiceFilter();
    const voice = voiceCatalog.find((candidate) =>
      candidate.gender === gender
      && String(candidate.culture || "").slice(0, 2) === culture);
    if (!voice) return;
    const select = $("voice-select");
    if (!Array.from(select.options).some((o) => o.value === voice.name)) {
      const option = document.createElement("option");
      option.value = voice.name;
      option.textContent = voice.display_name;
      select.appendChild(option);
    }
    select.value = voice.name;
    const result = await api.set_speech_voice(voice.name);
    if (result && result.ok) setStatus(`Voz Edge: ${result.voice}`);
  }

  // Radio-like groups (legacy New-ToggleGroup panels): one active per group.
  const VOICE_TOGGLE_GROUPS = {
    "gender-male": ["gender-male", "gender-female"],
    "gender-female": ["gender-male", "gender-female"],
    "lang-es": ["lang-es", "lang-en"],
    "lang-en": ["lang-es", "lang-en"],
  };

  function activateVoiceToggle(toggleId) {
    for (const id of VOICE_TOGGLE_GROUPS[toggleId]) {
      $(id).setAttribute("aria-pressed", String(id === toggleId));
    }
    selectVoiceByFilter();
  }

  $("gender-male").addEventListener("click", () => activateVoiceToggle("gender-male"));
  $("gender-female").addEventListener("click", () => activateVoiceToggle("gender-female"));
  $("lang-es").addEventListener("click", () => activateVoiceToggle("lang-es"));
  $("lang-en").addEventListener("click", () => activateVoiceToggle("lang-en"));

  $("voice-select").addEventListener("change", async () => {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    const result = await api.set_speech_voice($("voice-select").value);
    if (result && result.ok) setStatus(`Voz Edge: ${result.voice}`);
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
    let config = null;
    if (api) {
      // Persisted settings win over localStorage (legacy Import-AppSettings).
      try {
        config = await api.get_settings();
      } catch (_) { /* settings are best effort */ }
      if (config && config.theme) applyTheme(config.theme);
      // S10: apply the persisted speed to the slider before the first paint,
      // then paint both sliders so fill and thumb agree from the first
      // render (not only after the first input event).
      if (config && typeof config.speed === "number") {
        speedSlider.value = String(config.speed);
        speedValue.textContent = speedLabel(config.speed);
      }
      paintSlider(speedSlider);
      paintSlider($("seek"));
      // Legacy voice catalog load: cache first, edge-tts on a miss.
      refreshVoices(false, config && config.speech_voice);
    }
    const version = await api.app_version();
    // VERSION already carries the "v:" prefix (legacy $appVersion).
    $("version-badge").textContent = version;
    setStatus("Listo.");
    // S9: the main model selector gets its catalog at startup, after the
    // persisted settings (selected model) are known. Not awaited: the model
    // fetch runs while the editor is already usable.
    // S11: the persisted/default model drives the capability icons before
    // the catalog arrives (static map), and again after it loads.
    selectedModelId = (config && config.selected_model) || selectedModelId;
    applySelectedModelCapabilities(selectedModelId);
    loadStartupModels(config && config.selected_model);
    setInterval(speechTick, 120);
  });

  // ---- AI actions (T5/S9) ---------------------------------------------------
  let speechLanguage = "es";

  // S10: pending AI work shows one large centered overlay over the canvas —
  // "apariencia de trabajo" — never a spinner inside a button.
  function showWorkOverlay(message) {
    $("work-message").textContent = message || "Procesando...";
    $("work-overlay").hidden = false;
  }

  function hideWorkOverlay() {
    $("work-overlay").hidden = true;
  }

  const AI_BUSY_LABELS = {
    consult: "Consultando a la IA",
    summarize: "Creando resumen profesional",
    correct: "Corrigiendo gramática y ortografía",
    translate_en_es: "Traduciendo con IA",
    translate_es_en: "Traduciendo con IA",
  };

  async function runAi(action) {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    const button = document.querySelector(`[data-ai-action="${action}"]`);
    if (button) button.disabled = true;
    showWorkOverlay(`${AI_BUSY_LABELS[action] || "Consultando a la IA"}...`);
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
      // Vista previa now shows the AI response (legacy Copy MD/TXT rule).
      previewHasAiResponse = true;
      await renderPreviewNow();
      setTab("preview");
      setStatus(result.message);
    } finally {
      hideWorkOverlay();
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

  // Exposed for future steps and tests.
  window.txtUI = {
    setTab, setStatus, renderPreviewNow,
    wrapSpeechWords, getSpeechWords, getSpeechTextFrom,
    setSpeechWordIndex, clearSpeechProgress,
    runAi, applyAttachments, getSpeechLanguage: () => speechLanguage,
    copyMain, withBusy,
    applyTheme, applyModelCatalog, saveApiKey, showWorkOverlay, hideWorkOverlay,
    applySelectedModelCapabilities, capabilitiesFor,
    loadStartupModels, applyUpdateStatus,
    applyVoiceCatalog, refreshVoices,
    selectVoiceByFilter, applySpeechState, speedLabel,
  };
})();
