// FramePilot - Multi-Camera Labelling Tool Logic

let master = null;
let vids = [];
let activeCamera = 1;
const changes = [];
const highlights = [];
let hStart = null;

function getSid() {
  const labelMeta = document.getElementById("labelMeta");
  return labelMeta ? labelMeta.dataset.sid : "";
}

function setActiveCameraVisual(camNum) {
  activeCamera = camNum;
  const badge = document.getElementById("activeCamBadge");
  if (badge) badge.textContent = `Cam ${camNum}`;

  document.querySelectorAll(".label-video-item").forEach(item => {
    item.classList.remove("active-cam1", "active-cam2", "active-cam3", "active-cam4");
  });

  const wrapper = document.getElementById(`camWrapper${camNum}`);
  if (wrapper) {
    wrapper.classList.add(`active-cam${camNum}`);
  }
}

function updateCutsLog() {
  const cutCount = document.getElementById("cutCountBadge");
  if (cutCount) cutCount.textContent = changes.length;
  const logContainer = document.getElementById("cutsLog");
  if (!logContainer) return;

  if (changes.length === 0) {
    logContainer.innerHTML = '<span style="color: var(--text-quiet);">لا توجد تبديلات مسجلة بعد.</span>';
    return;
  }

  logContainer.innerHTML = changes.map(([t, cam], idx) => `
    <span class="chip chip-cam${cam}" style="padding: 2px 8px;">
      #${idx + 1}: <bdi>${t.toFixed(1)}s</bdi> &rarr; Cam ${cam}
    </span>
  `).join("");
  logContainer.scrollTop = logContainer.scrollHeight;
}

async function saveLabels() {
  if (!master || !master.duration) {
    alert("Please play or load video to establish duration before saving.");
    return;
  }

  const sid = getSid();
  const btn = document.getElementById("saveLabelsBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ Saving...";
  }

  try {
    const res = await fetch(`/api/labels/${sid}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        changes: changes,
        highlights: highlights,
        duration: master.duration
      })
    });

    if (res.ok) {
      const data = await res.json();
      alert(`Ground truth labels saved successfully! (${data.saved} rows written to labels.csv)`);
      if (btn) {
        btn.textContent = "✓ Saved";
        setTimeout(() => {
          btn.textContent = typeof t === "function" ? t("btn_save_labels") : "Save Ground Truth Labels";
          btn.disabled = false;
        }, 2000);
      }
    } else {
      alert("Failed to save labels.");
      if (btn) btn.disabled = false;
    }
  } catch (err) {
    alert("Network error: " + err);
    if (btn) btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  vids = Array.from(document.querySelectorAll("#videoGrid video"));
  master = vids[0];

  if (master) {
    master.muted = false;
    master.controls = true;
    master.playbackRate = 0.75;

    master.onplay = () => vids.slice(1).forEach(v => v.play());
    master.onpause = () => vids.slice(1).forEach(v => v.pause());

    setInterval(() => {
      vids.slice(1).forEach(v => {
        v.playbackRate = master.playbackRate;
        if (Math.abs(v.currentTime - master.currentTime) > 0.15) {
          v.currentTime = master.currentTime;
        }
      });
    }, 400);
  }

  setActiveCameraVisual(1);

  document.addEventListener("keydown", e => {
    if (!master) return;
    const t = parseFloat(master.currentTime.toFixed(1));

    if ("1234".includes(e.key)) {
      const cam = parseInt(e.key, 10);
      changes.push([t, cam]);
      setActiveCameraVisual(cam);
      updateCutsLog();
    }

    if (e.key.toLowerCase() === "h") {
      const indicator = document.getElementById("highlightIndicator");
      if (hStart === null) {
        hStart = t;
        if (indicator) indicator.style.display = "block";
      } else {
        highlights.push([hStart, t, "key_point"]);
        hStart = null;
        if (indicator) indicator.style.display = "none";
      }
    }

    if (e.key === "Backspace" && changes.length > 0) {
      changes.pop();
      if (changes.length > 0) {
        setActiveCameraVisual(changes[changes.length - 1][1]);
      } else {
        setActiveCameraVisual(1);
      }
      updateCutsLog();
    }
  });
});
