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

      if (submitBtn) submitBtn.disabled = true;
      if (uploadProgressContainer) uploadProgressContainer.style.display = "block";

      // Build per-camera multiCamProgressList
      const multiCamProgressList = document.getElementById("multiCamProgressList");
      if (multiCamProgressList) {
        multiCamProgressList.innerHTML = "";
        selectedItems.forEach((item, idx) => {
          const row = document.createElement("div");
          row.id = `camProgress_${idx}`;
          row.style.cssText = "display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: rgba(0,0,0,0.3); border-radius: var(--radius-sm); border: 1px solid rgba(255,255,255,0.05); font-size: 0.83rem;";
          const isLocal = item.type === "file";
          const icon = isLocal ? "💻" : (item.source === "gdrive" ? "📁" : "🔗");
          row.innerHTML = `
          <div style="display: flex; align-items: center; gap: 8px; min-width: 0;">
            <span style="font-weight: 700; color: var(--accent-orange); white-space: nowrap;">Cam ${idx + 1}:</span>
            <span style="color: var(--text-bright); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(item.name)}</span>
            <span style="color: var(--text-quiet); font-size: 0.78rem;">(${icon} ${isLocal ? "Local" : "Cloud"})</span>
          </div>
          <span class="cam-status" style="color: var(--accent-orange); font-weight: 600; white-space: nowrap;">Preparing... ⏳</span>
        `;
          multiCamProgressList.appendChild(row);
        });
      }

      const hasLinks = linkItems.length > 0;
      if (uploadStatusText) {
        uploadStatusText.textContent = hasLinks
          ? "Streaming cloud recordings to server and verifying..."
          : "Uploading local video recordings to server...";
      }

      const xhr = new XMLHttpRequest();
      xhr.upload.onprogress = ev => {
        if (ev.lengthComputable && uploadBarFill && uploadPercent) {
          const pct = Math.round((ev.loaded / ev.total) * 100);
          uploadBarFill.style.width = pct + "%";
          uploadPercent.innerHTML = `<bdi>${pct}%</bdi>`;

          if (pct >= 100) {
            if (uploadStatusText) {
              uploadStatusText.textContent = hasLinks
                ? "Streaming and verifying videos with ffprobe directly on server..."
                : "Verifying recordings and initializing pipeline...";
            }
            if (multiCamProgressList) {
              selectedItems.forEach((item, idx) => {
                const row = document.getElementById(`camProgress_${idx}`);
                if (row) {
                  const statusSpan = row.querySelector(".cam-status");
                  if (statusSpan) {
                    if (item.type === "file") {
                      statusSpan.style.color = "#4ade80";
                      statusSpan.textContent = "Uploaded & Probed ✅";
                    } else {
                      statusSpan.style.color = "var(--accent-orange)";
                      statusSpan.textContent = "Streaming directly to disk... ⏳";
                    }
                  }
                }
              });
            }
          }
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          if (multiCamProgressList) {
            selectedItems.forEach((item, idx) => {
              const row = document.getElementById(`camProgress_${idx}`);
              if (row) {
                const statusSpan = row.querySelector(".cam-status");
                if (statusSpan) {
                  statusSpan.style.color = "#4ade80";
                  statusSpan.textContent = "Ready & Verified ✅";
                }
              }
            });
          }
          if (uploadStatusText) {
            uploadStatusText.textContent = "All camera recordings verified! Redirecting to Director...";
          }
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
        showError("Network connection interrupted during upload.");
        if (submitBtn) submitBtn.disabled = false;
      };

      xhr.open("POST", "/api/projects");
      xhr.send(formData);
    });
  });
