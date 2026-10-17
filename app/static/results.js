// FramePilot - Results Studio Dashboard Logic

let player = null;
let chartInstance = null;
let timelineData = null;
let currentSpeakers = {};      // {SPEAKER_00: name shown when the page loaded}
let speakerMap = {};           // {SPEAKER_00: camera} from speaker_map.json
let versions = [];             // every version of the whole video (versions.json)
let publishData = null;
let publishLang = null;
let lastClips = [];
let lastData = null;           // the last /api/sessions answer (stats, trailer, thumbnails redraw on a language switch)
let whyData = [];              // "why this shot?" for the chosen version's shots
let speakerNames = {};         // {SPEAKER_00: "Salma"} for search results and stats

const CAM_COLORS = {
  "1": "#6d7384",
  "2": "#4688d7",
  "3": "#d68537",
  "4": "#9c5cdb"
};

const tr = (key, fallback, vars) => (typeof t === "function" ? t(key, vars) : fallback);

function getSid() {
  const sidEl = document.getElementById("sidLabel");
  return sidEl ? sidEl.textContent.trim() : "";
}

async function loadSession() {
  const sid = getSid();
  if (!sid) return;

  try {
    const res = await fetch(`/api/sessions/${sid}`);
    if (!res.ok) return;
    const data = await res.json();

    // Session duration
    if (data.session && data.session.duration) {
      const d = data.session.duration;
      const m = Math.floor(d / 60);
      const s = Math.floor(d % 60);
      const durEl = document.getElementById("durationText");
      if (durEl) durEl.textContent = `${m}:${s.toString().padStart(2, '0')}`;
    }

    speakerMap = data.speaker_map || {};
    lastData = data;
    speakerNames = {};
    (data.speakers || []).forEach(x => { speakerNames[x.speaker] = x.name || x.role || x.speaker; });
    if (data.timeline) timelineData = data.timeline;      // first: the chosen version draws its own on-air strip
    showVersions(data.versions || []);
    showJobNotice(data.job);

    // Timeline Chart
    if (data.timeline) {
      renderTimelineChart(data.timeline);
      if (!versions.length) renderOnAirStrip(data.timeline, data.cuts);
      renderModeStrip(data.timeline);
    }

    if (data.speakers) renderSpeakers(data.speakers);
    renderStats(data.stats);
    if (data.highlights) renderHighlights(data.highlights);
    renderTrailer(data.trailer);
    renderThumbnails(data.thumbnails);
    renderClips(data.clips || []);
    publishData = data.publish;
    showPublish(publishLang || (data.session && data.session.language) || "ar");
    if (typeof fillBrandForm === "function") fillBrandForm(data.brand || BRAND_DEFAULT);
    if (data.metrics) renderMetrics(data.metrics);

  } catch (err) {
    console.error("Failed to load session:", err);
  }
}

// ---------- versions (version history) ----------

function versionLabel(v) {
  if (v.made_by === "pipeline") return `${v.id} · ${tr("version_by_pipeline", "AI edit")}`;
  if (v.made_by === "update") {
    const base = (v.note.match(/v\d+/) || [""])[0];
    return `${v.id} · ${tr("version_updated_from", "Updated from {id}", { id: base })}`;
  }
  const by = v.made_by === "agent" ? tr("version_by_agent", "Editor Agent") : v.made_by;
  return `${v.id} · ${v.note || by}`;
}

let viewMode = "caps";         // the player shows the finished video "caps" (with captions) or "clean" (without)
let versionsShown = false;

function showVersions(list, keep) {
  versions = list || [];
  const sel = document.getElementById("videoVersionSelect");
  if (!sel) return;
  // first time: the newest version; later: keep the one that was chosen
  const before = keep || (versionsShown ? sel.value : (versions[versions.length - 1] || {}).id);
  versionsShown = true;
  sel.innerHTML = "";
  versions.forEach(v => {
    const opt = document.createElement("option");
    opt.value = v.id;
    opt.textContent = versionLabel(v);
    sel.appendChild(opt);
  });
  if (versions.some(v => v.id === before)) sel.value = before;
  selectVersion(sel.value, false);
}

function currentVersion() {
  const sel = document.getElementById("videoVersionSelect");
  return versions.find(v => v.id === (sel ? sel.value : "v1")) || versions[0];
}

// what the player shows: the finished video (captions, name cards, logo, intro, outro), or the same without captions;
// a version that has no finished file yet: the plain edit + the captions track
function playerFile(v) {
  if (viewMode === "clean" && v.has_clean) return { file: v.clean, finished: true };
  if (viewMode === "caps" && v.has_program) return { file: v.program, finished: true };
  return { file: v.nocaps, finished: false };
}

// a time of the edit -> the time in what the player shows (the finished videos start with the brand intro)
function seekTo(t) {
  if (!player) return;
  const v = currentVersion();
  player.currentTime = t + (v && playerFile(v).finished ? (v.intro || 0) : 0);
}

function setView(mode) {
  viewMode = mode;
  const v = currentVersion();
  if (v) selectVersion(v.id, true);
}

async function selectVersion(vid, play = true) {
  const sid = getSid();
  const v = versions.find(x => x.id === vid);
  if (!v) return;
  const shown = playerFile(v);
  const source = document.getElementById("videoSource");
  if (source && player && !source.src.endsWith(`/files/${sid}/${shown.file}`)) {
    source.src = `/files/${sid}/${shown.file}`;
    player.load();
    if (play) player.play();
  }
  const track = document.getElementById("captionsTrack");          // burned-in captions: no second copy on top
  if (track && track.track) track.track.mode = !shown.finished && viewMode === "caps" ? "showing" : "disabled";
  document.querySelectorAll("[data-view]").forEach(b => b.classList.toggle("btn-primary", b.dataset.view === viewMode));

  const podcast = document.getElementById("podcastLink");
  if (podcast) podcast.href = `/api/sessions/${sid}/podcast/${v.id}`;
  [["srtArLink", "ar", "srt"], ["srtEnLink", "en", "srt"], ["vttLink", "ar+en", "vtt"]].forEach(([id, lang, fmt]) => {
    const a = document.getElementById(id);                         // timed for this version (intro, cut pauses)
    if (a) a.href = `/api/sessions/${sid}/captions/${v.id}?lang=${encodeURIComponent(lang)}&fmt=${fmt}`;
  });
  const exportLink = document.getElementById("exportLink");
  if (exportLink) exportLink.href = `/api/sessions/${sid}/export/${v.id}`;
  const del = document.getElementById("deleteVersionBtn");
  if (del) del.style.display = v.id === "v1" ? "none" : "";
  const info = document.getElementById("versionInfo");
  if (info) {
    const by = { pipeline: tr("version_by_pipeline", "AI edit"), agent: tr("version_by_agent", "Editor Agent"),
                 update: tr("version_by_update", "Update video") }[v.made_by] || v.made_by;
    info.textContent = by + (v.created ? " · " + v.created.replace("T", " ") : "");
  }
  if (publishLang !== null) showPublish(publishLang);               // the chapters' times of this version
  // the on-air strip shows this version's cuts, each with its "why this shot?"
  if (timelineData) {
    try {
      const [res, why] = await Promise.all([fetch(`/files/${sid}/${v.cuts}`), fetch(`/api/sessions/${sid}/why/${v.id}`)]);
      whyData = why.ok ? await why.json() : [];
      if (res.ok) renderOnAirStrip(timelineData, await res.json());
    } catch (err) {
      console.error("Failed to load the version's cuts:", err);
    }
  }
}

// ---------- downloads: the video with captions in one language (made on request), job progress ----------

function triggerDownload(url) {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function langNotice(text) {
  const box = document.getElementById("langNotice");
  if (!box) return;
  box.style.display = text ? "block" : "none";
  box.textContent = text || "";
}

async function downloadVideo() {
  const v = currentVersion();
  if (!v) return;
  const sid = getSid();
  const langs = (document.getElementById("downloadLang") || {}).value || "ar+en";
  if (langs === "ar+en" && v.has_program) return triggerDownload(`/files/${sid}/${v.program}`);
  if (langs === "none") return triggerDownload(`/files/${sid}/${v.has_clean ? v.clean : v.nocaps}`);
  const res = await fetch(`/api/sessions/${sid}/language`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: v.id, langs })
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return alert(data.detail || "Failed");
  if (data.ready) return triggerDownload(`/files/${sid}/${data.file}`);
  waitForJob(data.job_id, tr("lang_making", "Making the video with these captions"), async () => {
    await refreshVersions();
    const again = await fetch(`/api/sessions/${sid}/language`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: v.id, langs })
    });
    const d = await again.json().catch(() => ({}));
    if (d.ready) triggerDownload(`/files/${sid}/${d.file}`);
  });
}

// follow a job on this page: "... 40 % · about 30 s left", then onDone()
function waitForJob(jobId, label, onDone) {
  const tick = async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      const j = await res.json();
      if (j.status === "done") {
        langNotice(tr("lang_ready", "Ready ✓ the download starts"));
        setTimeout(() => langNotice(""), 4000);
        return onDone();
      }
      if (j.status === "error") return langNotice(`${tr("status_error", "Failed")}: ${j.error || ""}`);
      const left = j.eta_seconds ? ` · ${tr("lang_left", "about {s} s left", { s: j.eta_seconds })}` : "";
      langNotice(`⏳ ${label} · ${j.progress || 0}%${left}`);
    } catch (err) {
      console.error(err);
    }
    setTimeout(tick, 3000);
  };
  tick();
}

async function refreshVersions() {
  try {
    const res = await fetch(`/api/sessions/${getSid()}`);
    if (res.ok) showVersions((await res.json()).versions);
  } catch (err) {
    console.error("Failed to refresh versions:", err);
  }
}

async function updateVideo() {
  const v = currentVersion();
  if (!v) return;
  const res = await fetch(`/api/sessions/${getSid()}/update`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: v.id })
  });
  const data = await res.json().catch(() => ({}));
  if (res.ok) window.location.href = `/jobs/${data.job_id}`;
  else alert(data.detail || "Failed");
}

async function deleteVersion() {
  const v = currentVersion();
  if (!v || v.id === "v1") return;
  if (!confirm(tr("confirm_delete_version", "Delete this version? Its files move to data/trash."))) return;
  const res = await fetch(`/api/sessions/${getSid()}/versions/${v.id}`, { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  if (res.ok) showVersions(data.versions.map(x => ({ ...x, has_nocaps: true, has_program: true })), "v1");
  else alert(data.detail || "Failed");
  refreshVersions();
}

function showJobNotice(job) {
  const box = document.getElementById("jobNotice");
  if (!box) return;
  if (job && (job.status === "queued" || job.status === "running")) {
    const kinds = { finish: tr("job_kind_finish", "Updating the video"), publish: tr("job_kind_publish", "Making the publish kit"),
                    language: tr("job_kind_language", "Video with one caption language"),
                    thumbnails: tr("job_kind_thumbnails", "Thumbnails"), trailer: tr("job_kind_trailer", "Trailer") };
    const kind = kinds[job.kind] || tr("status_running", "Processing");
    document.getElementById("jobNoticeText").textContent = `${kind} · ${job.progress || 0}%`;
    document.getElementById("jobNoticeLink").href = `/jobs/${job.id}`;
    box.style.display = "flex";
  } else {
    box.style.display = "none";
  }
}

// ---------- timeline ----------

function renderTimelineChart(tl) {
  const ctx = document.getElementById("timelineChart");
  if (!ctx || typeof Chart === "undefined") return;

  const datasets = Object.entries(tl.scores || {}).map(([cam, scores]) => ({
    label: `Camera ${cam}`,
    data: scores,
    borderColor: CAM_COLORS[cam] || "#888",
    backgroundColor: CAM_COLORS[cam] || "#888",
    borderWidth: 1.8,
    pointRadius: 0,
    tension: 0.15
  }));

  if (chartInstance) chartInstance.destroy();

  chartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: tl.t || [],
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: {
        mode: "index",
        intersect: false
      },
      plugins: {
        legend: {
          labels: { color: "#cacdd2", font: { size: 11 } }
        },
        tooltip: {
          backgroundColor: "rgba(12, 15, 23, 0.9)",
          titleColor: "#ef8a2c",
          bodyColor: "#cacdd2",
          borderColor: "#1b2130",
          borderWidth: 1
        }
      },
      scales: {
        x: {
          ticks: { color: "#7c8089", maxTicksLimit: 12 },
          grid: { color: "rgba(255, 255, 255, 0.05)" }
        },
        y: {
          ticks: { color: "#7c8089" },
          grid: { color: "rgba(255, 255, 255, 0.05)" }
        }
      },
      onClick: (e, els, chart) => {
        if (!tl.t || !player) return;
        const xVal = chart.scales.x.getValueForPixel(e.x);
        if (xVal !== undefined && tl.t[xVal] !== undefined) {
          seekTo(tl.t[xVal]);
        }
      }
    }
  });
}

// on-air strip: one block per shot from the cut list, sized by its length
function renderOnAirStrip(tl, cuts) {
  const strip = document.getElementById("onAirStrip");
  if (!strip) return;
  strip.innerHTML = "";

  let shots = (cuts || []).filter(c => c.end > c.start);
  if (shots.length === 0 && tl.on_air) {            // no cuts.json: rebuild the shots from the timeline
    const times = tl.t || [];
    tl.on_air.forEach((cam, i) => {
      const t0 = times[i] !== undefined ? times[i] : i;
      const next = times[i + 1] !== undefined ? times[i + 1] : t0 + 0.1;
      const last = shots[shots.length - 1];
      if (last && last.cam === cam) last.end = next;
      else shots.push({ start: t0, end: next, cam: cam });
    });
  }

  shots.forEach(c => {
    const block = document.createElement("div");
    block.className = "strip-block";
    block.style.flex = `${c.end - c.start} 1 0`;
    if (Array.isArray(c.split)) {
      block.classList.add("strip-split");
      block.title = `${c.start.toFixed(1)}–${c.end.toFixed(1)}s: Split Screen (Cams ${c.split.join("+")})`;
      const splitLegend = document.getElementById("splitLegend");
      if (splitLegend) splitLegend.style.display = "inline";
    } else {
      block.classList.add(`strip-cam${c.cam}`);
      block.title = `${c.start.toFixed(1)}–${c.end.toFixed(1)}s: Camera ${c.cam}`;
    }
    const why = whyData.find(w => Math.abs(w.start - c.start) < 0.05);
    if (why) {
      const reason = getLang() === "ar" ? why.ar : why.en;
      block.title += ` · ${reason}`;
      block.onmouseenter = () => showWhy(c, reason);
    }
    block.onclick = () => {
      seekTo(c.start);
      if (why) showWhy(c, getLang() === "ar" ? why.ar : why.en);
    };
    strip.appendChild(block);
  });
}

function mmss(t) {
  const m = Math.floor(t / 60), s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function showWhy(c, reason) {
  const box = document.getElementById("whyBox");
  if (!box) return;
  const cam = Array.isArray(c.split) ? `${tr("split_screen", "Split screen")} ${c.split.join("+")}` : `${tr("camera", "Camera")} ${c.cam}`;
  box.innerHTML = `<span class="chip"><bdi>${mmss(c.start)}–${mmss(c.end)} · ${escapeHtml(cam)}</bdi></span> <span dir="auto">${escapeHtml(reason)}</span>`;
}

function renderModeStrip(tl) {
  const strip = document.getElementById("modeStrip");
  if (!strip || !tl.mode) return;
  strip.innerHTML = "";

  const runs = [];
  tl.mode.forEach(m => {
    const last = runs[runs.length - 1];
    if (last && last.mode === m) last.n += 1;
    else runs.push({ mode: m, n: 1 });
  });
  runs.forEach(r => {
    const block = document.createElement("div");
    block.className = `mode-block mode-${r.mode}`;
    block.style.flex = `${r.n} 1 0`;
    block.title = `Mode: ${r.mode}`;
    strip.appendChild(block);
  });
}

// ---------- speakers (names typed here = name cards) ----------

function renderSpeakers(speakersList) {
  const container = document.getElementById("speakersContainer");
  if (!container) return;
  container.innerHTML = "";

  speakersList.forEach(spk => {
    currentSpeakers[spk.speaker] = spk.name || "";
    const card = document.createElement("div");
    card.className = "speaker-card";
    const camNum = speakerMap[spk.speaker] || 1;
    const badge = spk.name_source === "user" ? ` · ${tr("name_card_on", "name card")}` : "";
    card.innerHTML = `
      <div class="speaker-avatar">${escapeHtml((spk.name || spk.speaker).charAt(0).toUpperCase())}</div>
      <div class="speaker-info">
        <span class="chip chip-cam${camNum}" style="margin-bottom: 4px;">${escapeHtml(spk.role || "Speaker")}${escapeHtml(badge)}</span>
        <input type="text" class="speaker-name-input" value="${escapeHtml(spk.name || "")}" placeholder="${escapeHtml(spk.speaker)}" data-spk-id="${escapeHtml(spk.speaker)}" dir="auto">
        <div style="font-size: 0.78rem; color: var(--text-quiet); margin-top: 4px;">${escapeHtml(spk.description || "")}</div>
      </div>
    `;
    container.appendChild(card);
  });
}

async function saveSpeakerNames() {
  const sid = getSid();
  const btn = document.getElementById("saveSpeakersBtn");
  const updates = {};
  document.querySelectorAll(".speaker-name-input").forEach(input => {
    const id = input.getAttribute("data-spk-id");
    const name = input.value.trim();
    if (id && name !== id && name !== currentSpeakers[id]) updates[id] = name;   // changed (also: emptied)
  });
  if (Object.keys(updates).length === 0) return;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳...";
  }

  try {
    const res = await fetch(`/api/sessions/${sid}/speakers`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ speakers: updates })
    });
    if (res.ok) {
      Object.assign(currentSpeakers, updates);
      if (btn) {
        btn.textContent = "✓ " + tr("saved_update_hint", "Saved: press Update video");
        setTimeout(() => {
          btn.textContent = tr("btn_save_names", "Save Names");
          btn.disabled = false;
        }, 2500);
      }
    } else {
      alert("Failed to save speaker names");
      if (btn) btn.disabled = false;
    }
  } catch (err) {
    alert("Network error: " + err);
    if (btn) btn.disabled = false;
  }
}

// ---------- highlights + the agent's clips ----------

function renderHighlights(highlightsList) {
  const sid = getSid();
  const container = document.getElementById("highlightsContainer");
  if (!container) return;
  container.innerHTML = "";

  highlightsList.forEach((h, idx) => {
    const card = document.createElement("div");
    card.className = "highlight-card";

    const file169 = (h.files && h.files["16:9"]) || "";
    const file916 = (h.files && h.files["9:16"]) || "";

    const dl169Html = file169 ? `<a href="/files/${sid}/${file169}" download class="btn btn-secondary btn-sm">⬇ 16:9</a>` : "";
    const dl916Html = file916 ? `<a href="/files/${sid}/${file916}" download class="btn btn-secondary btn-sm">⬇ 9:16</a>` : "";

    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
        <div>
          <h4 style="color: var(--text-bright); font-size: 1.05rem;" dir="auto">${escapeHtml(h.title_ar || h.title || "")}</h4>
          <div style="color: var(--text-quiet); font-size: 0.85rem;" dir="auto">${escapeHtml(h.title_en || "")}</div>
        </div>
        <span class="chip" style="font-family: var(--font-mono); font-size: 0.75rem;">#${idx + 1}</span>
      </div>

      <p style="color: var(--accent-orange); font-size: 0.85rem; margin: 8px 0;" dir="auto">${escapeHtml(h.hook || "")}</p>

      <div class="highlight-players">
        ${file169 ? `<div>
          <video class="highlight-video-169" controls preload="metadata" src="/files/${sid}/${file169}"></video>
          <div style="font-size: 0.75rem; color: var(--text-quiet); margin-top: 4px;">${tr("aspect_169", "16:9")}</div>
        </div>` : ""}
        ${file916 ? `<div>
          <video class="highlight-video-916" controls preload="metadata" src="/files/${sid}/${file916}"></video>
          <div style="font-size: 0.75rem; color: var(--text-quiet); margin-top: 4px;">${tr("aspect_916", "9:16")}</div>
        </div>` : ""}
      </div>

      <div style="display: flex; gap: 8px; margin-top: auto; padding-top: 10px; border-top: 1px solid var(--border-color); flex-wrap: wrap;">
        ${dl169Html}
        ${dl916Html}
      </div>
    `;
    container.appendChild(card);
  });
}

function captionsLabel(c) {
  return !c || c === "none" ? tr("clip_no_captions", "no captions") : `${tr("clip_captions", "captions")}: ${c.toUpperCase()}`;
}

function renderClips(clips) {
  lastClips = clips;
  const sid = getSid();
  const card = document.getElementById("clipsCard");
  const list = document.getElementById("clipsList");
  if (!card || !list) return;
  card.style.display = clips.length ? "block" : "none";
  list.innerHTML = "";
  clips.slice().reverse().forEach(c => {                       // newest first
    const row = document.createElement("div");
    row.className = "clip-row";
    const secs = c.end > c.start ? `${Math.round(c.end - c.start)} s` : "";
    const parent = c.parent ? `<span class="chip">${escapeHtml(tr("made_from", "made from {id}", { id: c.parent }))}</span>` : "";
    row.innerHTML = `
      <div style="flex: 1; min-width: 0;">
        <div style="color: var(--text-bright); font-weight: 600;" dir="auto">${escapeHtml(c.title || c.id)}</div>
        <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px;">
          <span class="chip"><bdi>${escapeHtml(c.id)}</bdi></span>
          <span class="chip"><bdi>${escapeHtml(c.format || "16:9")} · ${secs}</bdi></span>
          <span class="chip">${escapeHtml(captionsLabel(c.captions))}</span>
          ${parent}
        </div>
      </div>
      <a href="/files/${sid}/${c.file}" target="_blank" class="btn btn-secondary btn-sm">▶</a>
      <a href="/files/${sid}/${c.file}" download class="btn btn-secondary btn-sm">⬇</a>`;
    list.appendChild(row);
  });
}

// ---------- publish kit ----------

function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    if (!btn) return;
    const old = btn.textContent;
    btn.textContent = "✓";
    setTimeout(() => { btn.textContent = old; }, 1200);
  });
}

function showPublish(lang) {
  publishLang = lang;
  document.querySelectorAll(".lang-tab").forEach(b => b.classList.toggle("btn-primary", b.dataset.lang === lang));
  const box = document.getElementById("publishBox");
  const btn = document.getElementById("makePublishBtn");
  if (!box) return;
  box.innerHTML = "";
  if (btn) btn.textContent = publishData ? tr("btn_remake_publish", "Make again") : tr("btn_make_publish", "Make publish kit");
  if (!publishData) {
    box.innerHTML = `<p class="form-hint">${escapeHtml(tr("publish_none", "No publish kit yet."))}</p>`;
    return;
  }
  const dir = lang === "ar" ? "rtl" : "ltr";
  const v = currentVersion();
  const desc = (v && v.descriptions && v.descriptions[lang]) || publishData[`description_${lang}`] || "";
  const block = document.createElement("div");
  block.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
      <strong style="color: var(--text-bright);">${escapeHtml(tr("publish_youtube", "YouTube description"))}</strong>
      <button class="btn btn-secondary btn-sm" data-copy="desc">${escapeHtml(tr("btn_copy", "Copy"))}</button>
    </div>
    <textarea class="form-control publish-text" readonly dir="${dir}" rows="10">${escapeHtml(desc)}</textarea>`;
  box.appendChild(block);
  block.querySelector("[data-copy]").onclick = e => copyText(desc, e.target);

  (publishData.posts || []).forEach(p => {
    const text = `${p[`text_${lang}`] || ""}\n${(p.hashtags || []).join(" ")}`.trim();
    const row = document.createElement("div");
    row.className = "post-row";
    row.innerHTML = `
      <span class="chip"><bdi>${escapeHtml(p.highlight)}</bdi></span>
      <div style="flex: 1; white-space: pre-wrap;" dir="${dir}">${escapeHtml(text)}</div>
      <button class="btn btn-secondary btn-sm">${escapeHtml(tr("btn_copy", "Copy"))}</button>`;
    row.querySelector("button").onclick = e => copyText(text, e.target);
    box.appendChild(row);
  });

  const article = publishData[`article_${lang}`] || "";             // the blog article (Markdown)
  const art = document.createElement("div");
  art.style.marginTop = "18px";
  art.innerHTML = article ? `
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 8px;">
      <strong style="color: var(--text-bright);">${escapeHtml(tr("publish_article", "Article"))}</strong>
      <div style="display: flex; gap: 6px;">
        <button class="btn btn-secondary btn-sm" data-copy="article">${escapeHtml(tr("btn_copy", "Copy"))}</button>
        <a class="btn btn-secondary btn-sm" href="/api/sessions/${getSid()}/article.md?lang=${lang}" download>⬇ .md</a>
      </div>
    </div>
    <textarea class="form-control publish-text" readonly dir="${dir}" rows="14">${escapeHtml(article)}</textarea>`
    : `<p class="form-hint">${escapeHtml(tr("article_none", "No article yet: press Make again to write one."))}</p>`;
  box.appendChild(art);
  const copyBtn = art.querySelector("[data-copy]");
  if (copyBtn) copyBtn.onclick = e => copyText(article, e.target);
}

async function makePublish() {
  const res = await fetch(`/api/sessions/${getSid()}/publish`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (res.ok) window.location.href = `/jobs/${data.job_id}`;
  else alert(data.detail || "Failed");
}

// ---------- brand kit ----------

async function saveBrand() {
  const form = readBrandForm();
  const fd = new FormData();
  fd.append("settings", JSON.stringify(form.settings));
  fd.append("remove", form.remove.join(","));
  ["logo", "intro", "outro", "music"].forEach(k => { if (form[k]) fd.append(k, form[k]); });
  const btn = document.getElementById("saveBrandBtn");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`/api/sessions/${getSid()}/brand`, { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      alert(data.detail || "Failed to save the brand kit");
      return;
    }
    ["brandLogo", "brandIntro", "brandOutro", "brandMusic"].forEach(id => { document.getElementById(id).value = ""; });
    fillBrandForm(data);
    if (btn) {
      btn.textContent = "✓ " + tr("saved_update_hint", "Saved: press Update video");
      setTimeout(() => { btn.textContent = tr("btn_save_brand", "Save brand kit"); }, 2500);
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ---------- metrics ----------

function renderMetrics(metrics) {
  const card = document.getElementById("metricsCard");
  const grid = document.getElementById("metricsGrid");
  if (!card || !grid) return;
  card.style.display = "block";
  grid.innerHTML = "";

  let agreementVal = "N/A";
  const ag = metrics.agreement ?? metrics.director?.ai?.agreement;
  if (ag !== undefined && ag !== null) {
    agreementVal = `${(ag * 100).toFixed(1)}%`;
  }

  let runtimeVal = "N/A";
  if (metrics.runtime) {
    runtimeVal = `${metrics.runtime}s`;
  } else if (metrics.processing_seconds && typeof metrics.processing_seconds === "object") {
    const total = Object.values(metrics.processing_seconds).reduce((a, b) => a + Number(b || 0), 0);
    runtimeVal = `${total.toFixed(0)}s`;
  }

  let spkCoverage = "N/A";
  const sc = metrics.speaker_coverage ?? metrics.director?.ai?.speaker_coverage;
  if (sc !== undefined && sc !== null) {
    spkCoverage = `${(sc * 100).toFixed(1)}%`;
  }

  const items = [
    { label: "Director Agreement", val: agreementVal },
    { label: "Speaker Coverage", val: spkCoverage },
    { label: "Total Processing Time", val: runtimeVal }
  ];

  items.forEach(it => {
    const el = document.createElement("div");
    el.style.background = "var(--bg-surface-elevated)";
    el.style.padding = "14px";
    el.style.borderRadius = "var(--radius-md)";
    el.style.border = "1px solid var(--border-color)";
    el.innerHTML = `
      <div style="font-size: 0.8rem; color: var(--text-quiet);">${it.label}</div>
      <div style="font-size: 1.3rem; font-weight: 700; color: var(--accent-orange); font-family: var(--font-mono); margin-top: 4px;">${it.val}</div>
    `;
    grid.appendChild(el);
  });
}

// ---------- Editor Agent chat ----------

async function loadChatHistory() {
  const sid = getSid();
  const chatMessages = document.getElementById("chatMessages");
  if (!sid || !chatMessages) return;

  try {
    const res = await fetch(`/api/agent/${sid}/messages`);
    if (!res.ok) return;
    const msgs = await res.json();
    chatMessages.innerHTML = "";
    msgs.forEach(m => {
      appendBubble(m.role, m.content, m.steps, false);
      (m.clips || []).forEach(c => appendClipBubble(c, false));
    });
    chatMessages.scrollTop = chatMessages.scrollHeight;
  } catch (err) {
    console.error("Failed to load chat history:", err);
  }
}

function appendBubble(role, content, steps = [], scroll = true) {
  const chatMessages = document.getElementById("chatMessages");
  if (!chatMessages) return null;

  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  bubble.setAttribute("dir", "auto");

  let html = "";
  if (steps && steps.length > 0) {
    html += `<div class="chat-steps">`;
    steps.forEach(s => {
      html += `<div class="chat-step-item">🔧 ${escapeHtml(s.tool || "")} — ${escapeHtml(s.summary || "")}</div>`;
    });
    html += `</div>`;
  }

  html += `<div>${escapeHtml(content || "")}</div>`;
  bubble.innerHTML = html;
  chatMessages.appendChild(bubble);

  if (scroll) {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }
  return bubble;
}

function appendClipBubble(clip, scroll = true) {
  const sid = getSid();
  const chatMessages = document.getElementById("chatMessages");
  if (!chatMessages || !clip.file) return;

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble assistant";
  const secs = clip.end > clip.start ? ` · ${Math.round(clip.end - clip.start)} s` : "";
  const parent = clip.parent ? ` · ${tr("made_from", "made from {id}", { id: clip.parent })}` : "";
  bubble.innerHTML = `
    <div class="clip-card-bubble">
      <div style="font-weight: 600; color: var(--text-bright); margin-bottom: 6px;">${escapeHtml(clip.title || "Custom Clip")}</div>
      <video controls style="width: 100%; border-radius: var(--radius-sm);" src="/files/${sid}/${clip.file}"></video>
      <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; gap: 8px;">
        <span class="chip" style="font-size: 0.72rem;"><bdi>${escapeHtml(clip.format || "16:9")}${secs} &middot; ${escapeHtml(captionsLabel(clip.captions))}${escapeHtml(parent)}</bdi></span>
        <a href="/files/${sid}/${clip.file}" download class="btn btn-secondary btn-sm">⬇ Download</a>
      </div>
    </div>
  `;
  chatMessages.appendChild(bubble);
  if (scroll) chatMessages.scrollTop = chatMessages.scrollHeight;
}

function useChip(text) {
  text = (text || "").trim();
  const chatInput = document.getElementById("chatInput");
  if (chatInput) {
    chatInput.value = text;
    chatInput.focus();
  }
}

async function deleteThisProject() {
  const sid = getSid();
  const msg = tr("confirm_delete", "Delete project?");
  if (!confirm(msg)) return;
  try {
    const res = await fetch(`/api/projects/${sid}`, { method: "DELETE" });
    if (res.ok) {
      window.location.href = "/";
    } else {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || "Failed to delete project");
    }
  } catch (e) {
    alert("Network error: " + e);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[m]));
}

// the language switch: redraw the parts this script wrote
document.addEventListener("framepilot:lang", e => {
  if (versions.length) showVersions(versions);
  renderClips(lastClips);
  if (publishLang !== null) showPublish(e.detail);
  if (lastData) {
    renderStats(lastData.stats);
    renderTrailer(lastData.trailer);
    renderThumbnails(lastData.thumbnails);
  }
});

document.addEventListener("DOMContentLoaded", () => {
  player = document.getElementById("mainPlayer");
  loadSession();
  loadChatHistory();

  const sel = document.getElementById("videoVersionSelect");
  if (sel) sel.addEventListener("change", e => selectVersion(e.target.value));
  const searchForm = document.getElementById("searchForm");
  if (searchForm) searchForm.addEventListener("submit", e => { e.preventDefault(); searchVideo("words"); });

  const chatForm = document.getElementById("chatForm");
  const chatInput = document.getElementById("chatInput");
  const chatSendBtn = document.getElementById("chatSendBtn");

  if (chatForm && chatInput) {
    chatForm.addEventListener("submit", async e => {
      e.preventDefault();
      const text = chatInput.value.trim();
      if (!text) return;

      const sid = getSid();
      chatInput.value = "";
      appendBubble("user", text);

      const workingBubble = appendBubble("assistant", tr("agent_working", "Working on your request..."));
      if (chatSendBtn) chatSendBtn.disabled = true;

      try {
        const res = await fetch(`/api/agent/${sid}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text })
        });

        if (res.status === 409) {
          workingBubble.textContent = tr("agent_status_busy", "GPU is busy with a video. Please wait...");
          return;
        }

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          workingBubble.textContent = err.detail || tr("agent_error", "The Editor Agent failed.");
          return;
        }

        const data = await res.json();
        workingBubble.remove();

        appendBubble("assistant", data.reply, data.steps);
        (data.clips || []).forEach(c => appendClipBubble(c));
        if ((data.clips || []).length) refreshClips();
        if ((data.steps || []).some(st => st.tool === "restyle_video")) refreshVersions();

      } catch (err) {
        workingBubble.textContent = "Network error: " + err;
      } finally {
        if (chatSendBtn) chatSendBtn.disabled = false;
      }
    });
  }
});

async function refreshClips() {
  try {
    const res = await fetch(`/api/sessions/${getSid()}`);
    if (res.ok) renderClips((await res.json()).clips || []);
  } catch (err) {
    console.error("Failed to refresh clips:", err);
  }
}

// ---------- search inside the video ----------

async function searchVideo(mode) {
  const input = document.getElementById("searchInput");
  const box = document.getElementById("searchResults");
  const q = input ? input.value.trim() : "";
  if (!q || !box) return;
  box.innerHTML = `<p class="form-hint">⏳ ${escapeHtml(mode === "meaning" ? tr("search_meaning_wait", "Searching by meaning (the first time takes a few seconds)...") : tr("searching", "Searching..."))}</p>`;
  try {
    const res = await fetch(`/api/sessions/${getSid()}/search?mode=${mode}&q=${encodeURIComponent(q)}`);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      box.innerHTML = `<p class="form-hint">${escapeHtml(data.detail || "Failed")}</p>`;
      return;
    }
    const results = data.results || [];
    box.innerHTML = results.length ? "" : `<p class="form-hint">${escapeHtml(tr("search_none", "Nothing found. Try another word, or search by meaning."))}</p>`;
    if (results.length) {
      const n = document.createElement("p");
      n.className = "form-hint";
      n.textContent = tr("search_found", "{n} moments · click one to watch it", { n: results.length });
      box.appendChild(n);
    }
    results.forEach(r => {
      const row = document.createElement("div");
      row.className = "search-row";
      row.innerHTML = `
        <span class="chip search-time"><bdi>${mmss(r.start)}</bdi></span>
        <div style="flex: 1; min-width: 0;">
          <div class="search-who">${escapeHtml(speakerNames[r.speaker] || r.speaker || "")}</div>
          <div dir="auto">${escapeHtml(r.text || "")}</div>
          ${r.translation ? `<div dir="auto" class="search-tr">${escapeHtml(r.translation)}</div>` : ""}
        </div>`;
      row.onclick = () => { seekTo(r.start); if (player) player.play(); };
      box.appendChild(row);
    });
  } catch (err) {
    box.innerHTML = `<p class="form-hint">Network error: ${escapeHtml(String(err))}</p>`;
  }
}

// ---------- speaker stats ----------

function renderStats(st) {
  const card = document.getElementById("statsCard");
  if (!card) return;
  if (!st || !st.people || !st.people.length) {
    card.style.display = "none";
    return;
  }
  card.style.display = "block";
  document.getElementById("statsSummary").textContent = tr("stats_summary",
    "Talking {talk}% of the video · {changes} speaker changes per minute", { talk: st.talk_share, changes: st.changes_per_min });
  const box = document.getElementById("statsPeople");
  box.innerHTML = "";
  st.people.forEach(p => {
    const cam = speakerMap[p.speaker] || 1;
    const row = document.createElement("div");
    row.className = "stat-row";
    row.innerHTML = `
      <div class="stat-head">
        <strong dir="auto">${escapeHtml(speakerNames[p.speaker] || p.speaker)}</strong>
        <span class="stat-share">${p.share}%</span>
      </div>
      <div class="stat-bar"><div class="stat-fill strip-cam${cam}" style="width: ${Math.max(p.share, 1)}%;"></div></div>
      <div class="stat-facts">
        <span class="chip"><bdi>${mmss(p.seconds)}</bdi> ${escapeHtml(tr("stats_talk", "talking"))}</span>
        <span class="chip"><bdi>${p.turns}</bdi> ${escapeHtml(tr("stats_turns", "turns"))}</span>
        <button class="chip chip-link" title="${escapeHtml(tr("stats_jump", "Watch it"))}"><bdi>${p.longest.seconds}</bdi> ${escapeHtml(tr("stats_longest", "s longest answer"))} ▶</button>
        <span class="chip"><bdi>${p.wpm}</bdi> ${escapeHtml(tr("stats_wpm", "words / min"))}</span>
        <span class="chip"><bdi>${p.jumped_in}</bdi> ${escapeHtml(tr("stats_jumped", "times jumped in"))}</span>
      </div>`;
    row.querySelector(".chip-link").onclick = () => { seekTo(p.longest.start); if (player) player.play(); };
    box.appendChild(row);
  });
  const laughs = document.getElementById("statsLaughs");
  laughs.innerHTML = "";
  if ((st.laughs || []).length) {
    const label = document.createElement("span");
    label.className = "form-hint";
    label.textContent = tr("stats_laughs", "Laughter:") + " ";
    laughs.appendChild(label);
    st.laughs.forEach(l => {
      const b = document.createElement("button");
      b.className = "chip chip-link";
      b.innerHTML = `😄 <bdi>${mmss(l.start)}</bdi>`;
      b.onclick = () => { seekTo(l.start); if (player) player.play(); };
      laughs.appendChild(b);
    });
  }
}

// ---------- trailer + thumbnails ----------

function renderTrailer(t) {
  const box = document.getElementById("trailerBox");
  const btn = document.getElementById("makeTrailerBtn");
  if (!box) return;
  if (btn) btn.textContent = t ? tr("btn_remake_trailer", "Make again") : tr("btn_make_trailer", "Make trailer");
  if (!t || !t.files) {
    box.innerHTML = `<p class="form-hint">${escapeHtml(tr("trailer_none", "No trailer yet."))}</p>`;
    return;
  }
  const sid = getSid();
  const stamp = Date.now();                                    // a remade trailer: no old copy from the browser cache
  const title = getLang() === "ar" ? t.title_ar : t.title_en;
  const secs = (t.moments || []).reduce((a, m) => a + m.end - m.start, 0);
  box.innerHTML = `
    <div style="color: var(--text-bright); font-weight: 600; margin-bottom: 8px;" dir="auto">${escapeHtml(title || "")}
      <span class="chip">${escapeHtml(tr("trailer_meta", "{n} moments · {s} s", { n: (t.moments || []).length, s: Math.round(secs) }))}</span></div>
    <div class="highlight-players">
      ${t.files["16:9"] ? `<div><video class="highlight-video-169" controls preload="metadata" src="/files/${sid}/${t.files["16:9"]}?t=${stamp}"></video>
        <a href="/files/${sid}/${t.files["16:9"]}" download class="btn btn-secondary btn-sm" style="margin-top: 6px;">⬇ 16:9</a></div>` : ""}
      ${t.files["9:16"] ? `<div><video class="highlight-video-916" controls preload="metadata" src="/files/${sid}/${t.files["9:16"]}?t=${stamp}"></video>
        <a href="/files/${sid}/${t.files["9:16"]}" download class="btn btn-secondary btn-sm" style="margin-top: 6px;">⬇ 9:16</a></div>` : ""}
    </div>`;
}

function renderThumbnails(items) {
  const box = document.getElementById("thumbsBox");
  const btn = document.getElementById("makeThumbsBtn");
  if (!box) return;
  if (btn) btn.textContent = (items || []).length ? tr("btn_remake_thumbs", "Make again") : tr("btn_make_thumbs", "Make thumbnails");
  box.innerHTML = (items || []).length ? "" : `<p class="form-hint">${escapeHtml(tr("thumbs_none", "No thumbnails yet."))}</p>`;
  const sid = getSid();
  const stamp = Date.now();
  const lang = getLang() === "ar" ? "ar" : "en";
  (items || []).forEach(it => {
    const div = document.createElement("div");
    div.className = "thumb-card";
    div.innerHTML = `
      <img src="/files/${sid}/${it.files[lang] || it.files.ar}?t=${stamp}" alt="Thumbnail ${it.n}" loading="lazy">
      <div style="display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap;">
        <a href="/files/${sid}/${it.files.ar}" download class="btn btn-secondary btn-sm">⬇ عربي</a>
        <a href="/files/${sid}/${it.files.en}" download class="btn btn-secondary btn-sm">⬇ English</a>
        <button class="btn btn-secondary btn-sm">▶ <bdi>${mmss(it.t)}</bdi></button>
      </div>`;
    div.querySelector("button").onclick = () => seekTo(it.t);
    box.appendChild(div);
  });
}

async function startJob(path) {
  const res = await fetch(`/api/sessions/${getSid()}/${path}`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (res.ok) window.location.href = `/jobs/${data.job_id}`;
  else alert(data.detail || "Failed");
}

function makeTrailer() { startJob("trailer"); }
function makeThumbnails() { startJob("thumbnails"); }
