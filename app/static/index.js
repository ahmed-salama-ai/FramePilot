// FramePilot - Projects Studio Index Page Logic

async function deleteProject(sid) {
  const msg = typeof t === "function" ? t("confirm_delete") : "Delete project permanently?";
  if (!confirm(msg)) return;
  
  try {
    const res = await fetch(`/api/projects/${sid}`, { method: "DELETE" });
    if (res.ok) {
      const card = document.getElementById(`card-${sid}`);
      if (card) {
        card.style.opacity = "0";
        card.style.transform = "scale(0.95)";
        setTimeout(() => location.reload(), 300);
      } else {
        location.reload();
      }
    } else {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || "Failed to delete project");
    }
  } catch (err) {
    alert("Network error: " + err);
  }
}


const itr = (key, fallback, vars) => (typeof t === "function" ? t(key, vars) : fallback);

function notifyWanted() {
  try { return localStorage.getItem("framepilot_notify") === "1"; } catch (e) { return false; }
}

async function pollProjects() {
  const cards = [...document.querySelectorAll(".project-card")]
    .filter(c => c.dataset.jobId && ["queued", "running"].includes(c.dataset.jobStatus));
  if (!cards.length) return;
  for (const card of cards) {
    try {
      const res = await fetch(`/api/jobs/${card.dataset.jobId}`);
      if (!res.ok) continue;
      const j = await res.json();
      const pct = card.querySelector(".job-progress");
      if (pct) pct.textContent = `${j.progress}%`;
      const eta = card.querySelector(".project-eta");
      if (eta) {
        eta.textContent = j.eta_seconds !== undefined
          ? itr("eta_left_short", "{n} min left", { n: Math.max(1, Math.round(j.eta_seconds / 60)) }) : "";
      }
      if (j.status !== card.dataset.jobStatus) {
        if ((j.status === "done" || j.status === "error") && notifyWanted() && "Notification" in window
            && Notification.permission === "granted") {
          new Notification(j.status === "done" ? itr("notify_done_title", "FramePilot: ready") : itr("notify_error_title", "FramePilot: failed"),
                           { body: j.project_name || j.session_id, icon: "/static/logo.jpeg", tag: `framepilot-job-${j.id}` });
        }
        setTimeout(() => location.reload(), 1000);
        return;
      }
    } catch (err) {
      console.error("Failed to poll job:", err);
    }
  }
  setTimeout(pollProjects, 4000);
}

document.addEventListener("DOMContentLoaded", pollProjects);
