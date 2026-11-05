// FramePilot - the brand kit form (templates/brand_form.html), used on the upload page and the results page

const BRAND_DEFAULT = { logo_corner: "top-right", logo_size: 0.12,
                        captions: { text_color: "#ffffff", box_color: "#000000", box: true, size: "medium",
                                    word_color: "#ffd43b" },
                        clean_voice: false };
let brandRemove = [];          // files the user asked to remove ("logo", "intro", "outro", "music")

function brandEl(id) { return document.getElementById(id); }

function readBrandForm() {
  return {
    settings: {
      logo_corner: brandEl("brandCorner").value,
      logo_size: parseFloat(brandEl("brandLogoSize").value),
      captions: {
        text_color: brandEl("brandTextColor").value,
        box_color: brandEl("brandBoxColor").value,
        box: brandEl("brandBoxStyle").value === "box",
        size: brandEl("brandCapSize").value,
        word_color: brandEl("brandWordColor").value
      },
      clean_voice: brandEl("brandCleanVoice").checked
    },
    logo: brandEl("brandLogo").files[0] || null,
    intro: brandEl("brandIntro").files[0] || null,
    outro: brandEl("brandOutro").files[0] || null,
    music: brandEl("brandMusic").files[0] || null,
    remove: brandRemove.slice()
  };
}

// true = nothing chosen (no files, default look): the upload sends no brand kit
function brandIsDefault(form) {
  return !form.logo && !form.intro && !form.outro && !form.music &&
    JSON.stringify(form.settings) === JSON.stringify(BRAND_DEFAULT);
}

// put a saved brand.json into the form; show the current files with a remove button
function fillBrandForm(b) {
  if (!b) return;
  brandRemove = [];
  brandEl("brandCorner").value = b.logo_corner || BRAND_DEFAULT.logo_corner;
  const sizes = [0.08, 0.12, 0.18];
  const size = sizes.reduce((a, x) => Math.abs(x - (b.logo_size || 0.12)) < Math.abs(a - (b.logo_size || 0.12)) ? x : a);
  brandEl("brandLogoSize").value = String(size);
  const c = b.captions || BRAND_DEFAULT.captions;
  brandEl("brandTextColor").value = (c.text_color || "#ffffff").toLowerCase();
  brandEl("brandBoxColor").value = (c.box_color || "#000000").toLowerCase();
  brandEl("brandBoxStyle").value = c.box === false ? "outline" : "box";
  brandEl("brandCapSize").value = c.size || "medium";
  brandEl("brandWordColor").value = (c.word_color || "#ffd43b").toLowerCase();
  brandEl("brandCleanVoice").checked = !!b.clean_voice;
  [["logo", "brandLogoNow"], ["intro", "brandIntroNow"], ["outro", "brandOutroNow"], ["music", "brandMusicNow"]].forEach(([key, id]) => {
    const el = brandEl(id);
    if (!el) return;
    el.innerHTML = "";
    if (!b[key]) return;
    const name = document.createElement("bdi");
    name.textContent = b[key].split("/").pop();
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-danger btn-sm";
    btn.style.marginInlineStart = "8px";
    btn.textContent = "✕";
    btn.title = "Remove";
    btn.onclick = () => {
      if (!brandRemove.includes(key)) brandRemove.push(key);
      el.innerHTML = "";
      el.textContent = (typeof t === "function" ? t("brand_removed") : "Removed") + " (" + key + ")";
    };
    el.append(name, btn);
  });
}
