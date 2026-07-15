/* Custom-comps wizard — per-comp entry + validation. Display/flow only; all classification and
 * screening happen server-side (POST /api/v1/custom_validate_comp, GET /custom_result). The
 * <8-comp options key on the VALID count (resolved + class 4), never the entered count. */
(function () {
  const root = document.getElementById("comp-entry");
  if (!root) return;
  const subjectBbl = root.dataset.subjectBbl;
  const autofillAvailable = root.dataset.autofillAvailable === "true";
  const MIN = 8;

  const listEl = document.getElementById("comp-list");
  const countEl = document.getElementById("valid-count");
  const thinBox = document.getElementById("thin-options");
  const readyBox = document.getElementById("ready");
  const autofillBtn = document.getElementById("run-autofill");
  const autofillNA = document.getElementById("autofill-unavailable");
  const input = document.getElementById("comp-bbl");
  const addBtn = document.getElementById("comp-add");

  const entered = new Set();       // every BBL tried (dedup)
  const valid = [];                // ordered valid comp BBLs

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function renderRow(v) {
    const li = document.createElement("li");
    li.className = "comp-row " + (v.valid ? "comp-valid" : "comp-rejected");
    if (v.valid) {
      const flags = [];
      if (v.cross_type) flags.push('<span class="flag flag-cross">cross-type</span>');
      if (v.land_dominant) flags.push('<span class="flag flag-land">land-dominant</span>');
      const sf = v.sf != null ? Number(v.sf).toLocaleString() + " SF" : "SF n/a";
      li.innerHTML = `<span class="ok">✓</span> <strong>${esc(v.bbl)}</strong> · ` +
        `${esc(v.address || "address n/a")} · ${esc(v.bldg_class)} (${esc(v.asset_type)}) · ${sf} ` +
        flags.join(" ");
    } else {
      li.innerHTML = `<span class="no">✕</span> <strong>${esc(v.bbl)}</strong> — ${esc(v.reason)}`;
    }
    listEl.appendChild(li);
  }

  function refreshControls() {
    countEl.textContent = valid.length;
    // Below 2: nothing to run yet. 2..7: expose BOTH options. >=8: generate.
    const below = valid.length < MIN;
    thinBox.hidden = !(valid.length >= 2 && below);
    readyBox.hidden = below;
    if (!autofillAvailable) {
      autofillBtn.hidden = true;
      autofillNA.hidden = false;
    }
  }

  async function addComp() {
    const bbl = (input.value || "").trim();
    if (!bbl) return;
    if (entered.has(bbl)) { input.value = ""; return; }
    entered.add(bbl);
    addBtn.disabled = true;
    try {
      const r = await fetch("/api/v1/custom_validate_comp", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject_bbl: subjectBbl, comp_bbls: [bbl] }),
      });
      const v = await r.json();
      renderRow(v);
      if (v.valid) valid.push(v.bbl);
      refreshControls();
    } catch (e) {
      const li = document.createElement("li");
      li.className = "comp-row comp-rejected";
      li.textContent = "Could not reach the validator; try again.";
      listEl.appendChild(li);
      entered.delete(bbl);
    } finally {
      addBtn.disabled = false;
      input.value = "";
      input.focus();
    }
  }

  function go(fill) {
    const params = new URLSearchParams({ subject: subjectBbl, comps: valid.join(","), fill });
    window.location = "/custom_result?" + params.toString();
  }

  addBtn.addEventListener("click", addComp);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addComp(); } });
  document.getElementById("run-thin").addEventListener("click", () => go("none"));
  autofillBtn.addEventListener("click", () => go("autofill"));
  document.getElementById("run-full").addEventListener("click", () => go("none"));

  refreshControls();
})();
