// Live pipeline page (ADR 0008). Polls the ingestion API on this machine about once
// a second and moves each ingestion card to the column of its status.
"use strict";

const POLL_INTERVAL_MS = 1000;
const RECENT_INGESTIONS = 20;
const MAX_TOKENS = 40;
const MAX_BLOCKS = 500;

const cardsById = new Map();
const lastQueueCounts = new Map();

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

function showError(target, error) {
  target.textContent = error.code ? `${error.code}: ${error.message}` : error.message;
  target.hidden = false;
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
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    if (!data.get("document_type")) data.delete("document_type");
    button.disabled = true;
    message.className = "message";
    message.textContent = "Uploading…";
    try {
      const receipt = await getJson("/knowledge-items", { method: "POST", body: data });
      message.className = "message ok";
      message.textContent = `Queued as ingestion ${receipt.ingestion_id}.`;
      form.querySelector('input[type="file"]').value = "";
      refreshIngestions();
    } catch (error) {
      message.className = "message error";
      showError(message, error);
    } finally {
      button.disabled = false;
    }
  });
}

function relativeTime(isoTime) {
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(isoTime)) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function fillCard(card, ingestion) {
  const isRunning = ["extracting", "reading_pages"].includes(ingestion.status);
  const isCompleted = ingestion.status === "completed";
  card.className = `card${isRunning ? " running" : ""}${isCompleted ? " clickable" : ""}`;
  card.tabIndex = isCompleted ? 0 : -1;
  card.title = `Ingestion ${ingestion.ingestion_id}`;

  const meta = element("div", "meta");
  meta.append(
    element("span", "badge", ingestion.document_format),
    element("span", "", `attempts ${ingestion.attempts}`),
    element("span", "", relativeTime(ingestion.updated_at)),
  );
  if (ingestion.blocks_for_review !== null) {
    const review = element("span", ingestion.blocks_for_review ? "review" : "",
      `${ingestion.blocks_for_review} for review`);
    meta.append(review);
  }
  const parts = [element("div", "file", ingestion.source_file_name), meta];
  if (ingestion.failure_code) parts.push(element("div", "failure", ingestion.failure_code));
  card.replaceChildren(...parts);
}

function placeCards(ingestions) {
  const seen = new Set();
  const byStatus = new Map();
  for (const ingestion of ingestions) {
    seen.add(ingestion.ingestion_id);
    let entry = cardsById.get(ingestion.ingestion_id);
    if (!entry) {
      const card = element("article", "card");
      card.addEventListener("click", () => openBlocks(entry.ingestion));
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter") openBlocks(entry.ingestion);
      });
      entry = { card, status: null, ingestion };
      cardsById.set(ingestion.ingestion_id, entry);
    }
    entry.ingestion = ingestion;
    fillCard(entry.card, ingestion);
    if (!byStatus.has(ingestion.status)) byStatus.set(ingestion.status, []);
    byStatus.get(ingestion.status).push(entry);
  }

  for (const [id, entry] of cardsById) {
    if (!seen.has(id)) {
      entry.card.remove();
      cardsById.delete(id);
    }
  }

  for (const column of document.querySelectorAll(".column")) {
    const status = column.dataset.status;
    const container = column.querySelector(".cards");
    const entries = byStatus.get(status) || [];
    entries.forEach((entry, index) => {
      // Re-inserting a card restarts its arrival animation, so only cards that are
      // new or changed column are moved.
      if (container.children[index] !== entry.card) {
        container.insertBefore(entry.card, container.children[index] || null);
      }
      entry.status = status;
    });
    let heading = column.querySelector("h3 .count");
    if (!heading) {
      heading = element("span", "count");
      column.querySelector("h3").append(heading);
    }
    heading.textContent = String(entries.length);
  }
}

function drawTokens(container, ready, unacked) {
  const total = ready + unacked;
  const tokens = [];
  for (let index = 0; index < Math.min(unacked, MAX_TOKENS); index += 1) {
    tokens.push(element("span", "token unacked"));
  }
  for (let index = 0; index < Math.min(ready, MAX_TOKENS - tokens.length); index += 1) {
    tokens.push(element("span", "token"));
  }
  if (total > MAX_TOKENS) tokens.push(element("span", "token more", `+${total - MAX_TOKENS}`));
  container.replaceChildren(...tokens);
}

function updateQueue(name, ready, unacked, consumers) {
  const tile = document.querySelector(`.queue[data-queue="${name}"]`);
  if (!tile) return;
  const key = `${ready}/${unacked}/${consumers}`;
  if (lastQueueCounts.get(name) === key) return;
  const isFirstDraw = !lastQueueCounts.has(name);
  lastQueueCounts.set(name, key);

  const set = (field, value) => {
    const target = tile.querySelector(`[data-field="${field}"]`);
    if (target) target.textContent = String(value);
  };
  set("ready", ready);
  set("unacked", unacked);
  set("consumers", consumers);
  set("unpublished", ready);
  drawTokens(tile.querySelector('[data-field="tokens"]'), ready, unacked);
  if (!isFirstDraw) {
    tile.classList.add("changed");
    setTimeout(() => tile.classList.remove("changed"), 600);
  }
}

async function refreshIngestions() {
  const body = await getJson(`/knowledge-ingestions?limit=${RECENT_INGESTIONS}`);
  placeCards(body.ingestions);
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

async function openBlocks(ingestion) {
  if (ingestion.status !== "completed") return;
  const dialog = document.getElementById("blocks-dialog");
  const list = document.getElementById("blocks-list");
  const summary = document.getElementById("blocks-summary");
  document.getElementById("blocks-title").textContent = ingestion.source_file_name;
  summary.textContent = "Loading…";
  list.replaceChildren();
  dialog.showModal();
  try {
    const body = await getJson(
      `/knowledge-items/${encodeURIComponent(ingestion.item_id)}/versions/` +
      `${encodeURIComponent(ingestion.version_tag)}/content?limit=${MAX_BLOCKS}`,
    );
    const extraction = body.extraction;
    const pages = extraction.page_count === null ? "" : `${extraction.page_count} pages · `;
    summary.textContent =
      `${extraction.document_format.toUpperCase()} · ${pages}${extraction.block_count} blocks · ` +
      `${extraction.table_count} tables · ${extraction.lvm_block_count} read by the LVM · ` +
      `${extraction.blocks_for_review} for review`;
    list.replaceChildren(...body.blocks.map((block) => {
      const item = element("li", `block ${block.kind}${block.needs_human_review ? " needs-review" : ""}`);
      const head = element("div", "block-head");
      head.append(
        element("span", "", `#${block.order}`),
        element("span", "where", blockLocation(block)),
        element("span", `badge ${block.kind}`, block.kind),
      );
      if (block.source === "lvm") head.append(element("span", "badge lvm", "LVM"));
      if (block.needs_human_review) head.append(element("span", "badge review", "review"));
      item.append(head, element("p", "block-text", block.text));
      if (block.review_reason) item.append(element("p", "review-reason", block.review_reason));
      return item;
    }));
  } catch (error) {
    summary.textContent = error.code ? `${error.code}: ${error.message}` : error.message;
  }
}

document.getElementById("blocks-close").addEventListener("click", () => {
  document.getElementById("blocks-dialog").close();
});

loadNodes();
setUpUpload();
poll();
