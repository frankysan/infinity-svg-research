(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const els = {
    summary: $("summary"), search: $("search"), status: $("status-filter"), action: $("action-filter"),
    queue: $("queue"), queueCount: $("queue-count"), position: $("position"), title: $("asset-title"),
    meta: $("asset-meta"), previous: $("previous"), next: $("next"), comparison: $("comparison"),
    opacityWrap: $("opacity-wrap"), opacity: $("opacity"), blinkPause: $("blink-pause"),
    form: $("decision-form"), reasons: $("reasons"), evidence: $("evidence"),
    confirmWrap: $("confirm-missing-wrap"), confirmMissing: $("confirm-missing"),
    save: $("save"), message: $("message")
  };
  let state = {summary: {}, assets: []};
  let filtered = [];
  let currentPath = null;
  let mode = "side";
  let activeCandidate = 0;
  let blinkTimer = null;
  let blinkVisible = true;
  let selectedCandidates = new Set();

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[ch]);
  }
  function imageUrl(kind, path) { return `/render/${kind}?path=${encodeURIComponent(path)}`; }
  function current() { return filtered.find(row => row.army_path === currentPath) || filtered[0] || null; }
  function reviewed(status) { return ["reviewed-match", "reviewed-design-mismatch", "confirmed-missing"].includes(status); }
  function selectedPaths() {
    return [...selectedCandidates];
  }
  function decisionValue() {
    return document.querySelector('input[name="decision"]:checked')?.value || "unresolved";
  }
  function stopBlink() {
    if (blinkTimer) clearInterval(blinkTimer);
    blinkTimer = null;
    blinkVisible = true;
  }
  function startBlink() {
    stopBlink();
    blinkTimer = setInterval(() => {
      blinkVisible = !blinkVisible;
      const top = document.querySelector(".blink-top");
      if (top) top.style.opacity = blinkVisible ? "1" : "0";
    }, 650);
    els.blinkPause.textContent = "Pause blink";
  }

  function applyFilters() {
    const query = els.search.value.trim().toLowerCase();
    const status = els.status.value;
    const action = els.action.value;
    filtered = state.assets.filter(row => {
      const haystack = [row.army_path, ...row.subjects, ...row.unit_slugs, ...row.profile_names,
        ...row.candidates.flatMap(c => [c.path, c.subject, ...c.tags])].join(" ").toLowerCase();
      if (query && !haystack.includes(query)) return false;
      if (status === "pending" && !["name-candidate", "unresolved"].includes(row.identity_status)) return false;
      if (status === "reviewed" && !reviewed(row.identity_status)) return false;
      if (!["pending", "reviewed", "all"].includes(status) && row.identity_status !== status) return false;
      if (action !== "all" && row.action !== action && !row.candidates.some(c => c.action === action)) return false;
      return true;
    });
    if (!filtered.some(row => row.army_path === currentPath)) currentPath = filtered[0]?.army_path || null;
    renderQueue();
    renderCurrent();
  }

  function renderQueue() {
    const row = current();
    const reviewedCount = state.assets.filter(item => reviewed(item.identity_status)).length;
    els.summary.textContent = `${reviewedCount} reviewed · ${state.assets.length} canonical assets · ${state.summary.identity_status?.["name-candidate"] || 0} name candidates`;
    els.queueCount.textContent = `${filtered.length} shown`;
    els.queue.innerHTML = filtered.map(item => {
      const label = item.subjects[0] || item.army_path;
      return `<button type="button" class="queue-item ${row?.army_path === item.army_path ? "active" : ""}" data-path="${esc(item.army_path)}">
        <span class="name"><span class="status ${esc(item.identity_status)}"></span>${esc(label)}</span>
        <span class="sub">${esc(item.identity_status)} · ${item.candidates.length} candidate${item.candidates.length === 1 ? "" : "s"}</span>
      </button>`;
    }).join("") || '<div class="empty">No assets match these filters.</div>';
    els.queue.querySelectorAll(".queue-item").forEach(button => button.addEventListener("click", () => {
      currentPath = button.dataset.path;
      activeCandidate = 0;
      renderQueue();
      renderCurrent();
    }));
    const index = row ? filtered.findIndex(item => item.army_path === row.army_path) : -1;
    els.position.textContent = index >= 0 ? `${index + 1} / ${filtered.length}` : "0 / 0";
  }

  function sideBySide(row) {
    const army = row.army_source ? `<article class="image-card"><header><div><strong>Current Army</strong><small>${esc(row.army_source.path)}</small></div></header><div class="image-wrap"><img src="${imageUrl("army", row.army_source.path)}" alt="Current Army emblem"></div></article>` : "";
    const candidates = row.candidates.map((candidate, index) => {
      const selected = selectedCandidates.has(candidate.path);
      return `<article class="image-card candidate ${index === activeCandidate ? "active-candidate" : ""}" data-index="${index}">
        <header><div><strong>${esc(candidate.subject)}</strong><small>${esc(candidate.tags.join(", ") || candidate.matched_by.join(", "))}</small></div>
        <label class="candidate-select"><input class="candidate-check" type="checkbox" value="${esc(candidate.path)}" ${selected ? "checked" : ""}> select</label></header>
        <div class="image-wrap"><img src="${imageUrl("vyo", candidate.path)}" alt="Vyo candidate ${esc(candidate.subject)}"></div>
      </article>`;
    }).join("");
    return `<div class="side-grid">${army}${candidates || '<div class="empty">No Vyo candidate is currently associated with this Army asset.</div>'}</div>`;
  }

  function overlay(row, blink) {
    if (!row.army_source || !row.candidates.length) return '<div class="empty">Overlay requires an Army source and at least one Vyo candidate.</div>';
    const candidate = row.candidates[Math.min(activeCandidate, row.candidates.length - 1)];
    const opacity = blink ? 1 : Number(els.opacity.value) / 100;
    return `<div class="overlay-stage"><img src="${imageUrl("army", row.army_source.path)}" alt="Current Army emblem"><img class="${blink ? "blink-top" : "overlay-top"}" style="opacity:${opacity}" src="${imageUrl("vyo", candidate.path)}" alt="Vyo candidate ${esc(candidate.subject)}"></div>
      <div class="overlay-label">Vyo: ${esc(candidate.path)}</div>`;
  }

  function renderComparison(row) {
    stopBlink();
    els.opacityWrap.classList.toggle("hidden", mode !== "overlay");
    els.blinkPause.classList.toggle("hidden", mode !== "blink");
    if (mode === "side") els.comparison.innerHTML = sideBySide(row);
    else els.comparison.innerHTML = overlay(row, mode === "blink");
    els.comparison.querySelectorAll(".candidate-check").forEach(input => input.addEventListener("change", () => {
      if (input.checked) selectedCandidates.add(input.value);
      else selectedCandidates.delete(input.value);
    }));
    els.comparison.querySelectorAll(".candidate").forEach(card => card.addEventListener("click", event => {
      if (event.target.closest("input")) return;
      activeCandidate = Number(card.dataset.index);
      renderComparison(row);
    }));
    if (mode === "blink" && row.candidates.length) startBlink();
  }

  function prefillDecision(row) {
    const review = row.review;
    let value = "unresolved";
    if (review?.status === "confirmed-missing") value = "missing";
    else if (review?.status === "reviewed-design-mismatch") value = "mismatch";
    else if (review?.status === "reviewed-match" && review.action === "minor-cleanup") value = "cleanup";
    else if (review?.status === "reviewed-match") value = "reuse";
    const radio = document.querySelector(`input[name="decision"][value="${value}"]`);
    if (radio) radio.checked = true;
    els.reasons.value = review?.reasons?.join(", ") || "";
    els.evidence.value = review?.evidence || "";
    els.confirmMissing.checked = false;
    updateMissingControl();
  }

  function renderCurrent() {
    const row = current();
    if (!row) {
      stopBlink();
      els.title.textContent = "No asset selected";
      els.meta.textContent = "";
      els.comparison.innerHTML = '<div class="empty">Adjust the filters to show review candidates.</div>';
      els.form.classList.add("hidden");
      return;
    }
    els.form.classList.remove("hidden");
    els.title.textContent = row.subjects.join(" / ") || row.army_path;
    els.meta.textContent = `${row.army_path} · ${row.identity_status}${row.profile_names.length ? " · profiles: " + row.profile_names.join(", ") : ""}`;
    activeCandidate = Math.min(activeCandidate, Math.max(0, row.candidates.length - 1));
    selectedCandidates = new Set(row.review?.vyo_paths || (row.candidates.length === 1 ? [row.candidates[0].path] : []));
    renderComparison(row);
    prefillDecision(row);
    const index = filtered.indexOf(row);
    els.previous.disabled = index <= 0;
    els.next.disabled = index < 0 || index >= filtered.length - 1;
    els.position.textContent = `${index + 1} / ${filtered.length}`;
    els.message.textContent = "";
    els.message.classList.remove("error");
  }

  function navigate(delta) {
    const row = current();
    const index = row ? filtered.indexOf(row) : -1;
    const next = filtered[index + delta];
    if (!next) return;
    currentPath = next.army_path;
    activeCandidate = 0;
    renderQueue();
    renderCurrent();
    document.querySelector(".queue-item.active")?.scrollIntoView({block: "nearest"});
  }

  function updateMissingControl() {
    const missing = decisionValue() === "missing";
    els.confirmWrap.classList.toggle("hidden", !missing);
    els.reasons.disabled = ["reuse", "unresolved", "missing"].includes(decisionValue());
    els.evidence.disabled = decisionValue() === "unresolved";
  }

  async function saveReview(event) {
    event.preventDefault();
    const row = current();
    if (!row) return;
    els.save.disabled = true;
    els.message.textContent = "Saving…";
    els.message.classList.remove("error");
    try {
      const payload = {
        army_path: row.army_path,
        decision: decisionValue(),
        vyo_paths: selectedPaths(),
        reasons: els.reasons.value.split(",").map(value => value.trim()).filter(Boolean),
        evidence: els.evidence.value.trim(),
        confirm_missing: els.confirmMissing.checked
      };
      const response = await fetch("/api/review", {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-Review-Token": state.review_token},
        body: JSON.stringify(payload)
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
      const oldIndex = filtered.indexOf(row);
      state = body;
      els.message.textContent = "Saved.";
      applyFilters();
      const nextRow = filtered[Math.min(Math.max(oldIndex, 0), Math.max(filtered.length - 1, 0))];
      if (nextRow) {
        currentPath = nextRow.army_path;
        activeCandidate = 0;
        renderQueue();
        renderCurrent();
      }
    } catch (error) {
      els.message.textContent = error.message;
      els.message.classList.add("error");
    } finally {
      els.save.disabled = false;
    }
  }

  async function load() {
    try {
      const response = await fetch("/api/state");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state = await response.json();
      applyFilters();
    } catch (error) {
      els.summary.textContent = `Failed to load: ${error.message}`;
    }
  }

  els.search.addEventListener("input", applyFilters);
  els.status.addEventListener("change", applyFilters);
  els.action.addEventListener("change", applyFilters);
  els.previous.addEventListener("click", () => navigate(-1));
  els.next.addEventListener("click", () => navigate(1));
  document.querySelectorAll(".mode").forEach(button => button.addEventListener("click", () => {
    mode = button.dataset.mode;
    document.querySelectorAll(".mode").forEach(item => item.classList.toggle("active", item === button));
    const row = current(); if (row) renderComparison(row);
  }));
  els.opacity.addEventListener("input", () => { const top = document.querySelector(".overlay-top"); if (top) top.style.opacity = String(Number(els.opacity.value) / 100); });
  els.blinkPause.addEventListener("click", () => {
    if (blinkTimer) { stopBlink(); els.blinkPause.textContent = "Resume blink"; }
    else startBlink();
  });
  document.querySelectorAll('input[name="decision"]').forEach(input => input.addEventListener("change", updateMissingControl));
  els.form.addEventListener("submit", saveReview);
  document.addEventListener("keydown", event => {
    if (event.target.matches("input, textarea, select")) return;
    if (event.key === "j") navigate(1);
    if (event.key === "k") navigate(-1);
  });
  load();
})();
