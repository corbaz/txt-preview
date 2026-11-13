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
    setInterval(speechTick, 120);
  });

  // Exposed for future steps (T2 actions) and tests.
  window.txtUI = {
    setTab, setStatus, renderPreviewNow,
    wrapSpeechWords, getSpeechWords, getSpeechTextFrom,
    setSpeechWordIndex, clearSpeechProgress,
  };
})();
