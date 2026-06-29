/* Renders the neutral distribution strip-plots and wires the RUNG 3 toggle.
 *
 * NO-VERDICT RENDERING (enforced here):
 *  - Neutral grays only. No red/amber/green; nothing colored to imply good/bad.
 *  - The subject is distinguished by a LABEL + point shape, NOT by an alarm color.
 *  - No threshold lines, no shaded zones, no "normal range" box, no box plot.
 *    Just the comp points, with subject and median marked neutrally.
 *  - Honest axis: framed by the actual data range (min..max), never cropped.
 *  - Labels state facts only: "subject", "median", "comps".
 */
const INK = "#1c1c1c", COMP = "#b4b4b4", SUBJECT_RING = "#1c1c1c", MEDIAN = "#6b6b6b", MEAN = "#404040";

function dataEl() {
  const el = document.getElementById("screen-data");
  if (!el || !el.textContent.trim()) return null;
  try { return JSON.parse(el.textContent); } catch (e) { return null; }
}

// Deterministic small y-jitter so overlapping comps are visible (no randomness).
function jitter(i) { return (((i * 2654435761) % 1000) / 1000 - 0.5) * 0.8; }

// Compact, type-agnostic axis tick formatter (e.g. 3000000 -> "3M", 197.9 -> "198"). No
// units baked in; works for any metric/property type.
const COMPACT = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

function stripPlot(canvas, sig) {
  const comps = sig.distribution || [];
  if (!comps.length) return;
  // marker data carries already-attached metadata (address/BBL/distance/phase-in gap/metric);
  // fall back to bare x-values if an older payload lacks comp_points.
  const cps = (sig.comp_points && sig.comp_points.length)
    ? sig.comp_points : comps.map(v => ({ x: v }));
  const sp = sig.subject_point || { x: sig.subject_value };
  const all = comps.concat([sig.subject_value, sig.median, sig.mean]).filter(v => v != null);
  let lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo) * 0.02 || Math.abs(hi) * 0.02 || 1;  // symmetric, honest

  new Chart(canvas.getContext("2d"), {
    type: "scatter",
    data: {
      datasets: [
        { label: "comps", data: cps.map((p, i) => ({ ...p, y: jitter(i) })),
          backgroundColor: COMP, pointRadius: 5, pointHoverRadius: 7 },
        { label: "median", data: [{ x: sig.median, y: 0, disp: sig.median_display }],
          backgroundColor: MEDIAN, pointStyle: "rectRot", pointRadius: 9,
          pointHoverRadius: 11, pointBorderColor: "#ffffff", pointBorderWidth: 1.5 },
        // mean — distinct triangle at the TRUE mean (never nudged); may sit near the median
        // diamond on symmetric pools — the white outline keeps the two readable when close.
        { label: "mean", data: [{ x: sig.mean, y: 0, disp: sig.mean_display }],
          backgroundColor: MEAN, pointStyle: "triangle", pointRadius: 9,
          pointHoverRadius: 11, pointBorderColor: "#ffffff", pointBorderWidth: 1.5 },
        { label: "subject", data: [{ ...sp, y: 0 }],
          backgroundColor: "#ffffff", borderColor: SUBJECT_RING, pointBorderWidth: 2.5,
          pointRadius: 10, pointHoverRadius: 12 },
      ],
    },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      layout: { padding: { top: 4, right: 14, bottom: 2, left: 6 } },
      font: { family: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", size: 12 },
      scales: {
        x: { min: lo - pad, max: hi + pad,
             ticks: { color: INK, font: { size: 11 }, maxRotation: 0, autoSkipPadding: 16,
                      callback: (v) => COMPACT.format(v) },
             grid: { color: "rgba(0,0,0,0.06)" }, border: { color: "rgba(0,0,0,0.18)" } },
        y: { display: false, min: -1, max: 1 },
      },
      plugins: {
        legend: { position: "top",
                  labels: { color: INK, usePointStyle: true, boxWidth: 10, padding: 14,
                            font: { size: 12 } } },
        tooltip: {
          usePointStyle: true, padding: 9, titleFont: { size: 12 }, bodyFont: { size: 12 },
          callbacks: {
            title: () => "",
            label: (c) => {
              const lab = c.dataset.label, d = c.raw || {};
              const val = (d.disp != null) ? d.disp : c.parsed.x.toLocaleString();
              // mean / median are statistics, not buildings — value only.
              if (lab === "mean" || lab === "median") return `${lab}: ${val}`;
              const lines = [];
              if (d.address && d.address !== "n/a") lines.push(d.address);
              lines.push("BBL " + (d.bbl || "n/a"));
              if (lab !== "subject") lines.push("distance: " + (d.distance || "n/a"));
              lines.push("phase-in gap: " + (d.gap || "n/a"));
              lines.push(sig.label + ": " + val);
              return lines;
            },
          },
        },
      },
    },
  });
}

function renderCharts(data) {
  if (!data || data.status !== "ok") return;
  if (typeof Chart === "undefined") {           // CDN blocked/offline: skip, don't throw
    console.warn("Chart.js not loaded; skipping distribution charts.");
    return;
  }
  for (const sig of data.signals) {
    if (sig.refused) continue;
    const canvas = document.getElementById("chart-" + sig.key);
    if (!canvas) continue;
    try { stripPlot(canvas, sig); }
    catch (e) { console.error("chart render failed for " + sig.key, e); }  // isolate per chart
  }
}

function subjectBbl(data) {
  return data && data.subject ? data.subject.bbl : null;
}

// RUNG 3 — always-visible input + Compute (no toggle). Computes only on click.
function wireRung3(data) {
  const go = document.getElementById("rung3-go");
  if (!go) return;
  go.addEventListener("click", async () => {
    const out = document.getElementById("rung3-result");
    const noi = document.getElementById("rung3-noi").value;
    const bbl = subjectBbl(data);
    if (!bbl) { out.textContent = "No subject parcel to compute against."; return; }
    const params = new URLSearchParams({ bbl, noi, enabled: "true" });
    const resp = await fetch("/api/rung3?" + params.toString(), { method: "POST" });
    const r = await resp.json();
    if (r.computed) {
      out.innerHTML = `<p>${r.statement}</p>` +
        `<p class="rung3-stamp">NOI: user-supplied (no citation) · market value cited to ` +
        `${r.market_value_citation.source_dataset}@${r.market_value_citation.roll_year}</p>`;
    } else {
      out.innerHTML = `<p>${r.message}</p>`;
    }
  });
}

// Expense Ratio Check — same discipline; ratio = subject real estate taxes / user opex.
function wireExpenseRatio(data) {
  const go = document.getElementById("opex-go");
  if (!go) return;
  go.addEventListener("click", async () => {
    const out = document.getElementById("opex-result");
    const opex = document.getElementById("opex-input").value;
    const bbl = subjectBbl(data);
    if (!bbl) { out.textContent = "No subject parcel to compute against."; return; }
    const params = new URLSearchParams({ bbl, opex });
    const resp = await fetch("/api/expense_ratio?" + params.toString(), { method: "POST" });
    const r = await resp.json();
    if (r.computed) {
      out.innerHTML = `<p>${r.statement}</p><p class="rung3-stamp">${r.stamp}</p>`;
    } else {
      out.innerHTML = `<p>${r.message}</p>`;
    }
  });
}

// Radius slider — OVERRIDE mode. Drag shows a live comp count (cheap count endpoint,
// debounced); release re-runs the full screen once at the settled radius.
function wireRadius() {
  const ctl = document.querySelector(".radius-control");
  const slider = document.getElementById("radius-slider");
  const live = document.getElementById("radius-live");
  if (!ctl || !slider || !live) return;
  const bbl = ctl.dataset.bbl;
  let timer = null;

  slider.addEventListener("input", () => {            // DURING drag — readout + count only
    const r = slider.value;
    // Immediate readout: the exact value that will be submitted on release and shown as
    // "Radius used". parseFloat normalizes like the server's %g (1.0 -> "1", 0.5 -> "0.5").
    live.textContent = `${parseFloat(r)} mi`;
    if (timer) clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const j = await (await fetch(`/api/comp_count?bbl=${bbl}&radius=${r}`)).json();
        live.textContent = `${j.radius} mi · ${j.count} comps` +
          (j.below_min ? ` — below the ${j.min_comp_count}-comp minimum` : "");
      } catch (e) { /* preview is best-effort */ }
    }, 120);                                            // ~120ms debounce
  });

  slider.addEventListener("change", () => {           // ON release — one full re-run
    window.location = `/screen?bbl=${bbl}&radius=${slider.value}`;
  });
}

(function () {
  const data = dataEl();
  // Decouple: a chart failure must NEVER prevent the user-input tools from wiring.
  try { renderCharts(data); } catch (e) { console.error("renderCharts failed:", e); }
  try { wireRung3(data); } catch (e) { console.error("wireRung3 failed:", e); }
  try { wireExpenseRatio(data); } catch (e) { console.error("wireExpenseRatio failed:", e); }
  try { wireRadius(); } catch (e) { console.error("wireRadius failed:", e); }
})();
