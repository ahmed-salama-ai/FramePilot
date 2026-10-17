// FramePilot - New Project Upload Page Logic

document.addEventListener("DOMContentLoaded", () => {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const filePreviewList = document.getElementById("filePreviewList");
  const form = document.getElementById("uploadForm");
  const uploadProgressContainer = document.getElementById("uploadProgressContainer");
  const uploadBarFill = document.getElementById("uploadBarFill");
  const uploadPercent = document.getElementById("uploadPercent");
  const uploadErrorNotice = document.getElementById("uploadErrorNotice");
  const submitBtn = document.getElementById("submitBtn");

  if (!dropzone || !fileInput || !form) return;

  let selectedFiles = [];

  // ---------- who is in the video (names -> name cards) ----------
  const ROLES = ["host", "co-host", "guest", "interviewer", "interviewee", "moderator", "panelist", "presenter", "other"];
  const peopleList = document.getElementById("peopleList");

  function addPerson(name = "", role = "") {
    if (!peopleList || peopleList.children.length >= 10) return;
    const row = document.createElement("div");
    row.className = "person-row";
    const roleOptions = ROLES.map(r => `<option value="${r}">${typeof t === "function" ? t("role_" + r.replace("-", "_")) : r}</option>`).join("");
    row.innerHTML = `
      <input type="text" class="form-control person-name" maxlength="60" dir="auto"
             placeholder="${typeof t === "function" ? t("ph_person_name") : "Name"}">
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

  dropzone.addEventListener("click", () => fileInput.click());

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
  });

  function handleFiles(files) {
    if (uploadErrorNotice) uploadErrorNotice.style.display = "none";
    const vids = files.filter(f => f.type.startsWith("video/") || f.name.match(/\.(mp4|mov|mkv|avi)$/i));
    if (vids.length === 0) {
      showError("Please select video files only (MP4, MOV).");
      return;
    }
    selectedFiles = vids;
    renderPreview();
  }

  function renderPreview() {
    if (!filePreviewList) return;
    filePreviewList.innerHTML = "";
    selectedFiles.forEach((file, idx) => {
      const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
      const item = document.createElement("div");
      item.className = "file-preview-item";
      item.innerHTML = `
        <div style="display: flex; align-items: center; gap: 12px;">
          <span style="font-weight: 700; color: var(--accent-orange); font-family: var(--font-mono);">Cam ${idx + 1}</span>
          <div>
            <div style="font-weight: 600; color: var(--text-bright);">${escapeHtml(file.name)}</div>
            <div style="font-size: 0.8rem; color: var(--text-quiet);"><bdi>${sizeMb} MB</bdi></div>
          </div>
        </div>
        <button type="button" class="btn btn-sm btn-danger" data-remove-idx="${idx}">✕</button>
      `;
      const removeBtn = item.querySelector("[data-remove-idx]");
      if (removeBtn) {
        removeBtn.addEventListener("click", () => {
          selectedFiles.splice(idx, 1);
          renderPreview();
        });
      }
      filePreviewList.appendChild(item);
    });
  }

  function showError(msg) {
    if (!uploadErrorNotice) return;
    uploadErrorNotice.textContent = msg;
    uploadErrorNotice.style.display = "block";
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, m => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[m]));
  }

  form.addEventListener("submit", e => {
    e.preventDefault();
    if (uploadErrorNotice) uploadErrorNotice.style.display = "none";

    if (selectedFiles.length < 2 || selectedFiles.length > 4) {
      showError(typeof t === "function" ? t("err_select_files") : "Please upload between 2 and 4 video files.");
      return;
    }

    const consentBox = document.getElementById("consentBox");
    if (!consentBox || !consentBox.checked) {
      showError(typeof t === "function" ? t("err_consent_required") : "Consent is required.");
      return;
    }

    const formData = new FormData();
    const nameEl = document.getElementById("projectName");
    const langEl = document.getElementById("languageSelect");
    const wideCamEl = document.getElementById("wideCamSelect");
    const numSpkEl = document.getElementById("numSpeakers");

    formData.append("name", nameEl ? nameEl.value.trim() : "New Project");
    formData.append("language", langEl ? langEl.value : "ar");
    formData.append("wide_cam", wideCamEl ? wideCamEl.value : "1");
    if (numSpkEl && numSpkEl.value) formData.append("num_speakers", numSpkEl.value);
    formData.append("consent", "true");
    formData.append("people_json", JSON.stringify(readPeople()));
    if (typeof readBrandForm === "function") {
      const brand = readBrandForm();
      if (!brandIsDefault(brand)) {
        formData.append("brand_json", JSON.stringify(brand.settings));
        ["logo", "intro", "outro", "music"].forEach(k => { if (brand[k]) formData.append(k, brand[k]); });
      }
    }

    selectedFiles.forEach(f => {
      formData.append("files", f);
    });

    if (submitBtn) submitBtn.disabled = true;
    if (uploadProgressContainer) uploadProgressContainer.style.display = "block";

    const xhr = new XMLHttpRequest();
    xhr.upload.onprogress = ev => {
      if (ev.lengthComputable && uploadBarFill && uploadPercent) {
        const pct = Math.round((ev.loaded / ev.total) * 100);
        uploadBarFill.style.width = pct + "%";
        uploadPercent.innerHTML = `<bdi>${pct}%</bdi>`;
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const res = JSON.parse(xhr.responseText);
          window.location.href = `/jobs/${res.job_id}`;
        } catch (err) {
          showError("Invalid server response.");
          if (submitBtn) submitBtn.disabled = false;
        }
      } else {
        let errDetail = "Upload failed";
        try {
          const res = JSON.parse(xhr.responseText);
          errDetail = res.detail || errDetail;
        } catch (ex) {}
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
