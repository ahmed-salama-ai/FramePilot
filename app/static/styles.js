// Editing style on the upload page (Task 2). The styles, their texts, values and limits all come from /api/styles
// (configs/styles.yaml), so a new style there needs no change here. The server checks the values
// (/api/styles/check, director/styles.py) and its message is shown in the page's language.
// window.readStyleForm() -> {ok: true, value: {preset, choices, remove_pauses}} | {ok: false, message}.
(function () {
  const box = document.getElementById("styleBox");
  if (!box) return;
  const $ = id => document.getElementById(id);
  const lang = () => (typeof getLang === "function" ? getLang() : "en");
  const tr = (key, vars) => (typeof t === "function" ? t(key, vars) : key);
  const pick = (both) => (both && typeof both === "object" ? (both[lang()] || both.en || "") : String(both || ""));
  const WEIGHTS = ["speaker", "frontal", "quality", "gesture", "shake"];
  const NUMBERS = { styleMinShot: "min_shot", styleMaxShot: "max_shot", styleZooms: "zooms_per_minute",
                    styleMinTurn: "min_turn" };
  let data = null;          // /api/styles
  let lastError = null;     // the last {en, ar} message, shown again when the language changes
  let checkTimer = null;

  const presetById = id => data.presets.find(p => p.id === id);
  const chosen = () => {
    const r = box.querySelector('input[name="stylePreset"]:checked');
    return r ? r.value : data.default;
  };
  const customId = () => (data.presets.find(p => p.custom) || {}).id;

  function drawPresets() {
    const now = data && box.querySelector('input[name="stylePreset"]:checked');
    const keep = now ? now.value : data.default;
    const list = $("stylePresets");
    list.innerHTML = "";
    data.presets.forEach(p => {
      const option = document.createElement("label");
      option.className = "style-option";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "stylePreset";
      radio.value = p.id;
      radio.checked = p.id === keep;
      radio.addEventListener("change", () => {
        fill(p.choices);
        markChosen();
        check();
      });
      const text = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = pick(p.name);
      const desc = document.createElement("small");
      desc.textContent = pick(p.description);
      text.append(name, desc);
      option.append(radio, text);
      list.appendChild(option);
    });
    markChosen();
  }

  function markChosen() {
    box.querySelectorAll(".style-option").forEach(o => {
      o.classList.toggle("is-chosen", o.querySelector("input").checked);
    });
  }

  function drawLevels() {
    box.querySelectorAll("select[data-level]").forEach(sel => {
      const keep = sel.value;
      sel.innerHTML = "";
      (data.levels[sel.dataset.level] || []).forEach(v => {
        const o = document.createElement("option");
        o.value = v;
        o.textContent = tr("style_level_" + v);
        sel.appendChild(o);
      });
      if (keep) sel.value = keep;
    });
  }

  function drawPauseHint() {
    $("stylePausesHint").textContent = tr("style_pauses_hint", { min: data.pauses.min_pause, keep: data.pauses.keep });
  }

  function setLimits() {
    const L = data.limits;
    Object.entries(NUMBERS).forEach(([id, key]) => {
      $(id).min = L[key][0];
      $(id).max = L[key][1];
    });
    WEIGHTS.forEach(w => { $("styleW_" + w).min = L.weights[0]; $("styleW_" + w).max = L.weights[1]; });
  }

  function fill(c) {
    Object.entries(NUMBERS).forEach(([id, key]) => { $(id).value = c[key]; });
    $("styleSensitivity").value = c.sensitivity;
    $("styleSplit").value = c.split;
    $("styleReactions").checked = !!c.reactions;
    WEIGHTS.forEach(w => { $("styleW_" + w).value = c.weights[w]; });
  }

  function read() {
    const num = id => {
      const v = $(id).value.trim();
      return v === "" ? null : Number(v);
    };
    const c = {};
    Object.entries(NUMBERS).forEach(([id, key]) => { c[key] = num(id); });
    c.sensitivity = $("styleSensitivity").value;
    c.split = $("styleSplit").value;
    c.reactions = $("styleReactions").checked;
    c.weights = {};
    WEIGHTS.forEach(w => { c.weights[w] = num("styleW_" + w); });
    return c;
  }

  function value() {
    const preset = chosen();
    const p = presetById(preset);
    return { preset, choices: p && p.custom ? read() : {}, remove_pauses: $("styleRemovePauses").checked };
  }

  function showError(detail) {
    lastError = detail;
    const el = $("styleError");
    el.textContent = detail ? pick(detail) : "";
    el.style.display = detail ? "block" : "none";
    if (detail) $("styleAdvanced").open = true;
  }

  async function ask(v) {
    const res = await fetch("/api/styles/check", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(v)
    });
    if (res.ok) return { ok: true };
    let detail = { en: "The editing style could not be checked.", ar: "تعذر التحقق من نمط المونتاج." };
    try { detail = (await res.json()).detail || detail; } catch (e) { }
    return { ok: false, detail };
  }

  async function check() {
    if (!data) return true;
    try {
      const r = await ask(value());
      showError(r.ok ? null : r.detail);
      return r.ok;
    } catch (e) {
      return true;            // offline check: the server checks again when the project is created
    }
  }

  function onAdvancedEdit() {
    const custom = customId();
    if (custom && chosen() !== custom) {                 // a changed value = the user's own style
      const radio = box.querySelector(`input[name="stylePreset"][value="${custom}"]`);
      if (radio) radio.checked = true;
      markChosen();
    }
    clearTimeout(checkTimer);
    checkTimer = setTimeout(check, 350);
  }

  window.readStyleForm = async function () {
    if (!data) return { ok: true, value: null };         // styles not loaded: no style = default.yaml (Balanced)
    const v = value();
    try {
      const r = await ask(v);
      showError(r.ok ? null : r.detail);
      return r.ok ? { ok: true, value: v } : { ok: false, message: pick(r.detail) };
    } catch (e) {
      return { ok: true, value: v };                     // the server checks it again on upload
    }
  };

  fetch("/api/styles")
    .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(d => {
      data = d;
      setLimits();
      drawLevels();
      drawPresets();
      drawPauseHint();
      fill(presetById(chosen()).choices);
      box.querySelectorAll("#styleAdvanced input, #styleAdvanced select").forEach(el => {
        el.addEventListener("input", onAdvancedEdit);
        el.addEventListener("change", onAdvancedEdit);
      });
    })
    .catch(() => { box.style.display = "none"; });

  document.addEventListener("framepilot:lang", () => {
    if (!data) return;
    drawPresets();
    drawLevels();
    drawPauseHint();
    if (lastError) showError(lastError);
  });
})();
