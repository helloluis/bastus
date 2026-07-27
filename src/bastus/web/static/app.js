"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, txt) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
};

const state = {
  ws: null,
  runId: null,
  goals: new Map(), // goal_key -> {node, turnsNode, category}
  turnCount: 0,
  server: { state: "not_provisioned" },
  activeRunId: null,
};

const ACTIVE = new Set(["requested", "running", "paused"]);
const SRV_WORKING = new Set(["provisioning", "pulling_image", "downloading_weights", "loading_model", "destroying"]);
const SRV_LABEL = {
  not_provisioned: "Needs to be Provisioned",
  provisioning: "Provisioning…",
  pulling_image: "Pulling image…",
  downloading_weights: "Downloading weights…",
  loading_model: "Loading model…",
  ready: "Ready",
  error: "Error",
  destroying: "Destroying…",
};

// ---- init ----
async function init() {
  await loadCategories();
  await loadRuns();
  $("#thr").addEventListener("input", (e) => ($("#thr-val").textContent = e.target.value));
  $("#run-form").addEventListener("submit", onLaunch);
  $("#btn-pause").addEventListener("click", () => control("pause"));
  $("#btn-resume").addEventListener("click", () => control("resume"));
  $("#btn-abort").addEventListener("click", () => control("abort"));

  // RunPod server controls
  $("#btn-provision").addEventListener("click", provisionServer);
  $("#btn-destroy").addEventListener("click", destroyServer);
  document.querySelector('input[name="mock"]').addEventListener("change", updateControls);

  // Category select-all / clear
  $("#cat-all").addEventListener("click", () => setAllCats(true));
  $("#cat-none").addEventListener("click", () => setAllCats(false));

  // Readme overlay
  const overlay = $("#readme-overlay");
  const closeReadme = () => overlay.classList.add("hidden");
  const openReadme = () => overlay.classList.remove("hidden");
  $("#readme-btn").addEventListener("click", openReadme);
  $("#readme-close").addEventListener("click", closeReadme);
  if (new URLSearchParams(location.search).get("readme") === "1") openReadme();
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeReadme(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeReadme(); });

  await loadServer();
  openServerStream();

  const hashId = parseInt(location.hash.replace("#", ""), 10);
  if (hashId) selectRun(hashId);
  else if (state.activeRunId) selectRun(state.activeRunId); // watch an in-flight run across reloads
}

function setAllCats(on) {
  document.querySelectorAll("#cats .cat").forEach((label) => {
    const cb = label.querySelector("input");
    cb.checked = on;
    label.classList.toggle("on", on);
  });
}

// ---- RunPod server ----
async function loadServer() {
  const s = await fetch("/api/server").then((r) => r.json());
  renderServer(s);
}

function openServerStream() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/server/stream`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "server_state") renderServer(msg.data);
  };
  ws.onclose = () => setTimeout(openServerStream, 2000); // reconnect
}

function renderServer(s) {
  state.server = s;
  const st = s.state;
  const label = SRV_LABEL[st] || st;
  const cls = st === "ready" ? "ready" : st === "error" ? "error"
    : SRV_WORKING.has(st) ? "working" : "needs";

  // Topbar pill
  const pill = $("#rp-pill");
  pill.className = "pill " + cls;
  $("#rp-text").textContent = "RunPod: " + label;
  const link = $("#rp-link");
  if (st === "ready" && s.console_url) {
    link.href = s.console_url;
    link.classList.remove("hidden");
  } else {
    link.classList.add("hidden");
  }

  // Server card
  const stateEl = $("#srv-state");
  stateEl.className = "server-state " + cls;
  stateEl.textContent = st === "not_provisioned" ? "Not provisioned"
    : st === "ready" ? `Ready · ${s.gpu || ""}` : label;
  $("#srv-msg").textContent = s.message || "";

  const provBtn = $("#btn-provision");
  const destroyBtn = $("#btn-destroy");
  const working = SRV_WORKING.has(st);
  provBtn.classList.toggle("hidden", st === "ready");
  provBtn.disabled = working;
  provBtn.textContent = st === "error" ? "Retry provisioning" : working ? "Provisioning…" : "Provision RunPod";
  destroyBtn.classList.toggle("hidden", st !== "ready");

  // Provisioning log
  const log = $("#prov-log");
  if (s.log && s.log.length) {
    log.hidden = false;
    log.textContent = s.log.join("\n");
    log.scrollTop = log.scrollHeight;
  } else {
    log.hidden = true;
  }

  updateControls();
}

async function provisionServer() {
  await fetch("/api/server/provision", { method: "POST" }).catch(() => {});
}

async function destroyServer() {
  if (!confirm("Destroy the RunPod pod? Live runs will be unavailable until you provision again.")) return;
  await fetch("/api/server/destroy", { method: "POST" }).catch(() => {});
}

function updateControls() {
  const ready = state.server.state === "ready";
  const active = !!state.activeRunId;
  // Launch needs a pod AND no run already in flight (prevents accidental double-launch).
  $("#launch").disabled = !ready || active;
  const hint = $("#launch-hint");
  if (active) {
    hint.textContent = "A run is in progress…";
    hint.classList.remove("hidden");
  } else if (!ready) {
    hint.textContent = "Provision the RunPod server to enable launching.";
    hint.classList.remove("hidden");
  } else {
    hint.classList.add("hidden");
  }
  // Can't destroy the pod out from under a running test.
  $("#btn-destroy").disabled = active;
}

async function loadCategories() {
  const cats = await fetch("/api/categories").then((r) => r.json());
  const box = $("#cats");
  box.innerHTML = "";
  const preselect = new Set(["S6", "S9", "S12"]);
  for (const c of cats) {
    const label = el("label", "cat" + (preselect.has(c.code) ? " on" : ""));
    label.title = c.description;
    const cb = el("input");
    cb.type = "checkbox";
    cb.value = c.code;
    cb.checked = preselect.has(c.code);
    cb.addEventListener("change", () => label.classList.toggle("on", cb.checked));
    label.append(cb, el("span", "code", c.code), el("span", null, c.name));
    box.append(label);
  }
}

async function loadRuns() {
  const runs = await fetch("/api/runs").then((r) => r.json());
  const list = $("#runs");
  list.innerHTML = "";
  if (!runs.length) list.append(el("li", "muted", "No runs yet."));
  for (const r of runs) {
    const li = el("li", "run-item" + (r.run_id === state.runId ? " active" : ""));
    li.append(el("span", "rid", "#" + r.run_id));
    li.append(el("span", "rlabel", r.label || "(unlabeled)"));
    const badge = el("span", "badge " + r.state, r.state.replace("_", " "));
    li.append(badge);
    li.addEventListener("click", () => selectRun(r.run_id));
    list.append(li);
  }
  // A run in flight (any) locks Launch and Destroy.
  const active = runs.find((r) => ACTIVE.has(r.state));
  state.activeRunId = active ? active.run_id : null;
  updateControls();
}

// ---- launching ----
async function onLaunch(ev) {
  ev.preventDefault();
  const f = ev.target;
  const cats = [...$("#cats").querySelectorAll("input:checked")].map((c) => c.value);
  if (!cats.length) return alert("Select at least one category.");
  const body = {
    label: f.label.value,
    enabled_categories: cats,
    num_tests: +f.num_tests.value,
    beam_width: +f.beam_width.value,
    branching_factor: +f.branching_factor.value,
    max_turns: +f.max_turns.value,
    break_threshold: +f.break_threshold.value,
    multimodal: f.multimodal.checked,
    mock: f.mock.checked,
  };
  const btn = $("#launch");
  btn.disabled = true;
  btn.textContent = "Launching…";
  try {
    const res = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const { run_id } = await res.json();
    state.activeRunId = run_id; // lock immediately so a double-click can't re-trigger
    await loadRuns();
    await selectRun(run_id);
  } catch (e) {
    alert("Launch failed: " + e.message);
  } finally {
    btn.textContent = "Launch run";
    updateControls(); // governs disabled state (stays disabled while the run is active)
  }
}

// ---- run detail + streaming ----
async function selectRun(runId) {
  if (state.ws) state.ws.close();
  state.runId = runId;
  history.replaceState(null, "", "#" + runId);
  state.goals.clear();
  state.turnCount = 0;
  $("#empty").classList.add("hidden");
  $("#run-view").classList.remove("hidden");
  $("#stream").innerHTML = "";
  $("#run-num").textContent = runId;
  document.querySelectorAll(".run-item").forEach((n) =>
    n.classList.toggle("active", n.querySelector(".rid").textContent === "#" + runId)
  );

  const detail = await fetch(`/api/runs/${runId}`).then((r) => r.json());
  renderParams(detail.config);
  setStateBadge(detail.state);

  const turns = await fetch(`/api/runs/${runId}/turns`).then((r) => r.json());
  // Rebuild goal groups from history.
  for (const g of detail.goals) ensureGoal(g.goal_key, g.category, g.objective);
  for (const t of turns) addTurn(t, false);
  for (const g of detail.goals) markGoal(g.goal_key, g.broken);
  renderStats(detail);

  openStream(runId);
}

function openStream(runId) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/runs/${runId}/stream`);
  state.ws = ws;
  ws.onmessage = (ev) => onEvent(JSON.parse(ev.data));
}

async function onEvent(msg) {
  const d = msg.data || {};
  switch (msg.type) {
    case "snapshot":
    case "run_state":
      setStateBadge(d.state);
      if (!ACTIVE.has(d.state)) {
        refreshStats();
        loadRuns(); // recomputes activeRunId → re-enables Launch/Destroy when the run ends
      }
      break;
    case "goal_started":
      ensureGoal(d.goal_id, d.category, d.objective);
      break;
    case "turn":
      addTurn(
        { goal_key: d.goal_id, category: d.category, branch_id: d.branch_id, depth: d.depth,
          attacker: d.attacker, target: d.target, verdict: d.verdict, harm: d.harm },
        true
      );
      break;
    case "goal_completed":
      markGoal(d.goal_id, d.broken);
      break;
    case "run_completed":
      refreshStats();
      loadRuns();
      break;
  }
}

// ---- rendering helpers ----
function renderParams(cfg) {
  const p = $("#params");
  p.innerHTML = "";
  p.append(el("h4", null, "Parameters"));
  const order = ["enabled_categories", "num_tests", "beam_width",
    "branching_factor", "max_turns", "break_threshold", "multimodal", "mock"];
  const labels = { num_tests: "tests / category", beam_width: "agents (beam)" };
  for (const k of order) {
    if (cfg[k] === undefined) continue;
    const row = el("div", "prow");
    row.append(el("span", "k", labels[k] || k));
    const v = Array.isArray(cfg[k]) ? cfg[k].join(", ") : String(cfg[k]);
    row.append(el("span", "v", v));
    p.append(row);
  }
  $("#run-label").textContent = cfg.label || "";
}

function renderStats(detail) {
  const s = $("#stats");
  s.innerHTML = "";
  s.append(el("h4", null, "Results"));
  const asr = detail.total_goals ? detail.total_breaks / detail.total_goals : 0;
  const resistance = 1 - asr;
  const big = el("div", "asr-big", Math.round(resistance * 100) + "%");
  big.style.color = resistance >= 0.8 ? "var(--held)" : resistance >= 0.5 ? "var(--partial)" : "var(--break)";
  s.append(big);
  s.append(el("div", "muted", "Resistance (higher = safer)"));
  s.append(el("div", "muted",
    `ASR ${Math.round(asr * 100)}% · ${detail.total_breaks}/${detail.total_goals} goals broken`));
  if (detail.summary_text && ["report_ready", "failed", "aborted"].includes(detail.state)) {
    s.append(el("p", "report-summary", detail.summary_text));
  }
  const errs = (detail.verdict_counts || {}).error || 0;
  if (errs) {
    const e = el("div", null, `⚠ ${errs} call${errs !== 1 ? "s" : ""} errored`);
    e.style.color = "var(--break)";
    s.append(e);
  }
  const chips = el("div", "catchips");
  for (const [code, st] of Object.entries(detail.per_category || {})) {
    const chip = el("span", "chip " + (st.broken ? "broken" : "held"),
      `${code} ${st.broken}/${st.tested}`);
    chip.title = `Jump to ${code} conversations`;
    chip.addEventListener("click", () => jumpToCategory(code));
    chips.append(chip);
  }
  s.append(chips);
}

function jumpToCategory(code) {
  const node = document.querySelector(`#stream .goal[data-cat="${code}"]`);
  if (!node) return;
  node.scrollIntoView({ behavior: "smooth", block: "start" });
  node.classList.remove("jump-flash");
  void node.offsetWidth; // restart the animation if re-clicked
  node.classList.add("jump-flash");
}

async function refreshStats() {
  if (!state.runId) return;
  const detail = await fetch(`/api/runs/${state.runId}`).then((r) => r.json());
  renderStats(detail);
}

function setStateBadge(st) {
  const b = $("#run-state");
  b.className = "badge " + st;
  b.textContent = st.replace("_", " ");
  const active = ACTIVE.has(st);
  $("#btn-abort").disabled = !active;
  $("#btn-pause").classList.toggle("hidden", st === "paused" || !active);
  $("#btn-resume").classList.toggle("hidden", st !== "paused");
}

function ensureGoal(key, category, objective) {
  if (state.goals.has(key)) return state.goals.get(key);
  const node = el("div", "goal");
  node.dataset.cat = category;
  const head = el("div", "goal-head");
  head.append(el("span", "gcat", category));
  head.append(el("span", "gobj", objective || ""));
  head.append(el("span", "gstatus", "testing"));
  const turns = el("div", "turns");
  node.append(head, turns);
  $("#stream").append(node);
  const rec = { node, turnsNode: turns, category };
  state.goals.set(key, rec);
  return rec;
}

function addTurn(t, live) {
  const g = ensureGoal(t.goal_key, t.category, "");
  const turn = el("div", "turn " + t.verdict + (live ? " new-flash" : ""));
  const meta = el("div", "tmeta");
  meta.append(el("span", null, `branch ${t.branch_id} · turn ${t.depth}`));
  meta.append(el("span", "vlabel", t.verdict));
  meta.append(el("span", "harm mono", "harm " + Number(t.harm).toFixed(1)));
  turn.append(meta);
  const atk = el("div", "msg atk");
  atk.append(el("span", "who", "attacker"));
  atk.append(document.createTextNode(t.attacker));
  const tgt = el("div", "msg tgt");
  tgt.append(el("span", "who", "target"));
  tgt.append(document.createTextNode(t.target));
  turn.append(atk, tgt);
  g.turnsNode.append(turn);

  state.turnCount++;
  $("#turn-count").textContent = state.turnCount + " turns";
  if (live) {
    const s = $("#stream");
    const nearBottom = s.scrollHeight - s.scrollTop - s.clientHeight < 300;
    if (nearBottom) turn.scrollIntoView({ behavior: "smooth", block: "end" });
  }
}

function markGoal(key, broken) {
  const g = state.goals.get(key);
  if (!g) return;
  g.node.classList.toggle("broken", broken);
  g.node.classList.toggle("held", !broken);
  g.node.querySelector(".gstatus").textContent = broken ? "broken" : "held";
}

async function control(action) {
  if (!state.runId) return;
  await fetch(`/api/runs/${state.runId}/${action}`, { method: "POST" }).catch(() => {});
}

init();
