/* Custom-comps wizard — per-comp entry + validation. Display/flow only; all classification and
 * screening happen server-side (POST /api/v1/custom_validate_comp, GET /custom_result). The
 * <8-comp options key on the VALID count (resolved + class 4), never the entered count.
 * Comps enter by ADDRESS or BBL (same resolver as the auto path); each row shows its status,
 * flags (cross-type / land-dominant / size-dissimilar, computed ON ENTRY server-side), and a
 * remove control. Rows render in the same comp-table markup the output page uses. */
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
  const bblInput = document.getElementById("comp-bbl");
  const houseInput = document.getElementById("comp-house");
  const streetInput = document.getElementById("comp-street");
  const boroSelect = document.getElementById("comp-borough");
  // BOTH input methods get an equally visible submit control (address fieldset + BBL fieldset).
  const addBtns = Array.from(document.querySelectorAll(".comp-add-btn"));
  function setAddDisabled(d) { addBtns.forEach(b => { b.disabled = d; }); }

  const entered = new Set();       // RESOLVED BBLs already in the list (dedup either input path)
  const valid = [];                // ordered valid comp BBLs

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function flagSpans(v) {
    const f = [];
    if (v.cross_type) f.push('<span class="flag">cross-type</span>');
    if (v.land_dominant) f.push('<span class="flag">land-dominant</span>');
    if (v.size_dissimilar) f.push(`<span class="size-flag" title="BldgArea outside ±${esc(v.size_band_pct)}% of the subject; percentile not size-restricted">size-dissimilar</span>`);
    return f.join(" ");
  }

  function renderRow(v) {
    const tr = document.createElement("tr");
    tr.dataset.bbl = v.bbl || "";
    if (v.valid) {
      tr.className = "comp-row-valid";
      const sf = v.sf != null ? Number(v.sf).toLocaleString() : "n/a";
      tr.innerHTML =
        `<td>${esc(v.bbl)}</td>` +
        `<td>${esc(v.address || "n/a")}</td>` +
        `<td>${esc(v.bldg_class)} (${esc(v.asset_type)})</td>` +
        `<td>${sf}</td>` +
        `<td>${esc(v.year_built || "n/a")}</td>` +
        `<td>${v.distance_miles != null ? esc(v.distance_miles) : "n/a"}</td>` +
        `<td><span class="ok">✓ valid</span> ${flagSpans(v)}</td>` +
        `<td><button type="button" class="comp-remove" title="Remove this comp">−</button></td>`;
    } else {
      // Rejected entries keep the table's column grid intact: dashes where data would be, and
      // the exclusion reason lives in the STATUS/FLAGS column — never where an address belongs.
      tr.className = "comp-row-rejected";
      tr.innerHTML =
        `<td>${esc(v.bbl || "—")}</td>` +
        `<td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>` +
        `<td class="reject-reason"><span class="no">✕</span> ${esc(v.reason)}</td>` +
        `<td><button type="button" class="comp-remove" title="Remove this row">−</button></td>`;
    }
    tr.querySelector(".comp-remove").addEventListener("click", () => removeRow(tr, v));
    listEl.appendChild(tr);
  }

  function removeRow(tr, v) {
    if (v.bbl) {
      entered.delete(v.bbl);
      const i = valid.indexOf(v.bbl);
      if (i >= 0) valid.splice(i, 1);
    }
    tr.remove();
    refreshControls();               // <8 options / generate re-evaluate on the VALID count
  }

  function refreshControls() {
    countEl.textContent = valid.length;
    const below = valid.length < MIN;
    thinBox.hidden = !(valid.length >= 2 && below);
    readyBox.hidden = below;
    if (!autofillAvailable) {
      autofillBtn.hidden = true;
      autofillNA.hidden = false;
    }
  }

  const errEl = document.getElementById("comp-entry-error");
  function showError(msg) { errEl.textContent = msg; errEl.hidden = false; }
  function clearError() { errEl.textContent = ""; errEl.hidden = true; }

  // The CLICKED button determines the input source: 'address' sends ONLY the address fields,
  // 'bbl' sends ONLY the BBL — the other side is ignored, never a silent fallback. An empty
  // clicked input gets an inline error naming that input.
  async function addComp(source) {
    clearError();
    const body = { subject_bbl: subjectBbl };
    if (source === "address") {
      const house = (houseInput.value || "").trim();
      const street = (streetInput.value || "").trim();
      if (!house && !street) { showError("Enter an address"); return; }
      // Borough is REQUIRED for address resolution (no ZIP alternative in the UI) — name the
      // missing field instead of letting the resolver return a vague not-found.
      if (!boroSelect.value) { showError("Select a borough"); return; }
      body.house_number = house; body.street = street; body.borough = boroSelect.value || "";
    } else {
      const bbl = (bblInput.value || "").trim();
      if (!bbl) { showError("Enter a BBL"); return; }
      if (entered.has(bbl)) { bblInput.value = ""; return; }
      body.bbl = bbl;
    }
    setAddDisabled(true);
    try {
      const r = await fetch("/api/v1/custom_validate_comp", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const v = await r.json();
      if (v.bbl && entered.has(v.bbl)) return;         // address resolved to a comp already added
      if (v.bbl) entered.add(v.bbl);
      renderRow(v);
      if (v.valid) valid.push(v.bbl);
      refreshControls();
      // success: clear ONLY the inputs that were used; the other side keeps whatever was typed
      if (source === "address") { houseInput.value = ""; streetInput.value = ""; }
      else { bblInput.value = ""; }
    } catch (e) {
      const tr = document.createElement("tr");
      tr.className = "comp-row-rejected";
      tr.innerHTML = '<td colspan="8" class="reject-reason">Could not reach the validator; try again.</td>';
      listEl.appendChild(tr);
    } finally {
      setAddDisabled(false);
      (source === "address" ? houseInput : bblInput).focus();
    }
  }

  function go(fill) {
    const params = new URLSearchParams({ subject: subjectBbl, comps: valid.join(","), fill });
    window.location = "/custom_result?" + params.toString();
  }

  addBtns.forEach(b => b.addEventListener("click", () => addComp(b.dataset.source || "bbl")));
  bblInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addComp("bbl"); } });
  [houseInput, streetInput].forEach(el =>
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addComp("address"); } }));
  document.getElementById("run-thin").addEventListener("click", () => go("none"));
  autofillBtn.addEventListener("click", () => go("autofill"));
  document.getElementById("run-full").addEventListener("click", () => go("none"));

  refreshControls();
})();
