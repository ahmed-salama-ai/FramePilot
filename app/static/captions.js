// FramePilot - Caption Editor: fix the words of every caption line (transcript.json rows)

let capRows = [];               // the rows as saved: [{id, start, end, speaker, text, translation}]
const capEdits = new Map();     // id -> {text, translation} the user changed and has not saved yet
let capLanguage = "ar";
let capSpeakers = {};

const ctr = (key, fallback, vars) => (typeof t === "function" ? t(key, vars) : fallback);
const capSid = () => document.getElementById("capMeta").dataset.sid;

function capEscape(s) {
  return String(s ?? "").replace(/[&<>"']/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
}

function mmss(t) {
  const m = Math.floor(t / 60), s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

async function loadCaptions() {
  const res = await fetch(`/api/sessions/${capSid()}/transcript`);
  const box = document.getElementById("capRows");
  if (!res.ok) {
    box.innerHTML = `<p class="form-hint">${capEscape(ctr("captions_none", "No transcript yet."))}</p>`;
    return;
  }
  const data = await res.json();
  capRows = data.rows;
  capLanguage = data.language;
  capSpeakers = data.speakers || {};
  capEdits.clear();
  document.getElementById("undoBtn").disabled = !data.saves;
  document.getElementById("restoreBtn").disabled = !data.has_original;
  renderRows();
  updateSaveBar();
}

function renderRows() {
  const box = document.getElementById("capRows");
  const q = (document.getElementById("capSearch").value || "").trim().toLowerCase();
  const said = capLanguage === "ar" ? ctr("col_said_ar", "Said (Arabic)") : ctr("col_said_en", "Said (English)");
  const trans = capLanguage === "ar" ? ctr("col_trans_en", "Translation (English)") : ctr("col_trans_ar", "Translation (Arabic)");
  box.innerHTML = "";
  capRows.forEach(r => {
    const e = capEdits.get(r.id) || {};
    const text = e.text ?? r.text, translation = e.translation ?? r.translation ?? "";
    if (q && !`${text} ${translation}`.toLowerCase().includes(q)) return;
    const row = document.createElement("div");
    row.className = "caption-row" + (capEdits.has(r.id) ? " changed" : "");
    row.dataset.id = r.id;
    row.dataset.start = r.start;
    row.dataset.end = r.end;
    row.innerHTML = `
      <div class="caption-row-head">
        <button class="btn btn-secondary btn-sm cap-time" title="▶"><bdi>${mmss(r.start)}</bdi></button>
        <span class="chip" dir="auto">${capEscape(capSpeakers[r.speaker] || r.speaker || "")}</span>
      </div>
      <label class="cap-label">${capEscape(said)}</label>
      <textarea class="form-control cap-text" rows="1" dir="auto">${capEscape(text)}</textarea>
      <label class="cap-label">${capEscape(trans)}</label>
      <textarea class="form-control cap-trans" rows="1" dir="auto">${capEscape(translation)}</textarea>`;
    row.querySelector(".cap-time").onclick = () => {
      const p = document.getElementById("capPlayer");
      p.currentTime = r.start;
      p.play();
    };
    const onEdit = () => {
      const newText = row.querySelector(".cap-text").value;
      const newTrans = row.querySelector(".cap-trans").value;
      if (newText.trim() === r.text && newTrans.trim() === (r.translation || "")) capEdits.delete(r.id);
      else capEdits.set(r.id, { text: newText, translation: newTrans });
      row.classList.toggle("changed", capEdits.has(r.id));
      updateSaveBar();
    };
    row.querySelector(".cap-text").addEventListener("input", onEdit);
    row.querySelector(".cap-trans").addEventListener("input", onEdit);
    box.appendChild(row);
  });
}

function updateSaveBar() {
  const n = capEdits.size;
  document.getElementById("changedCount").textContent = n ? ctr("captions_changed", "{n} lines changed", { n }) : "";
  document.getElementById("saveCapsBtn").disabled = n === 0;
}

function reloadTrack() {
  const track = document.getElementById("capTrack");
  track.src = `/files/${capSid()}/captions.vtt?v=${Date.now()}`;      // the player reads the new captions
}

async function saveCaptions() {
  const rows = [...capEdits.entries()].map(([id, e]) => ({ id, text: e.text, translation: e.translation }));
  if (!rows.length) return;
  const btn = document.getElementById("saveCapsBtn");
  btn.disabled = true;
  const res = await fetch(`/api/sessions/${capSid()}/transcript`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows })
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    alert(data.detail || "Failed to save");
    btn.disabled = false;
    return;
  }
  reloadTrack();
  await loadCaptions();
  document.getElementById("changedCount").textContent = "✓ " + ctr("saved_update_hint", "Saved: press Update video");
}

async function undoSave() {
  if (capEdits.size && !confirm(ctr("confirm_drop_edits", "Your unsaved changes will be lost. Continue?"))) return;
  const res = await fetch(`/api/sessions/${capSid()}/transcript/undo`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) alert(data.detail || "Failed");
  reloadTrack();
  loadCaptions();
}

async function restoreOriginal() {
  if (!confirm(ctr("confirm_restore", "Go back to the captions as the AI made them? (You can undo this.)"))) return;
  const res = await fetch(`/api/sessions/${capSid()}/transcript/restore`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) alert(data.detail || "Failed");
  reloadTrack();
  loadCaptions();
}

async function updateVideo() {
  if (capEdits.size && !confirm(ctr("confirm_drop_edits", "Your unsaved changes will be lost. Continue?"))) return;
  const res = await fetch(`/api/sessions/${capSid()}/update`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: "latest" })
  });
  const data = await res.json().catch(() => ({}));
  if (res.ok) window.location.href = `/jobs/${data.job_id}`;
  else alert(data.detail || "Failed");
}

// the line being said is highlighted while the video plays
function followPlayer() {
  const p = document.getElementById("capPlayer");
  p.addEventListener("timeupdate", () => {
    const now = p.currentTime;
    document.querySelectorAll(".caption-row").forEach(row => {
      row.classList.toggle("playing", now >= +row.dataset.start && now < +row.dataset.end);
    });
  });
}

window.addEventListener("beforeunload", e => {
  if (capEdits.size) {
    e.preventDefault();
    e.returnValue = "";
  }
});

document.addEventListener("DOMContentLoaded", () => {
  loadCaptions();
  followPlayer();
  document.getElementById("capSearch").addEventListener("input", renderRows);
});
