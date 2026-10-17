// FramePilot - Processing Tracker Page Logic (stages, time estimate, "notify me when it's ready")

let startTime = Date.now();
let timerInterval = null;
let queuedPolls = 0;            // how many polls in a row found the job waiting with nobody ahead
let lastStatus = null;

const jtr = (key, fallback, vars) => (typeof t === "function" ? t(key, vars) : fallback);

function formatSeconds(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

// "about 12 min" / "less than a minute"
function roughTime(secs) {
  if (secs < 60) return jtr("eta_under_minute", "less than a minute");
  const min = Math.round(secs / 60);
  return jtr("eta_minutes", "about {n} min", { n: min });
}

function updateTimer() {
  const elapsed = (Date.now() - startTime) / 1000;
  const timerEl = document.getElementById("elapsedTimer");
  if (timerEl) {
    timerEl.textContent = formatSeconds(elapsed);
  }
}

function renderStages(stages, currentStage, status, report) {
  const container = document.getElementById("stagesContainer");
  if (!container) return;
  container.innerHTML = "";

  const reportMap = {};
  if (Array.isArray(report)) {
    report.forEach(item => {
      if (Array.isArray(item) && item.length >= 3) {
        reportMap[item[0]] = { status: item[1], time: item[2] };
      }
    });
  }

  const current = stages.indexOf(currentStage);
  stages.forEach((stageName, idx) => {
    const itemEl = document.createElement("div");
    itemEl.className = "stage-item";

    let stageStatus = "waiting";
    let statusText = jtr("job_stage_waiting", "Waiting");
    let extraInfo = "";

    if (reportMap[stageName]) {
      stageStatus = String(reportMap[stageName].status).startsWith("done") ? "done" : "waiting";
      statusText = String(reportMap[stageName].status).startsWith("done")
        ? `✓ ${jtr("job_stage_done", "Done")} ${String(reportMap[stageName].status).slice(4)}`
        : reportMap[stageName].status;
      extraInfo = `<bdi style="font-family: var(--font-mono); font-size: 0.8rem; color: var(--text-quiet);">${reportMap[stageName].time}s</bdi>`;
    } else if (status === "running" && stageName === currentStage) {
      stageStatus = "running";
      statusText = `<span class="spinner"></span> ${jtr("job_stage_running", "Running...")}`;
    } else if (status === "running" && current > idx) {
      stageStatus = "done";
      statusText = `✓ ${jtr("job_stage_done", "Done")}`;
    } else if (status === "done") {
      stageStatus = "done";
      statusText = `✓ ${jtr("job_stage_done", "Done")}`;
    } else if (status === "error" && stageName === currentStage) {
      stageStatus = "failed";
      statusText = `⚠ ${jtr("job_stage_failed", "Failed")}`;
    }

    itemEl.classList.add(stageStatus);
    itemEl.innerHTML = `
      <div class="stage-left">
        <div class="stage-number">${idx + 1}</div>
        <div>
          <div style="font-weight: 600; color: var(--text-bright);">${stageName}</div>
          <div style="font-size: 0.8rem; color: var(--text-quiet);">${statusText}</div>
        </div>
      </div>
      <div>${extraInfo}</div>
    `;
    container.appendChild(itemEl);
  });
}

// ---------- notification when the job ends ----------

function notifyWanted() {
  try { return localStorage.getItem("framepilot_notify") === "1"; } catch (e) { return false; }
}

function updateNotifyButton() {
  const btn = document.getElementById("notifyBtn");
  if (!btn) return;
  if (!("Notification" in window)) {
    btn.style.display = "none";
    return;
  }
  const on = notifyWanted() && Notification.permission === "granted";
  btn.textContent = on ? jtr("notify_on", "🔔 You will be notified") : jtr("notify_off", "🔔 Notify me when it's ready");
  btn.classList.toggle("btn-primary", on);
}

async function toggleNotify() {
  if (!("Notification" in window)) return;
  if (notifyWanted() && Notification.permission === "granted") {
    try { localStorage.setItem("framepilot_notify", "0"); } catch (e) { /* private window */ }
  } else {
    const p = await Notification.requestPermission();
    try { localStorage.setItem("framepilot_notify", p === "granted" ? "1" : "0"); } catch (e) { /* private window */ }
  }
  updateNotifyButton();
}

function notifyEnd(j) {
  const name = j.project_name || j.session_id;
  if (notifyWanted() && "Notification" in window && Notification.permission === "granted") {
    const ok = j.status === "done";
    const n = new Notification(ok ? jtr("notify_done_title", "FramePilot: ready ✓") : jtr("notify_error_title", "FramePilot: failed"), {
      body: name, icon: "/static/logo.jpeg", tag: `framepilot-job-${j.id}`
    });
    n.onclick = () => { window.focus(); n.close(); };
  }
}

// ---------- polling ----------

async function pollJob() {
  const jobMeta = document.getElementById("jobMeta");
  if (!jobMeta) return;
  const jobId = parseInt(jobMeta.dataset.jobId, 10);
  if (!jobId) return;

  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) return;
    const j = await res.json();

    const progressEl = document.getElementById("progressPercent");
    const barEl = document.getElementById("mainProgressBar");
    const stageEl = document.getElementById("currentStageText");
    const queueNotice = document.getElementById("queueNotice");
    const errorCard = document.getElementById("errorCard");
    const etaEl = document.getElementById("etaText");

    if (barEl) barEl.style.width = j.progress + "%";
    if (progressEl) progressEl.innerHTML = `<bdi>${j.progress}%</bdi>`;
    if (stageEl) stageEl.textContent = `${j.stage} · ${j.progress}%`;
    document.title = `${j.status === "done" ? "✓" : j.status === "error" ? "⚠" : j.progress + "%"} · ${j.project_name || "FramePilot"}`;

    if (etaEl) {
      if (j.eta_seconds !== undefined && (j.status === "running" || j.status === "queued")) {
        const ready = new Date(Date.now() + j.eta_seconds * 1000);
        etaEl.textContent = jtr("eta_left", "{time} left · ready around {clock}", {
          time: roughTime(j.eta_seconds),
          clock: ready.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        });
      } else {
        etaEl.textContent = "";
      }
    }

    const qText = document.getElementById("queueNoticeText");
    queuedPolls = j.status === "queued" && !j.queue_position ? queuedPolls + 1 : 0;
    if (j.queue_position && j.queue_position > 0) {
      if (queueNotice) queueNotice.style.display = "block";
      if (qText) qText.textContent = jtr("job_queue_notice", "In queue", { n: j.queue_position });
    } else if (queuedPolls >= 3) {                 // ~6 s and still not started: the worker is probably not running
      if (queueNotice) queueNotice.style.display = "block";
      if (qText) qText.textContent = jtr("job_waiting_worker", "Waiting for the worker");
    } else {
      if (queueNotice) queueNotice.style.display = "none";
    }

    renderStages(j.stages || [], j.stage, j.status, j.report);

    if (lastStatus && lastStatus !== j.status && (j.status === "done" || j.status === "error")) notifyEnd(j);
    lastStatus = j.status;

    if (j.status === "done") {
      clearInterval(timerInterval);
      setTimeout(() => {
        window.location.href = `/results/${j.session_id}`;
      }, 1500);
      return;
    } else if (j.status === "error") {
      clearInterval(timerInterval);
      if (errorCard) errorCard.style.display = "block";
      const errText = document.getElementById("errorMsgText");
      if (errText) errText.textContent = j.error || "Stage execution failed";
      const logDetails = document.getElementById("logDetails");
      if (logDetails) logDetails.textContent = j.log_tail || j.error || "";
      return;
    }

    setTimeout(pollJob, 2000);
  } catch (err) {
    setTimeout(pollJob, 3000);
  }
}

function toggleDetails() {
  const d = document.getElementById("logDetails");
  if (d) {
    d.style.display = d.style.display === "none" ? "block" : "none";
  }
}

async function retryJob() {
  const jobMeta = document.getElementById("jobMeta");
  if (!jobMeta) return;
  const jobId = parseInt(jobMeta.dataset.jobId, 10);
  const btn = document.getElementById("retryBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳...";
  }

  try {
    const res = await fetch(`/api/jobs/${jobId}/retry`, { method: "POST" });
    if (res.ok) {
      const errCard = document.getElementById("errorCard");
      if (errCard) errCard.style.display = "none";
      startTime = Date.now();
      lastStatus = "queued";
      timerInterval = setInterval(updateTimer, 1000);
      pollJob();
    } else {
      alert("Failed to retry job");
      if (btn) btn.disabled = false;
    }
  } catch (e) {
    alert("Network error: " + e);
    if (btn) btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  timerInterval = setInterval(updateTimer, 1000);
  updateNotifyButton();
  pollJob();
});
