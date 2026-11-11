// FramePilot - New Project Upload & Link Import Logic (English by default)

document.addEventListener("DOMContentLoaded", () => {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const filePreviewList = document.getElementById("filePreviewList");
  const form = document.getElementById("uploadForm");
  const uploadProgressContainer = document.getElementById("uploadProgressContainer");
  const uploadBarFill = document.getElementById("uploadBarFill");
  const uploadPercent = document.getElementById("uploadPercent");
  const uploadStatusText = document.getElementById("uploadStatusText") || uploadProgressContainer?.querySelector("span:first-child");
  const uploadErrorNotice = document.getElementById("uploadErrorNotice");
  const submitBtn = document.getElementById("submitBtn");

  // Custom bleep words: the box shows only while "Bleep profanity" is ticked
  const bleepToggle = document.getElementById("bleepProfanity");
  const bleepWordsBox = document.getElementById("bleepWordsBox");
  if (bleepToggle && bleepWordsBox) {
    const showBleepWords = () => { bleepWordsBox.hidden = !bleepToggle.checked; };
    bleepToggle.addEventListener("change", showBleepWords);
    showBleepWords();
  }

  // Sound effects: the volume shows only while "Add sound effects" is ticked
  const sfxToggle = document.getElementById("soundEffects");
  const sfxVolumeBox = document.getElementById("sfxVolumeBox");
  if (sfxToggle && sfxVolumeBox) {
    const showSfxVolume = () => { sfxVolumeBox.hidden = !sfxToggle.checked; };
    sfxToggle.addEventListener("change", showSfxVolume);
    showSfxVolume();
  }

  // Modern (+) Popover & Link Input elements
  const addSourceBtn = document.getElementById("addSourceBtn");
  const addSourceMenu = document.getElementById("addSourceMenu");
  const menuAttachFile = document.getElementById("menuAttachFile");
  const menuAddLink = document.getElementById("menuAddLink");
  const quickLinkInput = document.getElementById("quickLinkInput");
  const fetchLinkBtn = document.getElementById("fetchLinkBtn");

  if (!dropzone || !fileInput || !form) return;

  // Selected items: local files or imported links
  // Format:
  // Local file: { type: "file", file: File, name: string, size: number }
  // Link:       { type: "link", url: string, name: string, source: "gdrive" | "link" }
  let selectedItems = [];

  // ---------- Who is in the video (names -> name cards) ----------
  const ROLES = ["host", "co-host", "guest", "interviewer", "interviewee", "moderator", "panelist", "presenter", "other"];
  const peopleList = document.getElementById("peopleList");

  function addPerson(name = "", role = "") {
    if (!peopleList || peopleList.children.length >= 10) return;
    const row = document.createElement("div");
    row.className = "person-row";
    const roleOptions = ROLES.map(r => `<option value="${r}">${typeof t === "function" ? t("role_" + r.replace("-", "_")) : r}</option>`).join("");
    row.innerHTML = `
      <input type="text" class="form-control person-name" maxlength="60" dir="auto"
             placeholder="${typeof t === "function" ? t("ph_person_name") : "Speaker Name"}">
      <select class="form-control person-role"><option value="">${typeof t === "function" ? t("role_none") : "Role"}</option>${roleOptions}</select>
      <button type="button" class="btn btn-sm btn-danger">✕</button>`;
    row.querySelector(".person-name").value = name;
    row.querySelector(".person-role").value = role;
    row.querySelector("button").addEventListener("click", () => row.remove());
    peopleList.appendChild(row);
  }

  function readPeople() {
    return [...document.querySelectorAll(".person-row")]
      .map(r => ({ name: r.querySelector(".person-name").value.trim(), role: r.querySelector(".person-role").value }))
      .filter(p => p.name);
  }

  const addPersonBtn = document.getElementById("addPersonBtn");
  if (addPersonBtn) addPersonBtn.addEventListener("click", () => addPerson());

  // ---------- (+) Popover Menu Handling ----------
  if (addSourceBtn && addSourceMenu) {
    addSourceBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const isVisible = addSourceMenu.style.display === "flex";
      addSourceMenu.style.display = isVisible ? "none" : "flex";
    });

    document.addEventListener("click", (e) => {
      if (addSourceMenu && !addSourceMenu.contains(e.target) && e.target !== addSourceBtn) {
        addSourceMenu.style.display = "none";
      }
    });

    if (menuAttachFile) {
      menuAttachFile.addEventListener("click", () => {
        addSourceMenu.style.display = "none";
        fileInput.click();
      });
    }

    if (menuAddLink) {
      menuAddLink.addEventListener("click", () => {
        addSourceMenu.style.display = "none";
        if (quickLinkInput) {
          quickLinkInput.focus();
        }
      });
    }
  }

  // ---------- Dropzone Interactions ----------
  dropzone.addEventListener("click", (e) => {
    // Avoid re-triggering file input if clicking link bar or popover
    if (e.target.closest(".video-input-bar") || e.target.closest(".add-source-popover")) {
      return;
    }
    fileInput.click();
  });

  dropzone.addEventListener("dragover", e => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", e => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(Array.from(e.dataTransfer.files));
    }
  });

  fileInput.addEventListener("change", e => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(Array.from(e.target.files));
    }
    fileInput.value = "";
  });

  function handleFiles(files) {
    if (uploadErrorNotice) uploadErrorNotice.style.display = "none";
    const vids = files.filter(f => f.type.startsWith("video/") || f.name.match(/\.(mp4|mov|mkv|avi)$/i));
    if (vids.length === 0) {
      showError("Please select video files only (MP4, MOV, MKV, AVI).");
      return;
    }

    for (const f of vids) {
      if (selectedItems.length >= 4) {
        showError("Maximum camera limit reached (2 to 4 cameras allowed).");
        break;
      }
      selectedItems.push({
        type: "file",
        file: f,
        name: f.name,
        size: f.size
      });
    }
    renderPreview();
  }

  // ---------- Link Import & Inspection (Google Drive / Direct URL) ----------
  async function handleLinkImport() {
    if (!quickLinkInput) return false;
    const rawVal = quickLinkInput.value.trim();
    if (!rawVal) {
      showError("Please enter a valid video link or Google Drive URL.");
      return false;
    }

    if (selectedItems.length >= 4) {
      showError("Maximum 4 camera angles already selected.");
      return false;
    }

    // Support multiple URLs pasted at once (split by space, comma, or newline)
    const rawTokens = rawVal.split(/[\s,\n]+/).map(s => s.trim()).filter(Boolean);
    const urls = rawTokens.filter(u => u.startsWith("http://") || u.startsWith("https://"));

    if (urls.length === 0) {
      showError("Please enter valid URL(s) starting with http:// or https://");
      return false;
    }

    if (uploadErrorNotice) uploadErrorNotice.style.display = "none";
    if (fetchLinkBtn) {
      fetchLinkBtn.disabled = true;
      fetchLinkBtn.textContent = "⏳ Inspecting...";
    }

    let anySuccess = false;
    try {
      for (const url of urls) {
        if (selectedItems.length >= 4) {
          showError("Maximum 4 cameras limit reached.");
          break;
        }

        const res = await fetch("/api/import/inspect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url })
        });

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || "Failed to inspect link.");
        }

        if (data.type === "folder") {
          const items = data.items || [];
          if (items.length === 0) {
            showError("No video files found inside this Google Drive folder.");
            continue;
          }

          for (const item of items) {
            if (selectedItems.length >= 4) break;
            selectedItems.push({
              type: "link",
              url: item.url,
              name: item.name,
              source: "gdrive"
            });
            anySuccess = true;
          }
        } else {
          // Single file (Google Drive or direct URL)
          const isDrive = url.includes("drive.google.com");
          selectedItems.push({
            type: "link",
            url: data.url || url,
            name: data.name || `Cam ${selectedItems.length + 1} (Link)`,
            source: isDrive ? "gdrive" : "link"
          });
          anySuccess = true;
        }
      }

      if (anySuccess) {
        quickLinkInput.value = "";
        renderPreview();
        return true;
      }
      return false;
    } catch (err) {
      showError(err.message || "An error occurred while inspecting the link.");
      return false;
    } finally {
      if (fetchLinkBtn) {
        fetchLinkBtn.disabled = false;
        fetchLinkBtn.textContent = "⚡ Import Link";
      }
    }
  }

  if (fetchLinkBtn) {
    fetchLinkBtn.addEventListener("click", handleLinkImport);
  }
  if (quickLinkInput) {
    quickLinkInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleLinkImport();
      }
    });
  }

  // ---------- Quick Video Preview Modal Logic ----------
  const previewModal = document.getElementById("videoPreviewModal");
  const previewModalTitle = document.getElementById("previewModalTitle");
  const previewModalMeta = document.getElementById("previewModalMeta");
  const previewVideoPlayer = document.getElementById("previewVideoPlayer");
  const previewIframePlayer = document.getElementById("previewIframePlayer");
  const previewLoadingNotice = document.getElementById("previewLoadingNotice");
  const closePreviewModalBtn = document.getElementById("closePreviewModalBtn");
  const donePreviewBtn = document.getElementById("donePreviewBtn");

  function closeVideoPreview() {
    if (!previewModal) return;
    previewModal.style.display = "none";
    if (previewVideoPlayer) {
      previewVideoPlayer.pause();
      previewVideoPlayer.src = "";
      previewVideoPlayer.style.display = "none";
    }
    if (previewIframePlayer) {
      previewIframePlayer.src = "";
      previewIframePlayer.style.display = "none";
    }
    if (previewLoadingNotice) previewLoadingNotice.style.display = "block";
  }

  if (closePreviewModalBtn) closePreviewModalBtn.addEventListener("click", closeVideoPreview);
  if (donePreviewBtn) donePreviewBtn.addEventListener("click", closeVideoPreview);
  if (previewModal) {
    previewModal.addEventListener("click", (e) => {
      if (e.target === previewModal) closeVideoPreview();
    });
  }

  function openVideoPreview(item, camNum) {
    if (!previewModal) return;
    previewModal.style.display = "flex";
    if (previewModalTitle) {
      previewModalTitle.textContent = `Cam ${camNum} Preview: ${item.name}`;
    }
    if (previewModalMeta) {
      previewModalMeta.textContent = item.type === "file"
        ? `Local file: ${(item.size / (1024 * 1024)).toFixed(1)} MB`
        : `Source: ${item.source === "gdrive" ? "Google Drive" : "Direct Link"}`;
    }

    if (item.type === "file") {
      if (previewIframePlayer) previewIframePlayer.style.display = "none";
      if (previewVideoPlayer) {
        previewVideoPlayer.src = URL.createObjectURL(item.file);
        previewVideoPlayer.style.display = "block";
        if (previewLoadingNotice) previewLoadingNotice.style.display = "none";
        previewVideoPlayer.play().catch(() => { });
      }
    } else if (item.source === "gdrive") {
      const fidMatch = item.url.match(/\/file\/d\/([a-zA-Z0-9_-]{25,})/);
      const fid = fidMatch ? fidMatch[1] : null;
      if (fid && previewIframePlayer) {
        if (previewVideoPlayer) previewVideoPlayer.style.display = "none";
        previewIframePlayer.src = `https://drive.google.com/file/d/${fid}/preview`;
        previewIframePlayer.style.display = "block";
        if (previewLoadingNotice) previewLoadingNotice.style.display = "none";
      } else if (previewVideoPlayer) {
        previewVideoPlayer.src = item.url;
        previewVideoPlayer.style.display = "block";
        if (previewLoadingNotice) previewLoadingNotice.style.display = "none";
      }
    } else {
      if (previewIframePlayer) previewIframePlayer.style.display = "none";
      if (previewVideoPlayer) {
        previewVideoPlayer.src = item.url;
        previewVideoPlayer.style.display = "block";
        if (previewLoadingNotice) previewLoadingNotice.style.display = "none";
        previewVideoPlayer.play().catch(() => { });
      }
    }
  }

  // ---------- Render Camera Preview List with Re-order & Quick Preview ----------
  function renderPreview() {
    if (!filePreviewList) return;
    filePreviewList.innerHTML = "";

    selectedItems.forEach((item, idx) => {
      const itemEl = document.createElement("div");
      itemEl.className = "file-preview-item";

      let badgeHtml = "";
      let detailHtml = "";

      if (item.type === "file") {
        const sizeMb = (item.size / (1024 * 1024)).toFixed(1);
        badgeHtml = `<span class="source-badge source-badge-local">💻 Local File</span>`;
        detailHtml = `<span style="font-size: 0.8rem; color: var(--text-quiet);"><bdi>${sizeMb} MB</bdi></span>`;
      } else if (item.source === "gdrive") {
        badgeHtml = `<span class="source-badge source-badge-gdrive">📁 Google Drive</span>`;
        detailHtml = `<span style="font-size: 0.8rem; color: var(--text-quiet); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block;">${escapeHtml(item.url)}</span>`;
      } else {
        badgeHtml = `<span class="source-badge source-badge-link">🔗 Direct Link</span>`;
        detailHtml = `<span style="font-size: 0.8rem; color: var(--text-quiet); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block;">${escapeHtml(item.url)}</span>`;
      }

      itemEl.innerHTML = `
        <div style="display: flex; align-items: center; gap: 14px; flex: 1; min-width: 0;">
          <span style="font-weight: 700; color: var(--accent-orange); font-family: var(--font-mono); font-size: 0.95rem; white-space: nowrap;">
            Cam ${idx + 1}
          </span>
          <div style="min-width: 0; flex: 1;">
            <div style="font-weight: 600; color: var(--text-bright); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              ${escapeHtml(item.name)}
            </div>
            <div style="display: flex; align-items: center; gap: 8px; margin-top: 3px; flex-wrap: wrap;">
              ${badgeHtml}
              ${detailHtml}
            </div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0;">
          <button type="button" class="cam-action-btn" data-move-up="${idx}" title="Move camera up" ${idx === 0 ? "disabled" : ""}>▲</button>
          <button type="button" class="cam-action-btn" data-move-down="${idx}" title="Move camera down" ${idx === selectedItems.length - 1 ? "disabled" : ""}>▼</button>
          <button type="button" class="cam-action-btn" data-preview-idx="${idx}" title="Preview camera video">👁 Preview</button>
          <button type="button" class="btn btn-sm btn-danger" data-remove-idx="${idx}" title="Remove Camera" style="padding: 4px 10px;">✕</button>
        </div>
      `;

      // Event: Move Up
      const upBtn = itemEl.querySelector("[data-move-up]");
      if (upBtn) {
        upBtn.addEventListener("click", () => {
          if (idx > 0) {
            const temp = selectedItems[idx];
            selectedItems[idx] = selectedItems[idx - 1];
            selectedItems[idx - 1] = temp;
            renderPreview();
          }
        });
      }

      // Event: Move Down
      const downBtn = itemEl.querySelector("[data-move-down]");
      if (downBtn) {
        downBtn.addEventListener("click", () => {
          if (idx < selectedItems.length - 1) {
            const temp = selectedItems[idx];
            selectedItems[idx] = selectedItems[idx + 1];
            selectedItems[idx + 1] = temp;
            renderPreview();
          }
        });
      }

      // Event: Quick Preview
      const previewBtn = itemEl.querySelector("[data-preview-idx]");
      if (previewBtn) {
        previewBtn.addEventListener("click", () => {
          openVideoPreview(item, idx + 1);
        });
      }

      // Event: Remove
      const removeBtn = itemEl.querySelector("[data-remove-idx]");
      if (removeBtn) {
        removeBtn.addEventListener("click", () => {
          selectedItems.splice(idx, 1);
          renderPreview();
        });
      }
      filePreviewList.appendChild(itemEl);
    });

    // Update Wide Cam select options to match count
    const wideCamSelect = document.getElementById("wideCamSelect");
    if (wideCamSelect) {
      const prevVal = wideCamSelect.value || "1";
      const count = Math.max(selectedItems.length, 2);
      wideCamSelect.innerHTML = "";
      for (let c = 1; c <= Math.min(count, 4); c++) {
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = `Camera ${c}` + (c === 1 ? " (Default Wide)" : "");
        if (String(c) === String(prevVal)) opt.selected = true;
        wideCamSelect.appendChild(opt);
      }
    }
  }

  const linkFeedbackNotice = document.getElementById("linkFeedbackNotice");
  function showError(msg) {
    if (linkFeedbackNotice) {
      linkFeedbackNotice.textContent = msg;
      linkFeedbackNotice.style.display = "block";
    }
    if (uploadErrorNotice) {
      uploadErrorNotice.textContent = msg;
      uploadErrorNotice.style.display = "block";
    }
  }

  function clearErrors() {
    if (linkFeedbackNotice) linkFeedbackNotice.style.display = "none";
    if (uploadErrorNotice) uploadErrorNotice.style.display = "none";
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, m => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[m]));
  }

  // ---------- Form Submission & Project Creation ----------
  let renderUploadProgress = null;   // set while an upload runs: redraws its progress texts
  document.addEventListener("framepilot:lang", () => { if (renderUploadProgress) renderUploadProgress(); });

  form.addEventListener("submit", async e => {
    e.preventDefault();
    if (uploadErrorNotice) uploadErrorNotice.style.display = "none";

    // If user entered a link into the input but didn't click "Import Link" beforehand, auto-import it now!
    if (quickLinkInput && quickLinkInput.value.trim() && selectedItems.length < 4) {
      const ok = await handleLinkImport();
      if (!ok) {
        return; // handleLinkImport already showed the exact detailed error
      }
    }

    if (selectedItems.length < 2 || selectedItems.length > 4) {
      showError("Please select between 2 and 4 camera recordings (files or links).");
      return;
    }

    const consentBox = document.getElementById("consentBox");
    if (!consentBox || !consentBox.checked) {
      showError("Consent agreement is required before proceeding.");
      return;
    }

    // Editing style (styles.js): checked by the server before any video is sent
    const style = typeof window.readStyleForm === "function" ? await window.readStyleForm() : { ok: true, value: null };
    if (!style.ok) {
      showError(style.message);
      return;
    }

    const formData = new FormData();
    const nameEl = document.getElementById("projectName");
    const langEl = document.getElementById("languageSelect");
    const wideCamEl = document.getElementById("wideCamSelect");
    const numSpkEl = document.getElementById("numSpeakers");

    formData.append("name", nameEl ? nameEl.value.trim() : "New Project");
    formData.append("language", langEl ? langEl.value : "en");
    formData.append("wide_cam", wideCamEl ? wideCamEl.value : "1");
    if (numSpkEl && numSpkEl.value) formData.append("num_speakers", numSpkEl.value);
    formData.append("consent", "true");
    formData.append("people_json", JSON.stringify(readPeople()));
    const bleepEl = document.getElementById("bleepProfanity");
    formData.append("bleep_profanity", bleepEl && bleepEl.checked ? "true" : "false");
    const bleepWordsEl = document.getElementById("bleepWords");
    if (bleepEl && bleepEl.checked && bleepWordsEl && bleepWordsEl.value.trim()) {
      formData.append("bleep_words", bleepWordsEl.value);
    }
    const fillerEl = document.getElementById("fillerMode");
    formData.append("filler_mode", fillerEl ? fillerEl.value : "off");
    const sfxEl = document.getElementById("soundEffects");
    const sfxVolumeEl = document.getElementById("sfxVolume");
    formData.append("sound_effects", sfxEl && sfxEl.checked ? "true" : "false");
    if (sfxEl && sfxEl.checked && sfxVolumeEl) formData.append("sfx_volume", sfxVolumeEl.value);
    if (style.value) formData.append("style_json", JSON.stringify(style.value));

    if (typeof readBrandForm === "function") {
      const brand = readBrandForm();
      if (!brandIsDefault(brand)) {
        formData.append("brand_json", JSON.stringify(brand.settings));
        ["logo", "intro", "outro", "music"].forEach(k => { if (brand[k]) formData.append(k, brand[k]); });
      }
    }

    // Append local files, collected links, and unified items_order_json for exact camera ordering
    const linkItems = [];
      const orderedItems = [];
      let fileCounter = 0;

      selectedItems.forEach((item, pos) => {
        if (item.type === "file") {
          formData.append("files", item.file);
          orderedItems.push({ type: "file", index: fileCounter, name: item.name });
          fileCounter++;
        } else if (item.type === "link") {
          linkItems.push({ url: item.url, name: item.name });
          orderedItems.push({ type: "link", url: item.url, name: item.name });
        }
      });

      formData.append("items_order_json", JSON.stringify(orderedItems));
      formData.append("links_json", JSON.stringify(linkItems));

      // The server downloads the links after the form has arrived; the page follows each camera with this id
      const progressId = Array.from(crypto.getRandomValues(new Uint8Array(12)),
        b => b.toString(16).padStart(2, "0")).join("");
      formData.append("progress_id", progressId);

      if (submitBtn) submitBtn.disabled = true;
      if (uploadProgressContainer) uploadProgressContainer.style.display = "block";

      // One row per camera: "Camera 1: name (source)" ... status
      const multiCamProgressList = document.getElementById("multiCamProgressList");
      if (multiCamProgressList) {
        multiCamProgressList.innerHTML = "";
        selectedItems.forEach((item, idx) => {
          const row = document.createElement("div");
          row.id = `camProgress_${idx}`;
          row.style.cssText = "display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 12px; background: rgba(0,0,0,0.3); border-radius: var(--radius-sm); border: 1px solid rgba(255,255,255,0.05); font-size: 0.83rem;";
          const icon = item.type === "file" ? "💻" : (item.source === "gdrive" ? "📁" : "🔗");
          row.innerHTML = `
          <div style="display: flex; align-items: center; gap: 8px; min-width: 0;">
            <span class="cam-label" style="font-weight: 700; color: var(--accent-orange); white-space: nowrap;"></span>
            <span style="color: var(--text-bright); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(item.name)}</span>
            <span style="color: var(--text-quiet); font-size: 0.78rem; white-space: nowrap;">(${icon} <span class="cam-source"></span>)</span>
          </div>
          <span class="cam-status" style="font-weight: 600; white-space: nowrap;"></span>
        `;
          multiCamProgressList.appendChild(row);
        });
      }

      const hasLocal = selectedItems.some(item => item.type === "file");
      const linkPositions = selectedItems.map((item, idx) => (item.type === "link" ? idx : -1)).filter(idx => idx >= 0);
      let uploadFraction = 0;   // the browser sending the form (local files travel inside it), 0..1
      let serverCams = null;    // per camera from /api/import/progress: {state, done, total}
      let finished = "";        // "ok" | "failed" once the server has answered
      let failedIdx = -1;       // the camera the server was working on when it failed

      const ORANGE = "var(--accent-orange)", GREEN = "#4ade80", RED = "#ff6b7d", QUIET = "var(--text-quiet)";

      function formatBytes(bytes) {
        const mb = 1024 * 1024, gb = 1024 * mb;
        return bytes >= gb ? `${(bytes / gb).toFixed(1)} ${t("unit_gb")}` : `${Math.round(bytes / mb)} ${t("unit_mb")}`;
      }

      // How far one camera is, 0..1. A link reaches 1 only once the server has checked the video.
      function camFraction(item, idx) {
        if (finished === "ok") return 1;
        if (item.type === "file") return uploadFraction;
        const cam = serverCams && serverCams[idx];
        if (!cam) return 0;
        if (cam.state === "ready") return 1;
        if (cam.state === "checking") return 0.99;
        if (cam.state === "downloading" && cam.total) return Math.min(cam.done / cam.total, 1) * 0.98;
        return 0;
      }

      function camStatus(item, idx) {
        if (finished === "ok") return [t("cam_ready"), GREEN];
        if (idx === failedIdx) return [t("cam_failed"), RED];
        if (item.type === "file") {
          return uploadFraction >= 1 ? [t("cam_uploaded"), GREEN]
            : [t("cam_uploading", { pct: Math.floor(uploadFraction * 100) }), ORANGE];
        }
        if (failedIdx >= 0) return idx < failedIdx ? [t("cam_ready"), GREEN] : [t("cam_not_started"), QUIET];
        const cam = serverCams && serverCams[idx];
        if (!cam || cam.state === "waiting") return [t("cam_waiting"), QUIET];
        if (cam.state === "ready") return [t("cam_ready"), GREEN];
        if (cam.state === "checking") return [t("cam_checking"), ORANGE];
        if (cam.total) {
          const pct = Math.min(99, Math.floor((cam.done / cam.total) * 100));
          return [t("cam_downloading", { pct, done: formatBytes(cam.done), total: formatBytes(cam.total) }), ORANGE];
        }
        return [t("cam_downloading_nosize", { done: formatBytes(cam.done) }), ORANGE];
      }

      function topStatus() {
        if (finished === "ok") return t("up_done");
        if (finished === "failed") return t("up_failed");
        if (hasLocal && uploadFraction < 1) return t("up_uploading");
        const current = linkPositions.findIndex(idx => !(serverCams && serverCams[idx] && serverCams[idx].state === "ready"));
        if (current < 0) return t("up_checking");
        const cam = serverCams && serverCams[linkPositions[current]];
        if (cam && cam.state === "checking") return t("up_checking");
        return t("up_downloading", { n: current + 1, total: linkPositions.length });
      }

      function renderProgress() {
        const fractions = selectedItems.map(camFraction);
        const pct = Math.floor((fractions.reduce((a, b) => a + b, 0) / fractions.length) * 100);
        if (uploadBarFill) uploadBarFill.style.width = pct + "%";
        if (uploadPercent) uploadPercent.innerHTML = `<bdi>${pct}%</bdi>`;
        if (uploadStatusText) uploadStatusText.textContent = topStatus();
        selectedItems.forEach((item, idx) => {
          const row = document.getElementById(`camProgress_${idx}`);
          if (!row) return;
          row.querySelector(".cam-label").textContent = `${t("camera")} ${idx + 1}:`;
          row.querySelector(".cam-source").textContent =
            t(item.type === "file" ? "src_local" : (item.source === "gdrive" ? "src_drive" : "src_link"));
          const [text, color] = camStatus(item, idx);
          const statusSpan = row.querySelector(".cam-status");
          statusSpan.textContent = text;
          statusSpan.style.color = color;
        });
      }
      renderUploadProgress = renderProgress;   // redrawn in the new language if the user switches
      renderProgress();

      // Ask the server every second how far the downloads are, from the moment the form has arrived
      let pollTimer = null;
      let polling = false;
      async function pollProgress() {
        if (polling || finished) return;
        polling = true;
        try {
          const res = await fetch(`/api/import/progress/${progressId}`, { cache: "no-store" });
          if (res.ok && !finished) {
            serverCams = (await res.json()).cameras;
            renderProgress();
          }
        } catch (err) {
          // the upload request itself reports any error
        } finally {
          polling = false;
        }
      }
      function startPolling() {
        if (!linkPositions.length || pollTimer || finished) return;
        pollProgress();
        pollTimer = setInterval(pollProgress, 1000);
      }
      function stopPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = null;
      }

      const xhr = new XMLHttpRequest();
      xhr.upload.onprogress = ev => {
        if (!ev.lengthComputable) return;
        uploadFraction = ev.total ? ev.loaded / ev.total : 1;
        renderProgress();
        if (uploadFraction >= 1) startPolling();
      };
      xhr.upload.onload = () => {
        uploadFraction = 1;
        renderProgress();
        startPolling();
      };

      xhr.onload = () => {
        stopPolling();
        if (xhr.status >= 200 && xhr.status < 300) {
          finished = "ok";
          renderProgress();
          try {
            const res = JSON.parse(xhr.responseText);
            setTimeout(() => {
              window.location.href = `/jobs/${res.job_id}`;
            }, 600);
          } catch (err) {
            showError("Invalid server response.");
            if (submitBtn) submitBtn.disabled = false;
          }
        } else {
          finished = "failed";
          failedIdx = parseInt(xhr.getResponseHeader("X-Failed-Camera") || "0", 10) - 1;   // -1: not a camera
          renderProgress();
          let errDetail = "Upload / Download failed";
          try {
            const res = JSON.parse(xhr.responseText);
            const d = res.detail;                          // a style error comes as {en, ar}
            errDetail = (d && typeof d === "object" && !Array.isArray(d))
              ? (d[typeof getLang === "function" ? getLang() : "en"] || d.en || errDetail)
              : (d || errDetail);
          } catch (ex) { }
          showError(errDetail);
          if (submitBtn) submitBtn.disabled = false;
        }
      };

      xhr.onerror = () => {
        stopPolling();
        finished = "failed";
        renderProgress();
        showError("Network connection interrupted during upload.");
        if (submitBtn) submitBtn.disabled = false;
      };

      xhr.open("POST", "/api/projects");
      xhr.send(formData);
    });
  });
