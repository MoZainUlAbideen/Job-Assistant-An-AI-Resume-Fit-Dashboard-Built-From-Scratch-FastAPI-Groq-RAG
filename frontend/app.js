const $ = (s) => document.querySelector(s);
const form = $("#form"), fileInput = $("#resume"), drop = $("#drop"), dropText = $("#drop-text");
const statusEl = $("#status"), results = $("#results"), scanBtn = $("#scan-btn"), tailorBtn = $("#tailor-btn");
const API = (window.API_BASE || "").replace(/\/$/, "");
let lastScanKey = null;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const LABELS = { keywords: "Keywords", title: "Job title", experience: "Experience", education: "Education", format: "Format" };

// ---------- file picker / drag and drop
function showFile() {
  const f = fileInput.files[0];
  drop.classList.toggle("has-file", !!f);
  dropText.textContent = f ? f.name : "Choose a PDF or DOCX, or drop it here";
}
fileInput.addEventListener("change", () => { showFile(); tailorBtn.disabled = true; });
["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((e) => drop.addEventListener(e, () => drop.classList.remove("over")));
drop.addEventListener("drop", (ev) => {
  ev.preventDefault();
  if (ev.dataTransfer.files.length) { fileInput.files = ev.dataTransfer.files; showFile(); tailorBtn.disabled = true; }
});

// ---------- requests
function setStatus(msg, isError = false) { statusEl.textContent = msg; statusEl.classList.toggle("error", isError); }

async function post(path, slowMsg) {
  const f = fileInput.files[0];
  const jd = $("#jd").value.trim();
  if (!f) throw new Error("Choose your resume file first.");
  if (jd.length < 80) throw new Error("Paste the full job description — that looks too short.");
  const body = new FormData();
  body.append("resume", f);
  body.append("jd_text", jd);
  const title = $("#title").value.trim();
  if (title) body.append("job_title", title);

  // Render's free tier sleeps when idle; the first request can take ~a minute
  const wake = setTimeout(() => setStatus(slowMsg), 6000);
  // never hang forever: a cold Render start is ~60s, so give up after 100s with a clear message
  const ctrl = new AbortController();
  const kill = setTimeout(() => ctrl.abort(), 100000);
  try {
    const res = await fetch(API + path, { method: "POST", body, signal: ctrl.signal });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `The server returned an error (${res.status}).`);
    return data;
  } catch (e) {
    if (e.name === "AbortError") throw new Error(`No response from ${API} after 100 seconds. The server may be down or the API address in config.js is wrong.`);
    if (e instanceof TypeError) throw new Error(`Couldn't reach ${API}. Check the API address in config.js and that the backend allows this site (ALLOWED_ORIGINS).`);
    throw e;
  } finally { clearTimeout(wake); clearTimeout(kill); }
}

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  scanBtn.disabled = tailorBtn.disabled = true;
  setStatus("Reading your resume…");
  try {
    const data = await post("/api/scan", "Starting the server — the free tier sleeps when idle, so the first check can take up to a minute.");
    renderReport(data.report, data.resume);
    setStatus("");
    tailorBtn.disabled = false;
  } catch (e) { setStatus(e.message, true); }
  finally { scanBtn.disabled = false; }
});

tailorBtn.addEventListener("click", async () => {
  scanBtn.disabled = tailorBtn.disabled = true;
  setStatus("Drafting edits and checking each one against your resume…");
  try {
    const data = await post("/api/tailor", "Still working — the server may be starting up.");
    renderTailor(data);
    setStatus("");
    document.getElementById("tailor-sheet")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  } catch (e) { setStatus(e.message, true); }
  finally { scanBtn.disabled = false; tailorBtn.disabled = false; }
});

// ---------- rendering
function verdict(score, knockouts) {
  if (knockouts.length) return "Possible automatic filters below — fix or address those first.";
  if (score >= 80) return "Strong match. Your resume uses most of this job's language.";
  if (score >= 60) return "Decent match. A few missing keywords are worth adding if you have them.";
  return "Weak match for this posting. Check the missing skills before applying.";
}

function bars(components) {
  return Object.entries(components).map(([k, c]) => `
    <div class="bar">
      <span>${LABELS[k] || k}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${Math.max(0, Math.min(100, c.score))}%"></span></span>
      <span class="bar-val">${Math.round(c.score)}</span>
      <span class="bar-detail">${esc(c.detail)} · weight ${Math.round(c.weight)}%</span>
    </div>`).join("");
}

function chip(k) {
  const pref = k.importance === "preferred" ? `<span class="pref">preferred</span>` : "";
  const ev = k.status === "implied" ? `<span class="ev">you have ${esc(k.evidence.join(", "))}</span>` : "";
  return `<span class="chip ${k.status}">${esc(k.keyword)}${pref}${ev}</span>`;
}

function kwGroup(title, hint, items) {
  if (!items.length) return "";
  return `<div class="kw-group"><p class="kw-head">${title} <span>${hint}</span></p><div class="chips">${items.map(chip).join("")}</div></div>`;
}

function reportHtml(r, resume) {
  const hard = r.keywords.filter((k) => !k.soft);
  const soft = r.keywords.filter((k) => k.soft);
  const by = (s) => hard.filter((k) => k.status === s);
  const issues = r.checks.filter((c) => c.status !== "pass");
  const passes = r.checks.filter((c) => c.status === "pass");
  const icon = { pass: "✓", warn: "!", fail: "×" };
  const checkLi = (c) => `<li><span class="mark ${c.status}" aria-label="${c.status}">${icon[c.status]}</span><span>${esc(c.label)}<span class="d">${esc(c.detail)}</span></span></li>`;
  const weak = (r.tips.weak_openers || []).length;

  return `
  <div class="sheet fresh">
    <div class="scoreline">
      <div class="score">${Math.round(r.score)}<small> / 100</small></div>
      <p class="verdict">${esc(verdict(r.score, r.knockouts))}</p>
    </div>
    <div class="bars">${bars(r.components)}</div>
  </div>

  ${r.knockouts.length ? `<div class="sheet fresh"><h2>Could filter you out</h2>
    <p class="sub">Recruiters often set these as hard filters in the ATS. Address them in your resume or cover letter if you can.</p>
    <ul class="alerts">${r.knockouts.map((k) => `<li>${esc(k)}</li>`).join("")}</ul></div>` : ""}

  <div class="sheet fresh">
    <h2>Keywords from the job</h2>
    <p class="sub">Highlighted means the exact term is on your resume. Dashed means you have related skills but not the term itself; an ATS won't connect them, so adding the term is an easy, honest win.</p>
    ${kwGroup("On your resume", `${by("matched").length}`, by("matched"))}
    ${kwGroup("Related skills, exact term missing", `${by("implied").length}`, by("implied"))}
    ${kwGroup("Not on your resume", `${by("missing").length}`, by("missing"))}
    ${soft.length ? kwGroup("Soft skills", "lower weight", soft) : ""}
  </div>

  <div class="sheet fresh">
    <h2>Can an ATS read it?</h2>
    <p class="sub">${issues.length ? `${issues.length} problem${issues.length > 1 ? "s" : ""} found.` : "No layout problems found."} Read from ${resume.sections.length} sections, ${resume.bullets} bullets, ~${resume.experience_years} years of dated experience.</p>
    <ul class="checks">${issues.map(checkLi).join("")}${passes.map(checkLi).join("")}</ul>
    ${r.tips.bullets ? `<p class="sub" style="margin-top:14px">For the human reader: ${r.tips.quantified} of ${r.tips.bullets} bullets include a number${weak ? `, and ${weak} start with a weak opener like “Utilized” or “Worked on”` : ""}.</p>` : ""}
  </div>`;
}

function renderReport(r, resume) {
  results.innerHTML = reportHtml(r, resume) + `<div id="tailor-slot"></div>`;
}

function renderTailor(d) {
  const t = d.tailor, b = d.before, a = d.after;
  const acc = t.edits.filter((e) => e.status === "accepted");
  const rej = t.edits.filter((e) => e.status === "rejected");
  const diff = (a.score - b.score);
  const changeHtml = (e, blocked) => `
    <div class="change ${blocked ? "blocked" : ""}">
      <p class="ctx">${esc(e.entry || e.section)}</p>
      <del>${esc(e.original)}</del>
      <ins>${esc(e.rewritten)}</ins>
      <p class="why ${blocked ? "" : "ok"}">${blocked ? "Blocked: " + esc(e.reasons.join("; ")) : "Adds " + esc(e.keywords_added.join(", "))}</p>
    </div>`;

  const url = URL.createObjectURL(new Blob([Uint8Array.from(atob(d.docx_base64), (c) => c.charCodeAt(0))],
    { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }));

  const html = `
  <div class="sheet fresh" id="tailor-sheet">
    <h2>Tailored resume</h2>
    <div class="delta"><strong>${Math.round(b.score)} → ${Math.round(a.score)}</strong><span>${diff > 0 ? `+${diff.toFixed(1)} points, re-scored on the file you'll download` : "No score change — nothing could be added honestly"}</span></div>
    ${t.llm_note ? `<p class="note">${esc(t.llm_note)}</p>` : ""}
    ${t.skills_added.length ? `<p class="kw-head">Added to Skills</p>
      <div class="chips" style="margin-bottom:16px">${t.skills_added.map((s) => `<span class="chip matched">${esc(s.keyword)}<span class="ev">because you have ${esc(s.evidence.join(", "))}</span></span>`).join("")}</div>` : ""}
    ${acc.length ? `<p class="kw-head">Rewritten bullets <span>${acc.length}</span></p>${acc.map((e) => changeHtml(e, false)).join("")}` : ""}
    ${rej.length ? `<details class="blocked-list"><summary>${rej.length} suggested rewrite${rej.length > 1 ? "s" : ""} blocked for overstating your resume</summary>${rej.map((e) => changeHtml(e, true)).join("")}</details>` : ""}
    ${t.gaps.length ? `<p class="kw-head" style="margin-top:16px">Not added</p><p class="gaps">${esc(t.gaps.join(", "))}. Nothing on your resume backs these up, so they're left out. Add them yourself only if they're true.</p>` : ""}
    ${t.title_suggestion ? `<p class="note">${esc(t.title_suggestion)}</p>` : ""}
    <a class="download" href="${url}" download="${esc(d.filename)}">Download ${esc(d.filename)}</a>
  </div>`;
  const slot = document.getElementById("tailor-slot");
  if (slot) slot.innerHTML = html; else results.insertAdjacentHTML("beforeend", html);
}
