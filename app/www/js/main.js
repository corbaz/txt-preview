// TXT Preview frontend: original-layout tabs, context bar, bottom control
// deck, theme, live markdown preview, embedded browser (T15/S8 parity).
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // ---- Bridge readiness + controlled errors (T25/S18) ---------------------
  // Centralized readiness: a user action while the pywebview bridge is not up
  // yet shows a visible Spanish status instead of silently doing nothing.
  const BRIDGE_NOT_READY = "El puente de la aplicación todavía se está iniciando; esperá unos segundos y probá de nuevo.";

  function bridgeApi() {
    return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
  }

  // requireBridge() returns null (with a visible status) when the bridge is
  // not ready; bridgeApi() stays silent for background work like speechTick.
  function requireBridge() {
    const api = bridgeApi();
    if (!api) setStatus(BRIDGE_NOT_READY);
    return api;
  }

  // Central async call/error wrapper: every bridge promise — awaited or
  // fire-and-forget — goes through safeCall, so a rejection becomes a
  // controlled status message and never an unhandled promise rejection.
  async function safeCall(action, failureMessage) {
    const api = requireBridge();
    if (!api) return null;
    try {
      return await action(api);
    } catch (_) {
      setStatus(failureMessage || "No se pudo completar la operación.");
      return null;
    }
  }

  function setTab(name) {
    document.querySelectorAll(".seg").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.dataset.page === name));
    // txt.ps1: the Contexto IA bar belongs to the Editor tab only.
    $("context-bar").hidden = name !== "editor";
    if (name === "preview") schedulePreview();
    placeBrowser();
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
    if (persist) {
      safeCall((api) => api.set_theme(theme), "No se pudo guardar el tema.");
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

  let previewRenderSequence = 0;

  async function renderPreviewNow() {
    const api = bridgeApi();
    if (!api) return;
    const sequence = ++previewRenderSequence;
    try {
      const html = await api.render_preview(previewContent());
      if (sequence !== previewRenderSequence) return; // a newer render is on its way
      $("preview").innerHTML = html;
      wrapSpeechWords();
      await renderDiagrams(sequence);
    } catch (_) {
      setStatus("No se pudo renderizar la vista previa.");
    }
  }

  // ---- Diagrams: ```mermaid blocks are drawn in Vista previa ---------------
  let diagramCounter = 0;

  function diagramTheme(renderer) {
    const light = document.body.dataset.theme === "light";
    return {
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      // SVG text labels (no foreignObject) so a diagram can become a PNG.
      flowchart: {
        htmlLabels: false, curve: "basis", useMaxWidth: true,
        // "elk": tidy columns with orthogonal arrows; "dagre-wrapper": the
        // classic top-down layout (see drawDiagram for when each is used).
        defaultRenderer: renderer || "elk",
        nodeSpacing: 46, rankSpacing: 58, padding: 16, diagramPadding: 18,
      },
      // Depth and weight: soft shadows, rounded steps and areas, bold labels.
      themeCSS: `
        .node rect, .node polygon, .node path, .node circle, .node ellipse {
          filter: drop-shadow(0 5px 7px rgba(0, 0, 0, ${light ? 0.22 : 0.45}));
        }
        .node rect { rx: 12px; ry: 12px; }
        .node text, .nodeLabel { font-weight: 600; }
        .edgePath .path, .flowchart-link { stroke-width: 2.2px; }
        .edgeLabel text { font-weight: 600; }
        .cluster rect, rect.subgraph {
          fill: ${light ? "#DDE3EE" : "#2C313C"};
          stroke: ${light ? "#9AA5BD" : "#566076"};
          stroke-width: 1.5px; stroke-dasharray: 7 5; rx: 18px; ry: 18px;
        }
        .cluster text, .subgraph text {
          fill: ${light ? "#4F55E3" : "#B3B9FF"}; font-weight: 700; font-size: 16px;
        }
      `,
      themeVariables: {
        fontFamily: 'system-ui, "Segoe UI", sans-serif',
        fontSize: "15px",
        background: light ? "#E8ECF2" : "#23272F",
        primaryColor: light ? "#DDE3F4" : "#353B48",
        primaryTextColor: light ? "#1F2533" : "#E6E9F2",
        primaryBorderColor: light ? "#4F55E3" : "#9AA2FF",
        lineColor: light ? "#4F55E3" : "#9AA2FF",
        textColor: light ? "#1F2533" : "#E6E9F2",
        edgeLabelBackground: light ? "#E8ECF2" : "#23272F",
        // Areas (subgraphs): a soft panel a step away from the surface.
        clusterBkg: light ? "#DDE3EE" : "#2C313C",
        clusterBorder: light ? "#9AA5BD" : "#4A5163",
        titleColor: light ? "#4F55E3" : "#9AA2FF",
        tertiaryColor: light ? "#DDE3EE" : "#2C313C",
      },
    };
  }

  // Where the flow starts inside a drawn diagram, as a fraction of its
  // height (0 = top). Measured off-screen, so a hidden preview works too.
  function diagramStartPosition(svg) {
    const holder = document.createElement("div");
    holder.style.cssText = "position:absolute;left:-99999px;top:0;width:1200px;visibility:hidden";
    holder.innerHTML = svg;
    document.body.appendChild(holder);
    try {
      const drawing = holder.querySelector("svg");
      const start = holder.querySelector("g.node.inicio") || holder.querySelector("g.node");
      if (!drawing || !start) return 0;
      const whole = drawing.getBoundingClientRect();
      const node = start.getBoundingClientRect();
      if (!whole.height) return 0;
      return (node.top + node.height / 2 - whole.top) / whole.height;
    } finally {
      holder.remove();
    }
  }

  // ELK gives the tidiest drawing, but with loops back to the start it can
  // turn the flow upside down. A flowchart must read from the top, so when
  // the start is not near the top the classic layout is used instead.
  async function drawDiagram(source) {
    window.mermaid.initialize(diagramTheme("elk"));
    await window.mermaid.parse(source); // throws before anything is drawn
    let { svg } = await window.mermaid.render(`txt-diagram-${++diagramCounter}`, source);
    if (diagramStartPosition(svg) > 0.4) {
      window.mermaid.initialize(diagramTheme("dagre-wrapper"));
      ({ svg } = await window.mermaid.render(`txt-diagram-${++diagramCounter}`, source));
    }
    return svg;
  }

  async function renderDiagrams(sequence) {
    const blocks = Array.from(document.querySelectorAll("#preview pre > code.language-mermaid"));
    if (!blocks.length || !window.mermaid) return;
    for (const code of blocks) {
      const source = code.textContent;
      try {
        const svg = await drawDiagram(source);
        if (sequence !== previewRenderSequence) return; // a newer render replaced the preview
        const figure = document.createElement("div");
        figure.className = "mermaid-diagram";
        figure.innerHTML = svg;
        code.parentElement.replaceWith(figure);
      } catch (_) {
        // The code stays visible so it can be fixed in the editor.
        setStatus("No se pudo dibujar el diagrama: el código Mermaid tiene un error.", "error");
      }
    }
  }

  // PNG data URLs of the drawn diagrams, in order (for «Copiar Teams»).
  async function diagramPictures() {
    const background = document.body.dataset.theme === "light" ? "#E8ECF2" : "#23272F";
    const pictures = [];
    for (const svg of document.querySelectorAll("#preview .mermaid-diagram svg")) {
      try {
        const box = svg.viewBox.baseVal;
        const width = Math.ceil(box && box.width ? box.width : svg.getBoundingClientRect().width);
        const height = Math.ceil(box && box.height ? box.height : svg.getBoundingClientRect().height);
        if (!width || !height) { pictures.push(""); continue; }
        const copy = svg.cloneNode(true);
        copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
        copy.setAttribute("width", width);
        copy.setAttribute("height", height);
        copy.removeAttribute("style");
        const xml = new XMLSerializer().serializeToString(copy);
        // load/error events, not image.decode(): WebKit (macOS) rejects
        // decode() for SVG sources even when the image draws fine.
        const image = await new Promise((resolve, reject) => {
          const picture = new Image();
          picture.onload = () => resolve(picture);
          picture.onerror = () => reject(new Error("svg"));
          picture.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
        });
        const scale = 2; // sharp on high-density screens
        const padding = 16;
        const canvas = document.createElement("canvas");
        canvas.width = (width + padding * 2) * scale;
        canvas.height = (height + padding * 2) * scale;
        const context = canvas.getContext("2d");
        context.fillStyle = background;
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, padding * scale, padding * scale, width * scale, height * scale);
        pictures.push(canvas.toDataURL("image/png"));
      } catch (_) {
        pictures.push(""); // that diagram is copied as code
      }
    }
    return pictures;
  }

  $("editor").addEventListener("input", () => {
    if (document.querySelector(".page[data-page='preview']").classList.contains("active")) {
      schedulePreview();
    }
  });

  // Legacy $script:aiResult: the last AI answer shown in Vista previa; null
  // means the preview mirrors the editor. Copy, PDF, MP3 and Play act on
  // previewContent() (legacy Get-PreviewContent).
  let aiResult = null;

  function previewContent() {
    return aiResult !== null ? aiResult : $("editor").value;
  }

  function showAiResult(markdown) {
    aiResult = markdown;
    $("preview-result-bar").hidden = false;
  }

  function clearAiResult() {
    aiResult = null;
    $("preview-result-bar").hidden = true;
    if (document.querySelector(".page[data-page='preview']").classList.contains("active")) {
      renderPreviewNow();
    }
  }

  // Hands the preview content to Python before an action that works on it.
  async function syncPreviewContent() {
    const api = bridgeApi();
    if (api) await api.set_preview_content(previewContent());
  }

  // Legacy Set-EditorText: replaces the whole editor as one undoable edit,
  // so Ctrl+Z brings the previous text back.
  function setEditorText(text) {
    const editor = $("editor");
    editor.focus();
    editor.select();
    let done = false;
    try {
      done = text
        ? document.execCommand("insertText", false, text)
        : document.execCommand("delete");
    } catch (_) { done = false; }
    if (!done || editor.value !== text) editor.value = text;
    editor.setSelectionRange(text.length, text.length);
  }

  $("use-result").addEventListener("click", () => {
    const answer = aiResult || "";
    setTab("editor");
    setEditorText(answer);
    clearAiResult();
    setStatus("Respuesta llevada al editor. Ctrl+Z recupera tu consulta.");
  });

  $("dismiss-result").addEventListener("click", () => {
    clearAiResult();
    setStatus("Vista previa muestra otra vez el contenido del Editor.");
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
        // Diagram code is drawn, not read aloud.
        if (parent.closest("code.language-mermaid, .mermaid-diagram")) return NodeFilter.FILTER_REJECT;
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
    if (!span) return;
    if (!speechState || speechState.mode === "Idle") return;
    const index = parseInt(span.dataset.i, 10);
    if (!Number.isNaN(index)) {
      safeCall((api) => api.speech_click(index, getSpeechTextFrom(index)),
        "No se pudo saltar la lectura a la palabra elegida.");
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
    } else if (state.provider === "Replay") {
      // The replay cache belongs to another preview (or has no valid marks):
      // never leave a stale Edge word highlighted.
      clearSpeechProgress();
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
    if (state.voice_update_offered) $("update-voices").hidden = false;
  }

  async function speechTick() {
    const api = bridgeApi();
    if (!api) return;
    try {
      applySpeechState(await api.speech_tick(getSpeechWords()));
    } catch (_) { /* the tick is best effort */ }
  }

  // S13 rule 2 + S15 truth table: when Play switched the voice, the
  // language+gender toggles move to the backend result FIRST, then the
  // selector renders ONLY that combination and shows the voice the backend
  // already persisted (never a redundant set_speech_voice from the UI). A
  // matching language (voice_switched=false) keeps the chosen voice and
  // mutates nothing.
  function applyVoiceSwitch(result) {
    if (!result || !result.ok || !result.voice_switched) return;
    const select = $("voice-select");
    setVoiceToggles(result.voice_gender, result.voice_language);
    renderFilteredVoiceCatalog(result.voice, false);
    if (select && result.voice
      && Array.from(select.options).some((o) => o.value === result.voice)) {
      select.value = result.voice;
    }
    if (result.message) setStatus(result.message);
  }

  $("speech-play").addEventListener("click", async () => {
    if (!requireBridge()) return;
    try {
      // txt.ps1 Play: reads the preview content as plain text, on Vista previa.
      if (!previewContent().trim()) {
        setStatus("No hay contenido en Vista previa para leer.", "warning");
        return;
      }
      setTab("preview");
      await renderPreviewNow();
      const api = window.pywebview.api;
      const speechText = await api.get_preview_speech_text();
      const result = await api.start_speech(speechText, getSpeechWords());
      applyVoiceSwitch(result);
      // T25/S18: start_speech reports its own failures as {ok:false,message}
      // — surface them instead of leaving the click silent.
      if (result && !result.ok) {
        setStatus(result.message || "No se pudo iniciar la lectura.");
      }
    } catch (_) {
      setStatus("No se pudo iniciar la lectura.");
    }
  });

  $("speech-pause").addEventListener("click", () => {
    setTab("preview"); // txt.ps1: the reading controls show Vista previa
    const paused = speechState && speechState.mode === "Paused";
    safeCall((api) => (paused ? api.resume_speech() : api.pause_speech()),
      paused ? "No se pudo continuar la lectura." : "No se pudo pausar la lectura.");
  });

  $("speech-replay").addEventListener("click", () => {
    setTab("preview"); // txt.ps1: the reading controls show Vista previa
    safeCall((api) => api.replay_start(0), "No se pudo repetir la lectura.");
  });

  $("speech-stop").addEventListener("click", async () => {
    const result = await safeCall((api) => api.stop_speech(),
      "No se pudo detener la lectura.");
    if (result !== null) {
      setTab("preview"); // txt.ps1: the reading controls show Vista previa
      setStatus("Lectura detenida.");
    }
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
    if (!(speechState && speechState.provider === "Replay")) return;
    safeCall((api) => api.replay_start(Number($("seek").value) / 10),
      "No se pudo reiniciar la lectura en esa posición.");
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
    safeCall((api) => api.set_speech_speed(Number(speedSlider.value)),
      "No se pudo aplicar la velocidad de lectura.");
  });

  // ---- Editor tools (bottom deck row 2) ------------------------------------
  // T25/S18: the native clipboard lives behind the bridge — the page in
  // WKWebView (macOS) has no browser clipboard API to rely on.
  $("paste-editor").addEventListener("click", async () => {
    const result = await safeCall((api) => api.read_clipboard(),
      "No se pudo leer el portapapeles.");
    if (!result) return;
    if (!result.ok) {
      setStatus(result.error);
      return;
    }
    if (!result.text || !result.text.trim()) {
      setStatus("El portapapeles no contiene texto.");
      return;
    }
    setTab("editor");
    setEditorText(result.text);
    setStatus("Texto pegado desde el portapapeles.");
  });

  // Legacy Copy MD/Copy TXT: use the preview content while Vista previa
  // shows an AI response, otherwise the editor text. fetchText picks the
  // preview source (api.get_preview_text / api.get_preview_plain_text).
  async function copyMain(plain, fetchText) {
    let text = previewContent();
    if (plain && text && text.trim()) {
      await syncPreviewContent();
      const fetched = await safeCall((api) => fetchText(api),
        "No se pudo leer la vista previa.");
      text = fetched || "";
    }
    if (!text || !text.trim()) {
      setStatus("No hay contenido para copiar.");
      return;
    }
    const result = await safeCall((api) => api.write_clipboard(text),
      "No se pudo copiar al portapapeles.");
    if (!result) return;
    if (!result.ok) {
      setStatus(result.error);
      return;
    }
    setStatus(plain
      ? "Texto sin formato copiado al portapapeles."
      : "Markdown copiado al portapapeles.");
  }

  $("copy-md").addEventListener("click", async () => {
    await copyMain(false, (api) => api.get_preview_text());
  });
  $("copy-txt").addEventListener("click", async () => {
    await copyMain(true, (api) => api.get_preview_plain_text());
  });

  // «Copiar Teams»: what Vista previa shows, as rich text for a Teams chat.
  $("copy-teams").addEventListener("click", async () => {
    if (!previewContent().trim()) {
      setStatus("No hay contenido para copiar.", "warning");
      return;
    }
    await renderPreviewNow(); // diagrams must be drawn to be copied as pictures
    const diagrams = await diagramPictures();
    const result = await safeCall((api) => api.copy_for_teams(diagrams),
      "No se pudo copiar al portapapeles.");
    if (!result) return;
    if (result.ok && diagrams.some((picture) => !picture)) {
      // Never silently paste code where a drawing was expected.
      setStatus("Copiado para Teams, pero un diagrama no se pudo convertir a imagen y va como código.",
        "warning");
      return;
    }
    setStatus(result.ok ? result.message : result.error, result.ok ? "info" : "error");
  });

  $("clear-chat").addEventListener("click", () => {
    $("editor").value = "";
    $("preview").innerHTML = "";
    clearAiResult();
    safeCall((api) => api.clear_attachments(),
      "No se pudieron quitar los adjuntos.");
    renderAttachmentSummary({ summary: "Sin archivos adjuntos para la próxima solicitud", items: [] });
    $("clear-attachments").hidden = true;
    setTab("editor");
    setStatus("Editor y adjuntos limpiados.");
  });

  // ---- Micrófono (legacy Win+H dictation) -----------------------------------
  $("mic-button").addEventListener("click", async () => {
    if (!requireBridge()) return;
    try {
      const result = await window.pywebview.api.start_dictation();
      if (result && result.ok) {
        // txt.ps1: the button reads "Mic <Esc>" and the caret goes to the
        // end of the editor, where the dictated text lands.
        $("mic-button").textContent = "Mic <Esc>";
        setTab("editor");
        const editor = $("editor");
        editor.focus();
        editor.setSelectionRange(editor.value.length, editor.value.length);
      }
      if (result && result.message) setStatus(result.message);
    } catch (_) {
      setStatus("No se pudo activar el dictado.");
    }
  });

  // ---- Cerrar (legacy $form.Close) -------------------------------------------
  $("close-app").addEventListener("click", () => {
    safeCall((api) => api.close_app(), "No se pudo cerrar la aplicación.");
  });

  // ---- Preview exports (bottom deck row 2) ----------------------------------
  // Legacy Export-PreviewPdf / Export-SpeechMp3: the Api works on the session
  // preview text (what Vista previa shows), not on the editor.
  async function withBusy(button, busyMessage, action) {
    if (!button) return;
    if (!requireBridge()) return;
    button.disabled = true;
    setStatus(busyMessage);
    try {
      const result = await action(bridgeApi());
      if (result && result.message) setStatus(result.message);
    } catch (_) {
      // T25/S18: a rejected export shows a controlled error, never an
      // unhandled promise rejection.
      setStatus("No se pudo generar el archivo.");
    } finally {
      button.disabled = false;
    }
  }

  $("export-pdf").addEventListener("click", () => {
    withBusy($("export-pdf"), "Generando PDF...",
      async (api) => { await syncPreviewContent(); return api.export_pdf(); });
  });

  $("export-mp3").addEventListener("click", () => {
    withBusy($("export-mp3"), "Generando MP3...",
      async (api) => { await syncPreviewContent(); return api.export_mp3(); });
  });

  // ---- Navegador (txt.ps1 Open-BrowserUrl) --------------------------------
  // The page itself is a native web view placed by Python over #browser-host;
  // this code only drives it and keeps its bounds in sync with the layout.
  let browserOpened = false;
  let browserPollTimer = null;

  function browserRect() {
    const box = $("browser-host").getBoundingClientRect();
    return { x: box.left, y: box.top, width: box.width, height: box.height,
             inner_width: window.innerWidth };
  }

  function browserTabActive() {
    const page = document.querySelector('.page[data-page="browser"]');
    return page && page.classList.contains("active");
  }

  // The native view covers the HTML below it, so it is only shown on its tab
  // and never over the work overlay.
  function placeBrowser() {
    const api = bridgeApi();
    if (!api || !browserOpened) return;
    const overlay = $("work-overlay");
    const visible = browserTabActive() && !(overlay && !overlay.hidden)
      && $("attachment-modal").hidden;
    api.browser_place(browserRect(), visible).catch(() => {});
    if (visible && !browserPollTimer) {
      browserPollTimer = setInterval(pollBrowser, 400);
    } else if (!visible && browserPollTimer) {
      clearInterval(browserPollTimer);
      browserPollTimer = null;
    }
  }

  async function pollBrowser() {
    const api = bridgeApi();
    if (!api) return;
    try {
      const state = await api.browser_state();
      $("browser-back").disabled = !state.can_back;
      $("browser-forward").disabled = !state.can_forward;
      if (state.url && document.activeElement !== $("browser-address")) {
        $("browser-address").value = state.url;
      }
      if (state.error) setStatus(state.error);
    } catch (_) { /* the next tick retries */ }
  }

  async function openBrowserUrl(address) {
    const result = await safeCall((api) => api.browser_open(address),
      "No se pudo abrir el navegador integrado.");
    if (!result) return;
    setStatus(result.message);
    if (result.unavailable) {
      // Legacy fallback: offer the default browser when the embedded one fails.
      if (window.confirm("El navegador integrado no está disponible. ¿Querés abrir "
          + result.url + " en tu navegador predeterminado?")) {
        await safeCall((api) => api.browser_open_external(result.url),
          "No se pudo abrir el navegador predeterminado.");
      }
      return;
    }
    if (!result.ok) return;
    $("browser-address").value = result.url;
    $("browser-empty").hidden = true;
    browserOpened = true;
    setTab("browser");
  }

  $("browser-go").addEventListener("click", () => openBrowserUrl($("browser-address").value));

  $("browser-address").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      openBrowserUrl($("browser-address").value);
    }
  });

  $("browser-back").addEventListener("click", () => {
    safeCall((api) => api.browser_back(), "No se pudo volver atrás.");
  });

  $("browser-forward").addEventListener("click", () => {
    safeCall((api) => api.browser_forward(), "No se pudo avanzar.");
  });

  $("browser-external").addEventListener("click", async () => {
    const result = await safeCall((api) => api.browser_open_external($("browser-address").value),
      "No se pudo abrir el navegador predeterminado.");
    if (result) setStatus(result.message);
  });

  window.addEventListener("resize", placeBrowser);

  // Links clicked in Vista previa leave the preview and open in the Navegador tab.
  $("preview").addEventListener("click", (e) => {
    const link = e.target.closest("a[href]");
    if (!link || !/^https?:\/\//i.test(link.href)) return;
    e.preventDefault();
    openBrowserUrl(link.href);
  });

  const ERROR_TEXT = /^(No se pudo|No se pudieron|No se encontró|Error|Falta)/;
  const WARNING_TEXT = /^(No hay|Ingresá|Escribí|El portapapeles no contiene|La lectura (ya|no)|Versión .* disponible)/;

  function setStatus(message, level) {
    const status = $("status-message");
    const text = message || "";
    const resolved = level
      || (ERROR_TEXT.test(text) ? "error" : WARNING_TEXT.test(text) ? "warning" : "info");
    status.textContent = text;
    status.classList.toggle("error", resolved === "error");
    status.classList.toggle("warning", resolved === "warning");
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
      // txt.ps1 Update-CapabilityBadges: only the capabilities the model has.
      span.hidden = !supported;
      span.title = CAP_TITLES[key];
    });
    // txt.ps1: the web checkbox and the attach button are hidden when they
    // do not apply to the selected model.
    $("web-search-label").hidden = !caps.web;
    $("attach-files").hidden = !(caps.text_files || caps.vision);
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
    // Legacy Show-GroqModels: one selector for every provider, labelled
    // "Groq · <id>" / "<Bridge> · <name>"; Groq models that cannot chat are
    // listed in Configuración only.
    for (const model of result.models || []) {
      const isBridge = !!model.bridge;
      if (!isBridge && !(model.capabilities && model.capabilities.chat)) continue;
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = `${isBridge ? model.provider : "Groq"} · ${model.name || model.id}`;
      select.appendChild(option);
    }
    const hasPrevious = Array.from(select.options).some((o) => o.value === previous);
    if (hasPrevious) {
      select.value = previous;
    } else if (select.options.length) {
      select.selectedIndex = 0; // legacy: fall back to the first listed model
    }
    select.disabled = select.options.length === 0;
    renderModelsList(result.models || []);
    applyBridgeStatus(result.bridge_status || {});
    // The catalog may have resolved the capabilities of the shown model.
    applySelectedModelCapabilities(select.value);
    showSelectedModelSummary();
  }

  // Legacy Add-ModelListRow: one column per capability.
  function renderModelsList(models) {
    const body = document.querySelector("#models-list tbody");
    body.innerHTML = "";
    const mark = (value) => (value ? "\u2713" : "\u2014");
    for (const model of models) {
      const caps = model.capabilities || FALLBACK_CAPABILITIES;
      const row = document.createElement("tr");
      row.dataset.model = model.id;
      const cells = [model.name || model.id, model.owned_by || "", model.context || "-",
        mark(caps.chat), mark(caps.vision), mark(caps.web),
        mark(caps.text_files || caps.vision), caps.summary || ""];
      for (const text of cells) {
        const cell = document.createElement("td");
        cell.textContent = text;
        row.appendChild(cell);
      }
      body.appendChild(row);
    }
    markSelectedModelRow();
  }

  // Legacy modelsList.Add_DoubleClick.
  document.querySelector("#models-list tbody").addEventListener("dblclick", (e) => {
    const row = e.target.closest("tr");
    if (!row) return;
    const modelId = row.dataset.model;
    const select = $("model-select");
    if (!Array.from(select.options).some((option) => option.value === modelId)) {
      setSettingsStatus(`${modelId} no es un modelo de chat para las acciones del editor.`,
        "warning");
      return;
    }
    select.value = modelId;
    select.dispatchEvent(new Event("change"));
  });

  function markSelectedModelRow() {
    const current = $("model-select").value;
    document.querySelectorAll("#models-list tbody tr").forEach((row) => {
      row.classList.toggle("selected", row.dataset.model === current);
    });
  }

  const BRIDGE_PORTS = { claude: 4098, codex: 4094, gemini: 4092 };
  const BRIDGE_NAMES = { claude: "Claude", codex: "Codex", gemini: "Gemini" };

  // Legacy Update-BridgeModels status labels (warning unless connected/off).
  function applyBridgeStatus(bridgeStatus) {
    for (const key of Object.keys(BRIDGE_PORTS)) {
      const label = $(`bridge-status-${key}`);
      const status = bridgeStatus[key] || "Sin comprobar";
      label.textContent = status;
      label.classList.toggle("warning",
        !(status.startsWith("Conectado") || status === "Apagado" || status === "Sin comprobar"));
      label.title = `${BRIDGE_NAMES[key]} · 127.0.0.1:${BRIDGE_PORTS[key]} · ${status}`;
    }
  }

  function setSettingsStatus(message, level) {
    const status = $("settings-status");
    status.textContent = message;
    status.classList.toggle("error", level === "error");
    status.classList.toggle("warning", level === "warning");
  }

  // Legacy Update-ModelCapabilityControls: "<model> · <capabilities>".
  function showSelectedModelSummary() {
    const modelId = $("model-select").value;
    if (!modelId) return;
    const caps = capabilitiesFor(modelId);
    setSettingsStatus(caps.summary ? `${modelId} · ${caps.summary}` : modelId);
    markSelectedModelRow();
  }

  function bridgePasswordsFromBoxes() {
    const passwords = {};
    document.querySelectorAll(".bridge-password").forEach((box) => {
      passwords[box.dataset.bridge] = box.value.trim();
    });
    return passwords;
  }

  // S9: startup model load — the persisted model is preselected and the
  // catalog arrives without visiting Configuración or clicking Actualizar
  // modelos. update_models already caches and returns fallback models on a
  // Groq error.
  async function loadStartupModels(selectedModel) {
    const api = requireBridge();
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
      // T25/S18: keep the default option and show a controlled error; the
      // selector only becomes usable when there is more than one known model.
      setStatus("No se pudo cargar el catálogo de modelos.");
    } finally {
      if (select.options.length > 1) select.disabled = false;
    }
  }

  let savedBridgePasswords = {};

  function applySettingsResult(result) {
    if (result.models) {
      applyModelCatalog(result);
      selectedModelId = $("model-select").value;
    }
    if (result.message) setSettingsStatus(result.message, result.level);
    savedBridgePasswords = bridgePasswordsFromBoxes();
  }

  async function saveSettingsForm() {
    const button = $("save-api-key");
    button.disabled = true;
    try {
      const result = await safeCall(
        (api) => api.save_settings_form($("api-key").value, bridgePasswordsFromBoxes()),
        "No se pudo guardar la configuración.");
      if (result) applySettingsResult(result);
    } finally {
      button.disabled = false;
    }
  }

  $("save-api-key").addEventListener("click", saveSettingsForm);
  $("api-key").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      saveSettingsForm();
    }
  });

  $("update-models").addEventListener("click", async () => {
    const button = $("update-models");
    button.disabled = true;
    setSettingsStatus("Consultando modelos activos de Groq...");
    try {
      const result = await safeCall(
        (api) => api.refresh_models($("api-key").value, bridgePasswordsFromBoxes()),
        "No se pudo actualizar el catálogo de modelos.");
      if (result) applySettingsResult(result);
    } finally {
      button.disabled = false;
    }
  });

  // Leaving a bridge box after changing its password checks the bridges again.
  document.querySelectorAll(".bridge-password").forEach((box) => {
    box.addEventListener("blur", async () => {
      if ((savedBridgePasswords[box.dataset.bridge] || "") === box.value.trim()) return;
      const result = await safeCall((api) => api.recheck_bridges(bridgePasswordsFromBoxes()),
        "No se pudieron comprobar los bridges.");
      if (result) applySettingsResult(result);
    });
  });

  // Fills the password boxes, the version label and the edge-tts label.
  async function loadSettingsPage() {
    const api = bridgeApi();
    if (!api) return;
    try {
      const secrets = await api.get_settings_secrets();
      $("api-key").value = secrets.api_key || "";
      for (const [key, password] of Object.entries(secrets.bridge_passwords || {})) {
        const box = $(`bridge-password-${key}`);
        if (box) box.value = password || "";
      }
      savedBridgePasswords = bridgePasswordsFromBoxes();
      $("app-version-label").textContent = `Aplicación ${await api.app_version()}`;
      if ((await api.platform()) === "darwin") {
        $("settings-hint").textContent =
          "La API key y las contraseñas de los bridges se guardan en el llavero de tu usuario de macOS.";
      }
      $("edge-tts-version").textContent = await api.edge_tts_version_label();
    } catch (_) {
      setSettingsStatus("No se pudo cargar la configuración.", "error");
    }
  }

  $("model-select").addEventListener("change", async () => {
    const select = $("model-select");
    const result = await safeCall((api) => api.set_selected_model(select.value),
      "No se pudo cambiar el modelo.");
    if (!result) return;
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
    showSelectedModelSummary();
    try {
      await refreshAttachmentSummary(); // a model without vision drops the images
    } catch (_) { /* the summary is best effort */ }
  });

  // ---- Voz Edge (T4/S6, filters S15/T22) -------------------------------------
  // The Hombre/Mujer + Español/Inglés toggles own the active language+gender
  // combination. The selector renders ONLY the voices of that combination —
  // never both languages at once — and its selection is the legacy default
  // for the combination, delivered by list_voices as `defaults` so the
  // priority table lives in one place (voices.py), never duplicated in JS.
  let voiceCatalog = [];
  let voiceDefaults = {};

  function voiceRecordOf(name) {
    return voiceCatalog.find((voice) => voice.name === name) || null;
  }

  function voiceFilterActive(toggleId) {
    return $(toggleId).getAttribute("aria-pressed") === "true";
  }

  // The JS-owned filter state: the four aria-pressed toggles.
  function selectedVoiceFilter() {
    const gender = voiceFilterActive("gender-male") ? "Male" : "Female";
    const culture = voiceFilterActive("lang-es") ? "es" : "en";
    return { gender, culture };
  }

  function setVoiceToggles(gender, culture) {
    const genderId = gender === "Male" ? "gender-male" : "gender-female";
    for (const id of VOICE_TOGGLE_GROUPS[genderId]) {
      $(id).setAttribute("aria-pressed", String(id === genderId));
    }
    const languageId = culture === "en" ? "lang-en" : "lang-es";
    for (const id of VOICE_TOGGLE_GROUPS[languageId]) {
      $(id).setAttribute("aria-pressed", String(id === languageId));
    }
  }

  // S15: render only the active combination. keepPreferred keeps a voice
  // that already matches the filter (chooseDefault=false); otherwise the
  // combination's legacy default is chosen (backend defaults map, fallback
  // first matching voice). Zero matching voices disables the selector.
  function renderFilteredVoiceCatalog(preferredVoice, chooseDefault) {
    const select = $("voice-select");
    if (!select) return null;
    const { gender, culture } = selectedVoiceFilter();
    const filtered = voiceCatalog.filter((voice) =>
      voice.gender === gender
      && String(voice.culture || "").slice(0, 2) === culture);
    select.innerHTML = "";
    for (const voice of filtered) {
      const option = document.createElement("option");
      option.value = voice.name;
      option.textContent = voice.display_name;
      select.appendChild(option);
    }
    const keepPreferred = preferredVoice && !chooseDefault
      && filtered.some((voice) => voice.name === preferredVoice);
    const target = keepPreferred
      ? preferredVoice
      : (voiceDefaults[culture + "|" + gender]
         || (filtered.length ? filtered[0].name : null));
    if (!target) {
      select.disabled = true;
      setStatus("No hay voces Edge para el idioma y género activos.");
      return null;
    }
    select.value = target;
    select.disabled = false;
    return target;
  }

  // S15 initial load: derive the active toggles from the persisted voice
  // when it exists in the catalog (so the selector renders only that
  // combination and keeps the voice); otherwise keep the toggle state and
  // choose that combination's default.
  function applyVoiceCatalog(selectedVoice) {
    const record = selectedVoice ? voiceRecordOf(selectedVoice) : null;
    if (record) {
      setVoiceToggles(record.gender, String(record.culture || "").slice(0, 2));
    }
    const preferred = record ? selectedVoice : ($("voice-select").value || null);
    renderFilteredVoiceCatalog(preferred, !preferred);
  }

  async function refreshVoices(force, selectedVoice) {
    if (!requireBridge()) return;
    const api = bridgeApi();
    const button = $("update-voices");
    if (button) button.disabled = true;
    try {
      const result = await api.list_voices(!!force);
      if (!result.ok) {
        setStatus(result.error || "No se pudo cargar el catálogo de voces Edge.");
        return;
      }
      voiceCatalog = result.voices || [];
      voiceDefaults = result.defaults || {};
      applyVoiceCatalog(selectedVoice);
      if (result.warning) setStatus(result.warning);
    } catch (_) {
      // T25/S18: the startup voice load must never leave an unhandled
      // rejection or a silent failure.
      setStatus("No se pudo cargar el catálogo de voces Edge.");
    } finally {
      if (button) button.disabled = false;
    }
  }

  // Legacy Update-EdgeTts: the button only appears after Edge rejects an
  // outdated edge-tts (HTTP 403) and upgrades the package.
  $("update-voices").addEventListener("click", async () => {
    const button = $("update-voices");
    button.disabled = true;
    showWorkOverlay("Actualizando las voces Edge (edge-tts)...");
    try {
      const result = await safeCall((api) => api.update_edge_tts(),
        "No se pudieron actualizar las voces Edge.");
      if (!result) return;
      $("edge-tts-version").textContent = result.label;
      setStatus(result.message);
      if (result.ok) {
        button.hidden = true;
        refreshVoices(true);
      }
    } finally {
      hideWorkOverlay();
      button.disabled = false;
    }
  });

  // Radio-like groups (legacy New-ToggleGroup panels): one active per group.
  const VOICE_TOGGLE_GROUPS = {
    "gender-male": ["gender-male", "gender-female"],
    "gender-female": ["gender-male", "gender-female"],
    "lang-es": ["lang-es", "lang-en"],
    "lang-en": ["lang-es", "lang-en"],
  };

  // S15/T22: a toggle click re-renders the selector for the new active
  // combination and selects + persists ITS default voice (never the
  // previous selection). set_speech_voice runs exactly once per click.
  async function selectVoiceByFilter(silent) {
    if (!voiceCatalog.length) return null;
    const chosen = renderFilteredVoiceCatalog(null, true);
    if (!chosen) return null;
    const result = await safeCall((api) => api.set_speech_voice(chosen),
      "No se pudo cambiar la voz Edge.");
    if (result && result.ok && !silent) setStatus(result.message || `Voz Edge: ${result.voice}`);
    return chosen;
  }

  function activateVoiceToggle(toggleId, silent) {
    for (const id of VOICE_TOGGLE_GROUPS[toggleId]) {
      $(id).setAttribute("aria-pressed", String(id === toggleId));
    }
    return selectVoiceByFilter(silent);
  }

  // Legacy Select-VoiceLanguage: after a translation the Español/Inglés
  // toggle follows the language of the result, keeping the chosen gender,
  // and that language's default voice is selected.
  function selectVoiceLanguage(language) {
    return activateVoiceToggle(language === "en" ? "lang-en" : "lang-es", true);
  }

  $("gender-male").addEventListener("click", () => activateVoiceToggle("gender-male"));
  $("gender-female").addEventListener("click", () => activateVoiceToggle("gender-female"));
  $("lang-es").addEventListener("click", () => activateVoiceToggle("lang-es"));
  $("lang-en").addEventListener("click", () => activateVoiceToggle("lang-en"));

  $("voice-select").addEventListener("change", async () => {
    const result = await safeCall((api) => api.set_speech_voice($("voice-select").value),
      "No se pudo cambiar la voz Edge.");
    if (result && result.ok) setStatus(result.message || `Voz Edge: ${result.voice}`);
  });

  // ---- In-app update (T11/S4) ---------------------------------------------
  // Legacy Update-AppUpdateControls / Install-AppUpdate messages: the three
  // task-worded states plus the legacy refusal details from txt.ps1.
  // Legacy Update-AppUpdateControls / Invoke-AppUpdateInstall texts.
  let availableUpdateVersion = null;

  function updateStatusMessage(status, installing) {
    if (status.updated) return "Actualización instalada. Cerrá y abrí la aplicación.";
    switch (status.state) {
      case "up_to_date": return `La aplicación está actualizada (${status.local_version}).`;
      case "available": return `Nueva versión ${status.remote_version} disponible.`;
      default: {
        const detail = status.detail || "error desconocido.";
        return `${installing ? "No se pudo actualizar" : "No se pudo comprobar"}: ${detail}`;
      }
    }
  }

  function applyUpdateStatus(status, installing) {
    if (!status) return;
    const failed = !status.updated
      && status.state !== "up_to_date" && status.state !== "available";
    const label = $("update-status");
    label.textContent = updateStatusMessage(status, installing);
    label.classList.toggle("error", failed);
    availableUpdateVersion = status.state === "available" ? status.remote_version : null;
    $("apply-update").hidden = status.state !== "available";
    if (status.updated) {
      const version = status.local_version || status.remote_version;
      $("version-badge").textContent = version;
      $("app-version-label").textContent = `Aplicación ${version}`;
      setStatus(`Actualización ${version} instalada.`);
    } else if (failed && installing) {
      setStatus(label.textContent, "error");
    }
  }

  async function checkForUpdates() {
    const button = $("check-update");
    button.disabled = true;
    $("apply-update").hidden = true;
    $("update-status").classList.remove("error");
    $("update-status").textContent = "Buscando una versión nueva en origin/main...";
    try {
      applyUpdateStatus(await bridgeApi().check_for_updates());
    } catch (_) {
      $("update-status").textContent = "No se pudo comprobar: error desconocido.";
    } finally {
      button.disabled = false;
    }
  }

  // Legacy Invoke-AppUpdateInstall: true when the new version was installed.
  async function installUpdate() {
    $("check-update").disabled = true;
    $("apply-update").disabled = true;
    $("update-status").textContent = "Aplicando la actualización...";
    setStatus("Aplicando la actualización...");
    try {
      const status = await bridgeApi().apply_update();
      applyUpdateStatus(status, true);
      return !!status.updated;
    } catch (_) {
      $("update-status").textContent = "No se pudo actualizar: error desconocido.";
      return false;
    } finally {
      $("check-update").disabled = false;
      $("apply-update").disabled = false;
    }
  }

  $("check-update").addEventListener("click", () => {
    if (requireBridge()) checkForUpdates();
  });

  $("apply-update").addEventListener("click", async () => {
    if (!requireBridge()) return;
    if (!window.confirm(`Se actualizará TXT Preview a ${availableUpdateVersion} desde origin/main. `
        + "La aplicación deberá reiniciarse.")) return;
    if (await installUpdate()) {
      window.alert(`TXT Preview se actualizó a ${$("version-badge").textContent}. `
        + "Cerrá y volvé a abrir la aplicación para usar el código nuevo.");
    }
  });

  // Legacy Invoke-StartupUpdateCheck: offers the new version once at startup.
  async function offerStartupUpdate(status) {
    applyUpdateStatus(status);
    if (!availableUpdateVersion) return;
    const accepted = window.confirm(
      `Hay una versión nueva de TXT Preview: ${availableUpdateVersion} (tenés ${status.local_version}).`
      + " ¿Querés actualizar ahora? La aplicación se reiniciará sola.");
    if (!accepted) {
      setStatus(`Versión ${availableUpdateVersion} disponible. Podés actualizar desde Configuración.`,
        "warning");
      return;
    }
    if (await installUpdate()) {
      await safeCall((api) => api.restart_app(), "No se pudo reiniciar la aplicación.");
    }
  }

  window.addEventListener("pywebviewready", async () => {
    let theme = "dark";
    // txt.ps1 always starts on Tema: Oscuro; the theme is not remembered.
    applyTheme(theme);
    const api = bridgeApi();
    let config = null;
    if (api) {
      // Persisted settings win over localStorage (legacy Import-AppSettings).
      try {
        config = await api.get_settings();
      } catch (_) {
        // T25/S18: a rejected settings load shows a controlled error and
        // never kills the rest of startup.
        setStatus("No se pudieron cargar las preferencias guardadas.");
      }
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
    // T25/S18: each startup await is caught on its own, so one rejected
    // call (version) never kills independent initialization (status,
    // capabilities, models, speech interval).
    try {
      const version = await api.app_version();
      // VERSION already carries the "v:" prefix (legacy $appVersion).
      $("version-badge").textContent = version;
    } catch (_) {
      setStatus("No se pudo obtener la versión de la aplicación.");
    }
    setStatus("Listo.");
    loadSettingsPage(); // not awaited: Configuración fills in the background
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
    placeBrowser();
  }

  function hideWorkOverlay() {
    $("work-overlay").hidden = true;
    placeBrowser();
  }

  const AI_BUSY_LABELS = {
    consult: "Consultando a la IA",
    summarize: "Creando resumen profesional",
    flowchart: "Diseñando el diagrama de flujo",
    correct: "Corrigiendo gramática y ortografía",
    translate_en_es: "Traduciendo con IA",
    translate_es_en: "Traduciendo con IA",
  };

  async function runAi(action) {
    const button = document.querySelector(`[data-ai-action="${action}"]`);
    if (button) button.disabled = true;
    showWorkOverlay(`${AI_BUSY_LABELS[action] || "Consultando a la IA"}...`);
    try {
      const api = requireBridge();
      if (!api) return;
      // Legacy Start-Busy text: "<acción> · <Proveedor> · <modelo>...".
      const option = $("model-select").selectedOptions[0];
      const display = option ? option.textContent : await api.get_selected_model();
      const busy = `${AI_BUSY_LABELS[action] || "Consultando a la IA"} · ${display}...`;
      showWorkOverlay(busy);
      setStatus(busy);
      // txt.ps1: web search only when the checkbox is ticked.
      const useWeb = $("web-search").checked;
      const result = await api.ask_ai(action, useWeb, $("editor").value);
      if (!result.ok) {
        setStatus(result.error, result.level);
        return;
      }
      if (result.editor_action === "replace") {
        // Corregir / Resumir / Traducir: the result replaces the editor
        // (Ctrl+Z restores it) and the preview mirrors the editor again.
        clearAiResult();
        setEditorText(result.text);
      } else {
        showAiResult(result.text); // Consultar: the question stays in the editor
      }
      if (result.clipboard && result.text) {
        // Legacy Corregir copies the result; the native clipboard bridge
        // (T25/S18) replaces the browser API, unavailable on WKWebView.
        await safeCall((api) => api.write_clipboard(result.text),
          "No se pudo copiar al portapapeles.");
      }
      if (result.speech_language) speechLanguage = result.speech_language;
      if (action === "translate_es_en" || action === "translate_en_es") {
        await selectVoiceLanguage(action === "translate_es_en" ? "en" : "es");
      }
      await renderPreviewNow();
      setTab("preview");
      setStatus(result.message);
    } catch (_) {
      // T25/S18: a rejected AI request shows a controlled error and never
      // leaves an unhandled promise rejection behind.
      setStatus("Error al conectar con la API.", "error");
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
  // The summary keeps the legacy text; every file name in it is a link that
  // opens a preview of that attachment.
  function renderAttachmentSummary(data) {
    const summary = $("attachment-summary");
    const items = data.items || [];
    summary.textContent = "";
    if (!items.length) {
      summary.textContent = data.summary;
    } else {
      summary.appendChild(document.createTextNode(
        data.summary.slice(0, data.summary.indexOf(": ") + 2)));
      items.forEach((item, index) => {
        if (index) summary.appendChild(document.createTextNode(", "));
        const link = document.createElement("button");
        link.type = "button";
        link.className = "attachment-link";
        link.textContent = item.name;
        link.title = "Ver el archivo adjunto";
        link.addEventListener("click", () => showAttachmentPreview(index));
        summary.appendChild(link);
      });
    }
    $("clear-attachments").hidden = !items.length;
  }

  async function refreshAttachmentSummary() {
    const data = await safeCall((api) => api.get_attachments(),
      "No se pudieron leer los adjuntos.");
    if (data) renderAttachmentSummary(data);
  }

  async function showAttachmentPreview(index) {
    const preview = await safeCall((api) => api.get_attachment_preview(index),
      "No se pudo mostrar el adjunto.");
    if (!preview) return;
    if (!preview.ok) {
      setStatus(preview.message, "error");
      return;
    }
    const body = $("attachment-modal-body");
    body.textContent = "";
    if (preview.kind === "image") {
      const image = document.createElement("img");
      image.src = preview.data_url;
      image.alt = preview.name;
      body.appendChild(image);
    } else {
      const text = document.createElement("pre");
      text.textContent = preview.text;
      body.appendChild(text);
    }
    $("attachment-modal-title").textContent = `Adjunto: ${preview.name}`;
    $("attachment-modal").hidden = false;
    placeBrowser(); // the native browser view must not cover the modal
    $("attachment-modal-close").focus();
  }

  function closeAttachmentPreview() {
    $("attachment-modal").hidden = true;
    $("attachment-modal-body").textContent = "";
    placeBrowser();
  }

  $("attachment-modal-close").addEventListener("click", closeAttachmentPreview);
  $("attachment-modal").addEventListener("click", (e) => {
    if (e.target === $("attachment-modal")) closeAttachmentPreview();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("attachment-modal").hidden) closeAttachmentPreview();
  });

  function applyAttachments(result) {
    if (!result) return;
    refreshAttachmentSummary();
    if (result.errors && result.errors.length) {
      setStatus(result.errors[0]);
    } else if (result.added && result.added.length) {
      setStatus("Los adjuntos visibles sobre el editor se enviarán en la próxima acción de IA.");
    }
  }

  // Use exactly one native dialog. WebView2 file inputs do not expose full
  // filesystem paths, which previously opened a second fallback dialog.
  $("attach-files").addEventListener("click", async () => {
    const result = await safeCall((api) => api.open_attachment_dialog(),
      "No se pudo abrir el diálogo de adjuntos.");
    applyAttachments(result);
  });

  $("attach-input").addEventListener("change", async () => {
    const files = Array.from($("attach-input").files || []);
    $("attach-input").value = "";
    const paths = files.map((file) => file.pywebviewFullPath).filter(Boolean);
    if (paths.length) {
      applyAttachments(await safeCall((api) => api.add_attachments(paths),
        "No se pudieron adjuntar los archivos."));
    } else {
      // WebView flavors that hide full paths: resolve through the native dialog.
      applyAttachments(await safeCall((api) => api.open_attachment_dialog(),
        "No se pudo abrir el diálogo de adjuntos."));
    }
  });

  $("clear-attachments").addEventListener("click", async () => {
    const result = await safeCall((api) => api.clear_attachments(),
      "No se pudieron quitar los adjuntos.");
    if (!result) return;
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
    applyTheme, applyModelCatalog, saveSettingsForm, showWorkOverlay, hideWorkOverlay,
    applySelectedModelCapabilities, capabilitiesFor,
    loadStartupModels, applyUpdateStatus, offerStartupUpdate,
    renderDiagrams, diagramPictures,
    applyVoiceCatalog, refreshVoices, renderFilteredVoiceCatalog,
    selectVoiceByFilter, applySpeechState, applyVoiceSwitch, speedLabel,
  };
})();
