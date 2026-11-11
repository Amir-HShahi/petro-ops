// Live pipeline page (ADR 0008). Polls the ingestion API on this machine about once
// a second: each recent ingestion is a card on the stage it is in, queue counts fill the
// stage stats, and the history list below keeps one row per ingestion.
"use strict";

const POLL_INTERVAL_MS = 1000;
const RECENT_INGESTIONS = 20;
const MAX_BLOCKS = 500;
const MAX_CHUNKS = 500;
const FLASH_MS = 6000;
const SHORT_ID_LENGTH = 8;

const STAGES = ["queued", "extracting", "reading_pages", "chunking"];
const STATUS_VIEWS = {
  queued: { label: "Queued", icon: "clock", tone: "attention" },
  extracting: { label: "Extracting", icon: "spinner", tone: "attention" },
  reading_pages: { label: "Reading pages", icon: "spinner", tone: "attention" },
  chunking: { label: "Chunking", icon: "spinner", tone: "attention" },
  completed: { label: "Completed", icon: "check", tone: "success" },
  failed: { label: "Failed", icon: "x", tone: "danger" },
};
// A card sits on the stage of its status; a failed ingestion sits in the failure lane.
const STAGE_KEYS = ["queued", "extracting", "reading_pages", "chunking", "completed", "failed"];
const WORKING_STAGES = ["queued", "extracting", "reading_pages", "chunking"];
const CARDS_PER_STAGE = { queued: 3, extracting: 3, reading_pages: 3, chunking: 3, completed: 3, failed: 3 };
const MOVE_MS = 800;
const ARRIVE_MS = 1000;
const FLAG_LABELS = {
  exact: "Exact duplicate of",
  near: "Near duplicate of",
  metadata_variant: "Metadata variant of",
  overlap: "Overlaps with",
};
const FILTERS = {
  all: () => true,
  active: (status) => status !== "completed" && status !== "failed",
  completed: (status) => status === "completed",
  failed: (status) => status === "failed",
};

const rowsById = new Map();
const cardsById = new Map();
const stageCounts = new Map();
const queueCounts = new Map();
const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
let activeFilter = "all";
let flashTimer = null;

const live = document.getElementById("live");
const liveText = document.getElementById("live-text");
const boardError = document.getElementById("board-error");
const brokerError = document.getElementById("broker-error");

async function getJson(url, options) {
  const response = await fetch(url, { cache: "no-store", ...options });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(body && body.detail ? body.detail : `HTTP ${response.status}`);
    error.code = body && body.type;
    throw error;
  }
  return body;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Only fixed icon names from this file reach the markup, never text from the API.
function icon(name) {
  const holder = document.createElement("span");
  const spin = name === "spinner" ? " spin" : "";
  holder.innerHTML =
    `<svg class="icon${spin}" width="16" height="16" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
  return holder.firstChild;
}

function statusIcon(view) {
  const holder = element("span", `status-icon tone-${view.tone}`);
  holder.append(icon(view.icon));
  return holder;
}

function showError(target, error) {
  target.textContent = error.code ? `${error.code}: ${error.message}` : error.message;
  target.hidden = false;
}

function showFlash(text) {
  document.getElementById("flash-text").textContent = text;
  document.getElementById("flash").hidden = false;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { document.getElementById("flash").hidden = true; }, FLASH_MS);
}

async function loadNodes() {
  const select = document.getElementById("node-select");
  try {
    const body = await getJson("/nodes");
    select.replaceChildren(element("option", "", "Pick a Node"));
    select.firstChild.value = "";
    for (const node of body.nodes) {
      const option = element("option", "", node.node_id);
      option.value = node.node_id;
      select.append(option);
    }
  } catch (error) {
    select.replaceChildren(element("option", "", "Node registry unavailable"));
    showError(document.getElementById("upload-message"), error);
  }
}

function setUpUpload() {
  const form = document.getElementById("upload-form");
  const button = document.getElementById("upload-button");
  const fileInput = document.getElementById("file-input");
  const message = document.getElementById("upload-message");
  const toggle = document.getElementById("submit-toggle");
  const popover = document.getElementById("submit-popover");

  const setOpen = (isOpen) => {
    popover.hidden = !isOpen;
    toggle.setAttribute("aria-expanded", String(isOpen));
  };
  toggle.addEventListener("click", () => setOpen(popover.hidden));
  document.addEventListener("click", (event) => {
    if (!popover.hidden && !event.target.closest(".submit-menu")) setOpen(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !popover.hidden) {
      setOpen(false);
      toggle.focus();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const files = Array.from(fileInput.files);
    const shared = new FormData(form);
    shared.delete("file");
    if (!shared.get("document_type")) shared.delete("document_type");
    button.disabled = true;
    message.className = "message";

    // The API takes one file per request, so each file gets its own ingestion. One
    // refused file must not stop the others.
    const failed = [];
    let queued = 0;
    for (const [index, file] of files.entries()) {
      message.textContent = `Uploading ${index + 1} of ${files.length}…`;
      const body = new FormData();
      for (const [name, value] of shared) body.append(name, value);
      body.append("file", file);
      try {
        await getJson("/knowledge-items", { method: "POST", body });
        queued += 1;
      } catch (error) {
        failed.push({ file, error });
      }
    }

    if (queued > 0) {
      showFlash(queued === 1 ? "Queued 1 file." : `Queued ${queued} files.`);
      refreshIngestions();
    }
    if (failed.length === 0) {
      message.textContent = "";
      form.reset();
      setOpen(false);
    } else {
      // Leave only the refused files selected, so Submit retries just those.
      const remaining = new DataTransfer();
      for (const { file } of failed) remaining.items.add(file);
      fileInput.files = remaining.files;
      message.className = "message error";
      message.textContent = failed
        .map(({ file, error }) => `${file.name}: ${error.code ? `${error.code}: ` : ""}${error.message}`)
        .join("\n");
    }
    button.disabled = false;
  });
  document.getElementById("flash-close").addEventListener("click", () => {
    document.getElementById("flash").hidden = true;
  });
}

function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function relativeTime(isoTime) {
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(isoTime)) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function stageTrack(status) {
  const position = STAGES.indexOf(status);
  const track = element("ol", "stage-track");
  track.setAttribute("aria-label", `Stage: ${STATUS_VIEWS[status].label}`);
  STAGES.forEach((stage, index) => {
    const step = element("li", "stage");
    if (status === "completed" || index < position) step.dataset.state = "done";
    else step.dataset.state = index === position ? "current" : "todo";
    step.title = STATUS_VIEWS[stage].label;
    track.append(step);
  });
  return track;
}

function timeLine(iconName) {
  const line = element("span", "time-line");
  const text = element("span");
  line.append(icon(iconName), text);
  return { line, text };
}

function createRow() {
  const entry = { row: element("li", "ingestion-row"), ingestion: null, signature: null };
  // The title is a button only for completed ingestions, so a click anywhere on the row
  // and Enter on the focused title both land here.
  entry.row.addEventListener("click", () => {
    if (entry.ingestion.status === "completed") openBlocks(entry.ingestion);
  });
  return entry;
}

function fillRow(entry) {
  const { row, ingestion } = entry;
  const view = STATUS_VIEWS[ingestion.status];
  const isCompleted = ingestion.status === "completed";
  row.className = `ingestion-row${isCompleted ? " is-clickable" : ""}`;
  row.dataset.status = ingestion.status;
  row.title = `Ingestion ${ingestion.ingestion_id}`;

  const title = element(isCompleted ? "button" : "span", "ingestion-title", ingestion.source_file_name);
  if (isCompleted) title.type = "button";
  const headline = element("div", "ingestion-headline");
  headline.append(title, element("span", "pill", ingestion.document_format.toUpperCase()));
  if (isCompleted) headline.append(actionButton("Chunks", () => openChunks(ingestion)));

  const meta = element("p", "ingestion-meta");
  meta.append(element(
    "span",
    "",
    `${view.label} · #${ingestion.ingestion_id.slice(0, SHORT_ID_LENGTH)} · attempts ${ingestion.attempts}`,
  ));
  if (ingestion.chunk_count !== null) meta.append(element("span", "pill", `${ingestion.chunk_count} chunks`));
  if (ingestion.blocks_for_review) {
    meta.append(element("span", "pill attention", `${ingestion.blocks_for_review} for review`));
  }
  if (ingestion.duplicate_flag_count) {
    const count = ingestion.duplicate_flag_count;
    meta.append(element("span", "pill attention", `${count} duplicate flag${count === 1 ? "" : "s"}`));
  }
  if (ingestion.failure_code) meta.append(element("span", "failure", ingestion.failure_code));

  const main = element("div");
  main.append(headline, meta);

  const age = timeLine("calendar");
  const duration = timeLine("stopwatch");
  const times = element("div", "ingestion-times");
  times.append(age.line, duration.line);
  entry.ageText = age.text;
  entry.durationText = duration.text;

  // A failed ingestion has no stage to mark, so its track cell stays empty to keep the columns aligned.
  const track = ingestion.status === "failed" ? element("span") : stageTrack(ingestion.status);
  row.replaceChildren(statusIcon(view), main, track, times);
}

// A finished ingestion stops counting at its last update; a running one counts up to now.
function refreshTimes(entry) {
  const { ingestion } = entry;
  const isFinished = ingestion.status === "completed" || ingestion.status === "failed";
  const end = isFinished ? Date.parse(ingestion.updated_at) : Date.now();
  entry.ageText.textContent = relativeTime(ingestion.updated_at);
  entry.durationText.textContent = formatDuration((end - Date.parse(ingestion.created_at)) / 1000);
}

function applyFilter() {
  let visible = 0;
  for (const entry of rowsById.values()) {
    entry.row.hidden = !FILTERS[activeFilter](entry.ingestion.status);
    if (!entry.row.hidden) visible += 1;
  }
  const empty = document.getElementById("ingestions-empty");
  empty.hidden = visible > 0;
  empty.textContent = rowsById.size === 0
    ? "No ingestions yet. Submit files to start one."
    : "No ingestions match this filter.";
}

function placeRows(ingestions) {
  const list = document.getElementById("ingestions");
  const seen = new Set();
  ingestions.forEach((ingestion, index) => {
    seen.add(ingestion.ingestion_id);
    let entry = rowsById.get(ingestion.ingestion_id);
    if (!entry) {
      entry = createRow();
      rowsById.set(ingestion.ingestion_id, entry);
    }
    const signature = JSON.stringify(ingestion);
    if (entry.signature !== signature) {
      entry.ingestion = ingestion;
      entry.signature = signature;
      fillRow(entry);
    }
    refreshTimes(entry);
    if (list.children[index] !== entry.row) list.insertBefore(entry.row, list.children[index] || null);
  });

  for (const [id, entry] of rowsById) {
    if (!seen.has(id)) {
      entry.row.remove();
      rowsById.delete(id);
    }
  }

  for (const [name, matches] of Object.entries(FILTERS)) {
    const count = String(ingestions.filter((ingestion) => matches(ingestion.status)).length);
    for (const target of document.querySelectorAll(`[data-count="${name}"]`)) target.textContent = count;
  }
  placeCards(ingestions);
  applyFilter();
}

function setUpFilters() {
  const buttons = document.querySelectorAll("[data-filter]");
  for (const button of buttons) {
    button.addEventListener("click", () => {
      activeFilter = button.dataset.filter;
      for (const other of buttons) other.setAttribute("aria-pressed", String(other === button));
      applyFilter();
    });
  }
}

function stageElement(key) {
  return document.querySelector(`.station[data-station="${key}"]`);
}

function stageOf(status) {
  return status === "failed" ? "failed" : status;
}

function createCard(ingestion) {
  return { el: element("li", "chip"), ingestion, signature: null, stage: null };
}

function fillCard(entry) {
  const { el, ingestion } = entry;
  el.dataset.stage = stageOf(ingestion.status);
  el.title = `Ingestion ${ingestion.ingestion_id}`;

  // A break hint after each _, . or - keeps long names from splitting inside a word.
  const name = element("span", "chip-name");
  name.dir = "auto";
  name.append(...ingestion.source_file_name.split(/(?<=[_.-])/).flatMap((part) => [part, document.createElement("wbr")]));
  const meta = element("span", "chip-meta");
  entry.timeText = element("span", "chip-time");
  meta.append(element("span", "pill", ingestion.document_format.toUpperCase()), entry.timeText);
  if (ingestion.attempts > 1) meta.append(element("span", "pill attention", `attempt ${ingestion.attempts}`));
  if (ingestion.chunk_count !== null) meta.append(element("span", "pill", `${ingestion.chunk_count} chunks`));
  if (ingestion.failure_code) meta.append(element("span", "chip-failure", ingestion.failure_code));
  el.replaceChildren(name, meta);
  if (ingestion.status === "completed") {
    const actions = element("span", "chip-actions");
    actions.append(
      actionButton("Chunks", () => openChunks(ingestion)),
      actionButton("Blocks", () => openBlocks(ingestion)),
    );
    el.append(actions);
  }
}

function actionButton(label, onClick) {
  const button = element("button", "chip-action", label);
  button.type = "button";
  button.addEventListener("click", (event) => {
    // The history rows open the blocks on a click anywhere; this button must not also do that.
    event.stopPropagation();
    onClick();
  });
  return button;
}

function refreshCardTime(entry) {
  const { ingestion } = entry;
  const isFinished = ingestion.status === "completed" || ingestion.status === "failed";
  const end = isFinished ? Date.parse(ingestion.updated_at) : Date.now();
  entry.timeText.textContent = formatDuration((end - Date.parse(ingestion.created_at)) / 1000);
}

// A card that moved is animated from where it was to where it is now (FLIP), so the
// audience sees the document travel to the next stage instead of blinking there.
function animateCards(before) {
  if (prefersReducedMotion.matches) return;
  for (const [id, entry] of cardsById) {
    if (entry.el.hidden) continue;
    const to = entry.el.getBoundingClientRect();
    const from = before.get(id);
    const frames = from
      ? [{ transform: `translate(${from.left - to.left}px, ${from.top - to.top}px)` }, { transform: "none" }]
      : [{ opacity: 0, transform: "translateY(-1rem) scale(0.95)" }, { opacity: 1, transform: "none" }];
    if (from && Math.abs(from.left - to.left) < 2 && Math.abs(from.top - to.top) < 2) continue;
    entry.el.classList.add("is-moving");
    const animation = entry.el.animate(frames, { duration: MOVE_MS, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" });
    animation.finished.then(() => entry.el.classList.remove("is-moving"), () => {});
  }
}

function placeCards(ingestions) {
  const before = new Map();
  for (const [id, entry] of cardsById) {
    if (!entry.el.hidden && entry.el.isConnected) before.set(id, entry.el.getBoundingClientRect());
  }

  const byStage = new Map(STAGE_KEYS.map((key) => [key, []]));
  const seen = new Set();
  for (const ingestion of ingestions) {
    seen.add(ingestion.ingestion_id);
    let entry = cardsById.get(ingestion.ingestion_id);
    if (!entry) {
      entry = createCard(ingestion);
      cardsById.set(ingestion.ingestion_id, entry);
    }
    const signature = JSON.stringify(ingestion);
    if (entry.signature !== signature) {
      entry.ingestion = ingestion;
      entry.signature = signature;
      fillCard(entry);
    }
    refreshCardTime(entry);
    byStage.get(stageOf(ingestion.status)).push(entry);
  }
  for (const [id, entry] of cardsById) {
    if (!seen.has(id)) {
      entry.el.remove();
      cardsById.delete(id);
    }
  }

  for (const [key, entries] of byStage) {
    const station = stageElement(key);
    const list = station.querySelector("[data-chips]");
    const isFinished = key === "completed" || key === "failed";
    // Waiting stages show the oldest first, as a queue; finished stages show the newest.
    const direction = isFinished ? -1 : 1;
    entries.sort((a, b) => direction * (Date.parse(a.ingestion.created_at) - Date.parse(b.ingestion.created_at)));
    const limit = CARDS_PER_STAGE[key];
    entries.forEach((entry, index) => {
      entry.el.hidden = index >= limit;
      if (list.children[index] !== entry.el) list.insertBefore(entry.el, list.children[index] || null);
      if (entry.stage !== null && entry.stage !== key) flashStage(station);
      entry.stage = key;
    });

    let more = list.querySelector(".chips-more");
    if (!more) more = element("li", "chips-more");
    more.hidden = entries.length <= limit;
    more.textContent = `+${entries.length - limit} more`;
    if (list.lastElementChild !== more) list.append(more);

    stageCounts.set(key, entries.length);
    station.querySelector('[data-field="count"]').textContent = String(entries.length);
  }

  animateCards(before);
  refreshBoardState();
}

function flashStage(station) {
  if (prefersReducedMotion.matches) return;
  station.classList.remove("arrived");
  // Reading the layout restarts the animation when a stage is hit twice in a row.
  void station.offsetWidth;
  station.classList.add("arrived");
  setTimeout(() => station.classList.remove("arrived"), ARRIVE_MS);
}

function queueDepth(name) {
  return queueCounts.get(name) || { ready: 0, unacked: 0, consumers: 0 };
}

function refreshBoardState() {
  const isBusy = (key) => {
    const depth = queueDepth(stageElement(key).dataset.queue);
    return (stageCounts.get(key) || 0) > 0 || depth.ready > 0 || depth.unacked > 0;
  };
  for (const key of WORKING_STAGES) stageElement(key).dataset.state = isBusy(key) ? "busy" : "idle";
  stageElement("completed").dataset.state = (stageCounts.get("completed") || 0) > 0 ? "done" : "idle";
  stageElement("failed").dataset.state = (stageCounts.get("failed") || 0) > 0 ? "failed" : "idle";
  stageElement("retry").dataset.state = isBusy("retry") ? "busy" : "idle";
  stageElement("dlq").dataset.state = isBusy("dlq") ? "failed" : "idle";

  // A connector moves when work waits before it or is being done after it.
  WORKING_STAGES.forEach((key, index) => {
    const next = WORKING_STAGES[index + 1];
    const isFlowing = isBusy(key) || (next !== undefined && isBusy(next));
    document.querySelector(`.link[data-after="${key}"]`).dataset.flow = isFlowing ? "on" : "off";
  });
}

function updateQueue(name, ready, unacked, consumers) {
  const node = document.querySelector(`[data-queue="${name}"]`);
  if (!node) return;
  const previous = queueCounts.get(name);
  if (previous && previous.ready === ready && previous.unacked === unacked && previous.consumers === consumers) return;
  queueCounts.set(name, { ready, unacked, consumers });

  const set = (field, value) => {
    const target = node.querySelector(`[data-field="${field}"]`);
    if (target) target.textContent = String(value);
  };
  set("ready", ready);
  set("unacked", unacked);
  set("consumers", consumers);
  set("unpublished", ready);
  // The retry and dead-letter stages have no ingestion cards, so their big number is the queue.
  if (name === "ingestion.retry" || name === "ingestion.dlq") set("count", ready + unacked);

  if (previous) {
    const stats = node.querySelector(".station-stats");
    stats.classList.add("changed");
    setTimeout(() => stats.classList.remove("changed"), 600);
  }
}

function setUpPresent() {
  const root = document.documentElement;
  const button = document.getElementById("present-toggle");
  const setPresenting = (isOn) => {
    root.toggleAttribute("data-present", isOn);
    button.setAttribute("aria-pressed", String(isOn));
  };
  button.addEventListener("click", async () => {
    const isOn = !root.hasAttribute("data-present");
    setPresenting(isOn);
    try {
      if (isOn) await root.requestFullscreen();
      else if (document.fullscreenElement) await document.exitFullscreen();
    } catch {
      // The browser may refuse fullscreen; the larger layout still applies.
    }
  });
  // Leaving fullscreen with Esc ends presenting too; without fullscreen Esc does it alone.
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement) setPresenting(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && root.hasAttribute("data-present")) setPresenting(false);
  });
}

async function refreshIngestions() {
  const body = await getJson(`/knowledge-ingestions?limit=${RECENT_INGESTIONS}`);
  placeRows(body.ingestions);
  boardError.hidden = true;
}

async function refreshQueues() {
  try {
    const body = await getJson("/ingestion-queues");
    updateQueue("outbox", body.unpublished_outbox_messages, 0, 0);
    for (const queue of body.queues) {
      updateQueue(queue.queue, queue.messages_ready, queue.messages_unacked, queue.consumers);
    }
    refreshBoardState();
    brokerError.hidden = true;
  } catch (error) {
    showError(brokerError, error);
  }
}

async function poll() {
  try {
    await Promise.all([
      refreshIngestions().catch((error) => { showError(boardError, error); throw error; }),
      refreshQueues(),
    ]);
    live.dataset.state = "live";
    liveText.textContent = `Live · ${new Date().toLocaleTimeString()}`;
  } catch {
    live.dataset.state = "down";
    liveText.textContent = "API not answering";
  } finally {
    setTimeout(poll, POLL_INTERVAL_MS);
  }
}

function blockLocation(block) {
  if (block.page_number !== null) return `Page ${block.page_number}`;
  if (block.heading_path.length) return block.heading_path.join(" › ");
  return "Before the first heading";
}

function flagRow(flag) {
  const row = element("li", "annotation");
  const warning = element("span", "status-icon tone-attention");
  warning.append(icon("warning"));
  row.append(
    warning,
    element("strong", "", FLAG_LABELS[flag.kind] || `${flag.kind} of`),
    element("span", "existing", `${flag.existing_item_id} ${flag.existing_version_tag}`),
    element("span", "score", `score ${flag.score}`),
  );
  if (flag.is_ambiguous) row.append(element("span", "pill attention", "ambiguous"));
  return row;
}

async function openBlocks(ingestion) {
  if (ingestion.status !== "completed") return;
  const dialog = document.getElementById("blocks-dialog");
  const list = document.getElementById("blocks-list");
  const flags = document.getElementById("blocks-flags");
  const flagsSection = document.getElementById("blocks-flags-section");
  const summary = document.getElementById("blocks-summary");
  const titleIcon = document.getElementById("blocks-icon");
  document.getElementById("blocks-title").textContent = ingestion.source_file_name;
  titleIcon.replaceChildren(icon(STATUS_VIEWS.completed.icon));
  summary.textContent = "Loading…";
  list.replaceChildren();
  flags.replaceChildren();
  flagsSection.hidden = true;
  dialog.showModal();
  try {
    const status = await getJson(`/knowledge-ingestions/${encodeURIComponent(ingestion.ingestion_id)}`);
    flags.replaceChildren(...status.duplicate_flags.map(flagRow));
    flagsSection.hidden = status.duplicate_flags.length === 0;
    const body = await getJson(
      `/knowledge-items/${encodeURIComponent(ingestion.item_id)}/versions/` +
      `${encodeURIComponent(ingestion.version_tag)}/content?limit=${MAX_BLOCKS}`,
    );
    const extraction = body.extraction;
    const pages = extraction.page_count === null ? "" : `${extraction.page_count} pages · `;
    summary.textContent =
      `${extraction.document_format.toUpperCase()} · ${pages}${extraction.block_count} blocks · ` +
      `${extraction.table_count} tables · ${extraction.lvm_block_count} read by the LVM · ` +
      `${extraction.blocks_for_review} for review · ${status.chunk_count} chunks`;
    list.replaceChildren(...body.blocks.map((block) => {
      const item = element("li", `block ${block.kind}${block.needs_human_review ? " needs-review" : ""}`);
      const head = element("div", "block-head");
      head.append(
        element("span", "where", blockLocation(block)),
        element("span", "pill", block.kind),
      );
      if (block.source === "lvm") head.append(element("span", "pill accent", "LVM"));
      if (block.needs_human_review) head.append(element("span", "pill attention", "review"));
      // Documents may be in Persian, so each block picks its own text direction.
      const text = element("pre", "block-text", block.text);
      text.dir = "auto";
      const blockBody = element("div", "block-body");
      blockBody.append(head, text);
      if (block.review_reason) blockBody.append(element("p", "review-reason", block.review_reason));
      item.append(element("span", "block-number", String(block.order)), blockBody);
      return item;
    }));
  } catch (error) {
    summary.textContent = error.code ? `${error.code}: ${error.message}` : error.message;
  }
}

function chunkLocation(chunk) {
  const pages = chunk.page_start === null ? "" : (
    chunk.page_start === chunk.page_end ? `Page ${chunk.page_start}` : `Pages ${chunk.page_start}–${chunk.page_end}`
  );
  const headings = chunk.heading_path.join(" › ");
  return [pages, headings].filter(Boolean).join(" · ") || "Before the first heading";
}

async function openChunks(ingestion) {
  if (ingestion.status !== "completed") return;
  const dialog = document.getElementById("chunks-dialog");
  const list = document.getElementById("chunks-list");
  const summary = document.getElementById("chunks-summary");
  document.getElementById("chunks-title").textContent = ingestion.source_file_name;
  document.getElementById("chunks-icon").replaceChildren(icon(STATUS_VIEWS.completed.icon));
  summary.textContent = "Loading…";
  list.replaceChildren();
  dialog.showModal();
  try {
    const body = await getJson(
      `/knowledge-items/${encodeURIComponent(ingestion.item_id)}/versions/` +
      `${encodeURIComponent(ingestion.version_tag)}/chunks?limit=${MAX_CHUNKS}`,
    );
    const retrieval = body.is_retrievable
      ? "retrievable"
      : `not retrievable, ${body.active_version_tag} is the active version`;
    const shown = body.chunks.length < body.chunk_count ? `first ${body.chunks.length} of ` : "";
    summary.textContent = `${body.version_tag} · ${shown}${body.chunk_count} chunks · ${retrieval}`;
    list.replaceChildren(...body.chunks.map((chunk) => {
      const item = element("li", "block paragraph");
      const head = element("div", "block-head");
      head.append(
        element("span", "where", chunkLocation(chunk)),
        element("span", "pill", `${chunk.token_count} tokens`),
        element("span", "pill", `blocks ${chunk.first_block_order}–${chunk.last_block_order}`),
      );
      // Documents may be in Persian, so each chunk picks its own text direction.
      const text = element("pre", "block-text", chunk.text);
      text.dir = "auto";
      const chunkBody = element("div", "block-body");
      chunkBody.append(head, text);
      item.append(element("span", "block-number", String(chunk.order)), chunkBody);
      return item;
    }));
  } catch (error) {
    summary.textContent = error.code ? `${error.code}: ${error.message}` : error.message;
  }
}

for (const name of ["blocks", "chunks"]) {
  const dialog = document.getElementById(`${name}-dialog`);
  document.getElementById(`${name}-close`).addEventListener("click", () => dialog.close());
  // A click on the backdrop lands on the dialog element itself, not on its content.
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

loadNodes();
setUpUpload();
setUpFilters();
setUpPresent();
poll();
