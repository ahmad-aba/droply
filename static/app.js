(() => {
  const $ = (selector) => document.querySelector(selector);
  const elements = {
    form: $("#link-form"),
    url: $("#media-url"),
    paste: $("#paste-button"),
    inspect: $("#inspect-button"),
    error: $("#form-error"),
    mediaCard: $("#media-card"),
    thumbnail: $("#thumbnail"),
    fallback: $("#thumb-fallback"),
    duration: $("#duration-chip"),
    platform: $("#media-platform"),
    title: $("#media-title"),
    creator: $("#media-creator"),
    reset: $("#reset-button"),
    options: $("#download-options"),
    formatTabs: [...document.querySelectorAll(".format-tab")],
    qualityRow: $("#quality-row"),
    qualityPicker: $("#quality-picker"),
    download: $("#download-button"),
    downloadLabel: $("#download-label"),
    progressCard: $("#progress-card"),
    progressIcon: $("#progress-icon"),
    progressTitle: $("#progress-title"),
    progressPercent: $("#progress-percent"),
    progressBar: $("#progress-bar"),
    progressDetail: $("#progress-detail"),
    save: $("#save-button"),
    toast: $("#toast"),
  };

  const state = { media: null, type: "video", quality: "best", poller: null, toastTimer: null };
  const checkIcon = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m5 12 4 4L19 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const errorIcon = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 8v4m0 4h.01M10.3 4.55 3.8 16a2 2 0 0 0 1.74 3h12.92a2 2 0 0 0 1.74-3L13.7 4.55a2 2 0 0 0-3.4 0Z" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';

  function toast(message) {
    clearTimeout(state.toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.add("show");
    state.toastTimer = setTimeout(() => elements.toast.classList.remove("show"), 2600);
  }

  function showError(message = "") {
    elements.error.textContent = message;
  }

  function formatDuration(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) return "";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
  }

  async function request(endpoint, body) {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let data;
    try { data = await response.json(); } catch { throw new Error("The server returned an unexpected response."); }
    if (!response.ok || !data.ok) throw new Error(data.error || "Something went wrong. Please try again.");
    return data;
  }

  function busy(button, active, label) {
    button.disabled = active;
    if (button === elements.inspect) button.querySelector("span").textContent = active ? "Checking link…" : "Fetch media";
    if (button === elements.download) elements.downloadLabel.textContent = active ? "Starting download…" : label;
  }

  function showMedia(media) {
    state.media = media;
    state.type = media.direct ? "file" : "video";
    state.quality = "best";
    elements.platform.textContent = media.platform || "Media";
    elements.title.textContent = media.title || "Untitled media";
    elements.creator.textContent = media.uploader || (media.direct ? "Direct link" : "Ready to save");
    elements.duration.textContent = formatDuration(media.duration);
    elements.thumbnail.classList.remove("loaded");
    elements.thumbnail.removeAttribute("src");
    elements.fallback.style.display = "grid";
    if (media.thumbnail) {
      elements.thumbnail.onload = () => { elements.thumbnail.classList.add("loaded"); elements.fallback.style.display = "none"; };
      elements.thumbnail.onerror = () => { elements.thumbnail.classList.remove("loaded"); elements.fallback.style.display = "grid"; };
      elements.thumbnail.src = media.thumbnail;
    }
    elements.mediaCard.classList.remove("hidden");
    elements.options.classList.remove("hidden");
    elements.progressCard.classList.add("hidden");
    elements.save.classList.add("hidden");
    elements.progressCard.classList.remove("complete", "error");

    elements.formatTabs.forEach((tab) => {
      const unavailable = media.direct && tab.dataset.type !== "file";
      tab.disabled = unavailable;
      tab.style.opacity = unavailable ? ".38" : "1";
    });
    renderQualities();
    setType(state.type);
  }

  function renderQualities() {
    elements.qualityPicker.replaceChildren();
    const levels = ["best", ...(state.media?.formats || [])];
    const unique = [...new Set(levels)].slice(0, 5);
    unique.forEach((level) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "quality-choice";
      button.dataset.quality = String(level);
      button.textContent = level === "best" ? "Best" : `${level}p`;
      button.addEventListener("click", () => {
        state.quality = String(level);
        [...elements.qualityPicker.children].forEach((item) => item.classList.toggle("active", item === button));
      });
      elements.qualityPicker.append(button);
    });
  }

  function setType(type) {
    if (!state.media || (state.media.direct && type !== "file")) return;
    state.type = type;
    elements.formatTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.type === type));
    const video = type === "video";
    elements.qualityRow.classList.toggle("hidden", !video);
    const labels = { video: "Download video", audio: "Download audio", file: "Download original file" };
    elements.downloadLabel.textContent = labels[type];
    elements.download.dataset.idleLabel = labels[type];
    const activeQuality = elements.qualityPicker.querySelector(`[data-quality="${CSS.escape(state.quality)}"]`) || elements.qualityPicker.firstElementChild;
    if (activeQuality) activeQuality.classList.add("active");
  }

  async function inspectLink() {
    const url = elements.url.value.trim();
    if (!url) { showError("Paste a link to get started."); elements.url.focus(); return; }
    try {
      new URL(url);
    } catch {
      showError("That doesn’t look like a complete web link.");
      return;
    }
    showError();
    busy(elements.inspect, true);
    try {
      const data = await request("/api/inspect", { url });
      showMedia(data.media);
      elements.mediaCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      showError(error.message || "We couldn’t read that link.");
    } finally {
      busy(elements.inspect, false);
    }
  }

  function reset() {
    if (state.poller) clearTimeout(state.poller);
    state.media = null;
    state.type = "video";
    state.quality = "best";
    elements.mediaCard.classList.add("hidden");
    elements.options.classList.add("hidden");
    elements.progressCard.classList.add("hidden");
    elements.save.classList.add("hidden");
    elements.progressCard.classList.remove("complete", "error");
    showError();
    elements.url.focus();
  }

  function updateProgress(task) {
    const percent = Math.max(0, Math.min(100, Number(task.progress) || 0));
    const complete = task.status === "complete";
    const failed = task.status === "error";
    elements.progressCard.classList.remove("hidden");
    elements.progressCard.classList.toggle("complete", complete);
    elements.progressCard.classList.toggle("error", failed);
    elements.progressBar.style.width = `${percent}%`;
    elements.progressPercent.textContent = `${percent}%`;
    elements.progressTitle.textContent = complete ? "Your file is ready" : failed ? "Download couldn’t finish" : task.title || "Preparing your download";
    elements.progressDetail.textContent = failed ? (task.error || "Please check the link and try again.") : (task.stage || "Working…");
    if (complete) {
      elements.progressIcon.innerHTML = checkIcon;
      elements.save.href = task.downloadUrl;
      elements.save.classList.remove("hidden");
      busy(elements.download, false, elements.download.dataset.idleLabel);
      toast("Your file is ready to save.");
    } else if (failed) {
      elements.progressIcon.innerHTML = errorIcon;
      elements.save.classList.add("hidden");
      busy(elements.download, false, elements.download.dataset.idleLabel);
    }
  }

  async function pollTask(id) {
    try {
      const response = await fetch(`/api/tasks/${encodeURIComponent(id)}`);
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "The download status could not be checked.");
      updateProgress(data.task);
      if (!["complete", "error"].includes(data.task.status)) state.poller = setTimeout(() => pollTask(id), 800);
    } catch (error) {
      updateProgress({ status: "error", error: error.message, progress: 0 });
    }
  }

  async function beginDownload() {
    if (!state.media) { await inspectLink(); if (!state.media) return; }
    const url = elements.url.value.trim();
    busy(elements.download, true);
    elements.progressCard.classList.remove("hidden", "complete", "error");
    elements.progressIcon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3v11m0 0 4-4m-4 4-4-4M5 16.5v1.25A2.25 2.25 0 0 0 7.25 20h9.5A2.25 2.25 0 0 0 19 17.75V16.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    elements.progressTitle.textContent = "Preparing your download";
    elements.progressPercent.textContent = "0%";
    elements.progressBar.style.width = "2%";
    elements.progressDetail.textContent = "Creating a secure download…";
    elements.save.classList.add("hidden");
    try {
      const data = await request("/api/download", { url, type: state.type, quality: state.quality });
      updateProgress(data.task);
      if (state.poller) clearTimeout(state.poller);
      state.poller = setTimeout(() => pollTask(data.task.id), 450);
    } catch (error) {
      updateProgress({ status: "error", error: error.message, progress: 0 });
    }
  }

  elements.form.addEventListener("submit", (event) => { event.preventDefault(); inspectLink(); });
  elements.url.addEventListener("input", () => { if (state.media) reset(); });
  elements.reset.addEventListener("click", reset);
  elements.download.addEventListener("click", beginDownload);
  elements.formatTabs.forEach((tab) => tab.addEventListener("click", () => setType(tab.dataset.type)));
  elements.paste.addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text) { toast("Your clipboard is empty."); return; }
      elements.url.value = text.trim();
      toast("Link pasted.");
      inspectLink();
    } catch { toast("Paste your link in the field above."); elements.url.focus(); }
  });

  ["dragenter", "dragover"].forEach((type) => document.addEventListener(type, (event) => { event.preventDefault(); document.body.classList.add("is-dragging"); }));
  ["dragleave", "drop"].forEach((type) => document.addEventListener(type, (event) => { event.preventDefault(); document.body.classList.remove("is-dragging"); }));
  document.addEventListener("drop", (event) => {
    const url = event.dataTransfer?.getData("text/plain")?.trim();
    if (url) { elements.url.value = url; inspectLink(); }
  });
})();
