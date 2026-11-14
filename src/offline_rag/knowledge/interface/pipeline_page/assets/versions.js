// Versions and duplicates page (spec §7.6, §7.7). Lists the items behind the recent
// ingestions and shows one item's version history, the lifecycle of each version's chunks
// and the duplicate flags raised for them. It polls only while its page is open.
"use strict";

const ITEM_POLL_MS = 2000;
const ITEMS_FROM_INGESTIONS = 100;
const HASH_PREVIEW_LENGTH = 12;
const FLAG_EXPLANATIONS = {
  exact: "Same file, byte for byte",
  near: "Same normalized text in a different file",
  metadata_variant: "Same text, different metadata",
  overlap: "Chunks repeat text of the other item",
};

let selectedItemId = null;
let itemPollTimer = null;
let itemListSignature = null;
let itemDetailSignature = null;

function isKnowledgeViewOpen() {
  return !document.querySelector('[data-view="knowledge"]').hidden;
}

function groupItems(ingestions) {
  const items = new Map();
  for (const ingestion of ingestions) {
    let item = items.get(ingestion.item_id);
    if (!item) {
      // Ingestions arrive newest first, so the first one seen is the latest.
      item = { item_id: ingestion.item_id, latest: ingestion, versions: new Set(), flags: 0 };
      items.set(ingestion.item_id, item);
    }
    item.versions.add(ingestion.version_tag);
    item.flags += ingestion.duplicate_flag_count || 0;
  }
  return Array.from(items.values());
}

function itemRow(item) {
  const row = element("li", "item-row");
  const button = element("button", "item-button");
  button.type = "button";
  button.setAttribute("aria-pressed", String(item.item_id === selectedItemId));
  const name = element("span", "item-name", item.latest.source_file_name);
  name.dir = "auto";
  const meta = element("span", "item-meta");
  meta.append(
    element("span", "pill", `${item.versions.size} version${item.versions.size === 1 ? "" : "s"}`),
    element("span", "pill", `#${item.item_id.slice(0, SHORT_ID_LENGTH)}`),
  );
  if (item.flags) meta.append(element("span", "pill attention", `${item.flags} flag${item.flags === 1 ? "" : "s"}`));
  button.append(name, meta);
  button.addEventListener("click", () => showItem(item.item_id));
  row.append(button);
  return row;
}

function setCount(name, value) {
  for (const target of document.querySelectorAll(`[data-know-count="${name}"]`)) target.textContent = String(value);
}

async function refreshItemList() {
  const errorBox = document.getElementById("item-list-error");
  try {
    const body = await getJson(`/knowledge-ingestions?limit=${ITEMS_FROM_INGESTIONS}`);
    const items = groupItems(body.ingestions);
    const signature = JSON.stringify([items.map((item) => [item.item_id, item.versions.size, item.flags]), selectedItemId]);
    errorBox.hidden = true;
    if (signature === itemListSignature) return;
    itemListSignature = signature;
    document.getElementById("item-list").replaceChildren(...items.map(itemRow));
    document.getElementById("item-list-empty").hidden = items.length > 0;
    setCount("items", items.length);
    setCount("versions", items.reduce((total, item) => total + item.versions.size, 0));
    setCount("flags", body.ingestions.reduce((total, ingestion) => total + (ingestion.duplicate_flag_count || 0), 0));
  } catch (error) {
    showError(errorBox, error);
  }
}

function lifecycleStep(label, state) {
  const step = element("li", "lifecycle-step", label);
  step.dataset.state = state;
  return step;
}

// Published → Chunked → Active or Superseded. Only the active version's chunks are retrievable.
function lifecycle(version) {
  const track = element("ol", "lifecycle");
  const isChunked = version.chunk_count > 0;
  track.append(
    lifecycleStep("Published", "done"),
    lifecycleStep(isChunked ? `${version.chunk_count} chunks` : "Not chunked yet", isChunked ? "done" : "todo"),
    lifecycleStep(
      version.is_active ? "Retrievable" : "Superseded, not retrievable",
      version.is_active ? (isChunked ? "done" : "todo") : "superseded",
    ),
  );
  return track;
}

function versionFlagRow(flag) {
  const row = flagRow(flag);
  row.dataset.kind = flag.kind;
  row.append(element("span", "hint", FLAG_EXPLANATIONS[flag.kind] || ""));
  // The other item may be one the page can show, so its id jumps there.
  const jump = element("button", "chip-action", "Open item");
  jump.type = "button";
  jump.addEventListener("click", () => showItem(flag.existing_item_id));
  row.append(jump);
  return row;
}

function versionCard(item, version) {
  const card = element("li", "version");
  card.dataset.state = version.is_active ? "active" : "superseded";

  const head = element("div", "version-head");
  head.append(
    element("strong", "version-tag", version.version_tag),
    element("span", version.is_active ? "pill accent" : "pill", version.is_active ? "active" : "superseded"),
    element("span", "pill", version.document_format.toUpperCase()),
  );
  const file = element("span", "version-file", version.source_file_name);
  file.dir = "auto";
  head.append(file);

  const facts = element("p", "hint");
  facts.textContent =
    `v${version.sequence_number} · ${new Date(version.created_at).toLocaleString()} · ` +
    `sha256 ${version.content_hash.slice(0, HASH_PREVIEW_LENGTH)}…` +
    (version.previous_version_tag ? ` · replaces ${version.previous_version_tag}` : " · first version");

  card.append(head, facts);
  if (version.change_reason) {
    const reason = element("p", "version-reason");
    reason.append(element("b", "", "Why: "), version.change_reason);
    card.append(reason);
  }
  if (version.diff_summary) {
    const diff = element("p", "version-reason");
    diff.append(element("b", "", "Changed: "), version.diff_summary);
    card.append(diff);
  }
  card.append(lifecycle(version));

  if (version.duplicate_flags.length) {
    const flags = element("ul", "annotations");
    flags.append(...version.duplicate_flags.map(versionFlagRow));
    card.append(flags);
  }

  const target = { item_id: item.item_id, version_tag: version.version_tag, source_file_name: version.source_file_name };
  const actions = element("div", "version-actions");
  actions.append(actionButton("Chunks", () => openChunks(target)), actionButton("Blocks", () => openBlocks(target)));
  actions.append(actionButton("Ingest again", () => reingestVersion(item.item_id, version.version_tag)));
  card.append(actions);
  return card;
}

async function reingestVersion(itemId, versionTag) {
  try {
    await getJson(
      `/knowledge-items/${encodeURIComponent(itemId)}/versions/${encodeURIComponent(versionTag)}/ingestions`,
      { method: "POST" },
    );
    showFlash(`Queued ${versionTag} for ingestion again. Follow it on the Pipeline page.`);
    refreshIngestions();
  } catch (error) {
    showFlash(error.code ? `${error.code}: ${error.message}` : error.message);
  }
}

async function refreshItemDetail() {
  if (selectedItemId === null) return;
  const panel = document.getElementById("item-detail");
  try {
    const item = await getJson(`/knowledge-items/${encodeURIComponent(selectedItemId)}`);
    const signature = JSON.stringify(item);
    panel.hidden = false;
    if (signature === itemDetailSignature) return;
    itemDetailSignature = signature;
    document.getElementById("item-title").textContent = `Item #${item.item_id.slice(0, SHORT_ID_LENGTH)}`;
    document.getElementById("item-summary").textContent =
      `Owner Node ${item.owner_node_id} · ${item.confidentiality}` +
      (item.usage_scope ? ` · ${item.usage_scope}` : "") +
      ` · active version ${item.active_version_tag}`;
    // The newest version goes first, as in a change log.
    document.getElementById("version-list").replaceChildren(
      ...item.versions.slice().reverse().map((version) => versionCard(item, version)),
    );
  } catch (error) {
    panel.hidden = false;
    document.getElementById("item-summary").textContent = error.code ? `${error.code}: ${error.message}` : error.message;
  }
}

// Opens the Versions page on this item. Called by the Versions buttons of the Pipeline page.
function showItem(itemId) {
  selectedItemId = itemId;
  itemDetailSignature = null;
  itemListSignature = null;
  if (location.hash !== "#knowledge") location.hash = "knowledge";
  else refreshKnowledge();
}

async function refreshKnowledge() {
  await Promise.all([refreshItemList(), refreshItemDetail()]);
}

function pollKnowledge() {
  clearTimeout(itemPollTimer);
  if (!isKnowledgeViewOpen()) return;
  refreshKnowledge().finally(() => { itemPollTimer = setTimeout(pollKnowledge, ITEM_POLL_MS); });
}

function setUpVersionForm() {
  const form = document.getElementById("version-form");
  const button = document.getElementById("version-button");
  const message = document.getElementById("version-message");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = new FormData(form);
    if (!body.get("diff_summary")) body.delete("diff_summary");
    button.disabled = true;
    message.className = "message";
    message.textContent = "Uploading…";
    try {
      const receipt = await getJson(`/knowledge-items/${encodeURIComponent(selectedItemId)}/versions`, { method: "POST", body });
      message.textContent = "";
      form.reset();
      showFlash(`Queued ${receipt.version_tag}. Follow it on the Pipeline page.`);
      refreshIngestions();
      refreshKnowledge();
    } catch (error) {
      message.className = "message error";
      message.textContent = error.code ? `${error.code}: ${error.message}` : error.message;
    } finally {
      button.disabled = false;
    }
  });
}

document.addEventListener("viewchange", pollKnowledge);
setUpVersionForm();
// The first viewchange fired before this script loaded.
pollKnowledge();
