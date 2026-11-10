// Live pipeline page (ADR 0008). Polls the ingestion API on this machine about once
// a second: queue counts fill the graph and each recent ingestion is a row in the list.
"use strict";

const POLL_INTERVAL_MS = 1000;
const RECENT_INGESTIONS = 20;
const MAX_BLOCKS = 500;
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
const QUEUE_STATE_VIEWS = {
  idle: { icon: "circle", tone: "neutral" },
  waiting: { icon: "clock", tone: "attention" },
  running: { icon: "spinner", tone: "attention" },
  failed: { icon: "x", tone: "danger" },
};
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
const lastQueueCounts = new Map();
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
    const formData = new FormData(form);
    if (!formData.get("document_type")) formData.delete("document_type");
    button.disabled = true;
    message.className = "message";
    message.textContent = "Uploading…";
    try {
      const receipt = await getJson("/knowledge-items", { method: "POST", body: formData });
      message.textContent = "";
      form.reset();
      setOpen(false);
      showFlash(`Queued as ingestion ${receipt.ingestion_id}.`);
      refreshIngestions();
    } catch (error) {
      message.className = "message error";
      showError(message, error);
    } finally {
      button.disabled = false;
    }
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
    ? "No ingestions yet. Submit a file to start one."
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
    const count = ingestions.filter((ingestion) => matches(ingestion.status)).length;
    document.querySelector(`[data-count="${name}"]`).textContent = String(count);
  }
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

function queueState(name, ready, unacked) {
  if (name === "ingestion.dlq" && ready > 0) return "failed";
  if (unacked > 0) return "running";
  return ready > 0 ? "waiting" : "idle";
}

function updateQueue(name, ready, unacked, consumers) {
  const node = document.querySelector(`.queue-node[data-queue="${name}"]`);
  if (!node) return;
  const key = `${ready}/${unacked}/${consumers}`;
  if (lastQueueCounts.get(name) === key) return;
  const isFirstDraw = !lastQueueCounts.has(name);
  lastQueueCounts.set(name, key);

  const set = (field, value) => {
    const target = node.querySelector(`[data-field="${field}"]`);
    if (target) target.textContent = String(value);
  };
  set("ready", ready);
  set("unacked", unacked);
  set("consumers", consumers);
  set("unpublished", ready);

  const state = queueState(name, ready, unacked);
  const view = QUEUE_STATE_VIEWS[state];
  node.dataset.state = state;
  const marker = node.querySelector('[data-field="icon"]');
  marker.className = `status-icon tone-${view.tone}`;
  marker.replaceChildren(icon(view.icon));

  if (!isFirstDraw) {
    node.classList.add("changed");
    setTimeout(() => node.classList.remove("changed"), 600);
  }
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

const blocksDialog = document.getElementById("blocks-dialog");
document.getElementById("blocks-close").addEventListener("click", () => blocksDialog.close());
// A click on the backdrop lands on the dialog element itself, not on its content.
blocksDialog.addEventListener("click", (event) => {
  if (event.target === blocksDialog) blocksDialog.close();
});

loadNodes();
setUpUpload();
setUpFilters();
poll();
