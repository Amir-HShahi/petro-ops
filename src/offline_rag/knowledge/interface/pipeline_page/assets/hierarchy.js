// Organizational hierarchy page (spec §6): the five Layers with what each one requires of
// the TransferPackages it receives, and the Nodes as a parent and child tree. Registering a
// Node and defining transfer requirements call the organization routes; the server enforces
// every rule, and the form only narrows the choices to ones that can pass.
"use strict";

const LAST_LAYER = 4;
const DEFAULT_PARENT_LABEL = "No parent (Layer 0 only)";
const DETAIL_LEVELS = {
  top_executive: "Top executive",
  managerial: "Managerial",
  technical_summary: "Technical summary",
  detailed_technical: "Detailed technical",
};
const CONFIDENTIALITY_LEVELS = ["public", "internal", "confidential"];

let layers = [];
let nodes = [];
let ruleLayerIndex = null;

function problemText(error) {
  return error.code ? `${error.code}: ${error.message}` : error.message;
}

function organizationCount(name, value) {
  for (const target of document.querySelectorAll(`[data-org-count="${name}"]`)) target.textContent = String(value);
}

function ruleFact(label, value) {
  const row = element("div");
  row.append(element("dt", "", label), element("dd", "", value));
  return row;
}

function layerCard(layer) {
  const card = element("li", "layer");
  card.dataset.layer = String(layer.layer_index);
  const count = nodes.filter((node) => node.layer_index === layer.layer_index).length;

  const head = element("div", "layer-head");
  head.append(
    element("span", "layer-number", String(layer.layer_index)),
    element("div", "layer-title"),
  );
  head.lastChild.append(element("h3", "", layer.name), element("p", "hint", layer.role));
  head.append(element("span", "pill", `${count} node${count === 1 ? "" : "s"}`));
  card.append(head);

  if (layer.layer_index === LAST_LAYER) {
    card.append(element("p", "layer-note", "Provides knowledge only. It receives no TransferPackage, so it has no detail level or rules."));
    return card;
  }

  card.append(element("span", "pill accent", `Receives ${DETAIL_LEVELS[layer.received_detail_level] || layer.received_detail_level}`));
  const rule = layer.transfer_rule;
  if (rule === null) {
    card.append(element("p", "layer-note", "No transfer requirements defined yet."));
  } else {
    const facts = element("dl", "rule-facts");
    facts.append(
      ruleFact("Required topics", rule.required_topics.join(", ") || "none"),
      ruleFact("Excluded topics", rule.excluded_topics.join(", ") || "none"),
      ruleFact("Output format", rule.output_format),
      ruleFact("Lowest judge score", `${rule.min_judge_score}/20`),
      ruleFact("Longest package", `${rule.max_package_length_tokens} tokens`),
      ruleFact("Source references", rule.source_reference_level),
    );
    card.append(facts);
  }
  const edit = element("button", "btn", rule === null ? "Define requirements" : "Edit requirements");
  edit.type = "button";
  edit.addEventListener("click", () => openRuleDialog(layer));
  card.append(edit);
  return card;
}

function nodeEntry(node, childrenByParent) {
  const item = element("li", "tree-node");
  const card = element("div", "node-card");
  card.dataset.tracked = String(node.is_internal_structure_tracked);
  card.dataset.layer = String(node.layer_index);

  const head = element("div", "node-head");
  head.append(
    element("span", "pill accent", `Layer ${node.layer_index}`),
    element("strong", "node-name", node.name),
    element("code", "node-id", node.node_id),
  );
  const facts = element("p", "hint");
  facts.textContent = `${node.activity_area} · reports ${node.reporting_rule} · ${node.confidentiality}`;
  const boundary = node.is_internal_structure_tracked
    ? element("span", "pill", "internal structure tracked")
    : element("span", "pill attention", "terminal Node · boundary");
  card.append(head, facts, boundary);
  item.append(card);

  const children = childrenByParent.get(node.node_id) || [];
  if (children.length) {
    const list = element("ul", "tree");
    list.append(...children.map((child) => nodeEntry(child, childrenByParent)));
    item.append(list);
  }
  return item;
}

function renderHierarchy() {
  document.getElementById("layer-list").replaceChildren(...layers.map(layerCard));

  const childrenByParent = new Map();
  const roots = [];
  for (const node of nodes) {
    if (node.parent_node_id === null) roots.push(node);
    else {
      if (!childrenByParent.has(node.parent_node_id)) childrenByParent.set(node.parent_node_id, []);
      childrenByParent.get(node.parent_node_id).push(node);
    }
  }
  document.getElementById("node-tree").replaceChildren(...roots.map((node) => nodeEntry(node, childrenByParent)));
  document.getElementById("node-tree-empty").hidden = nodes.length > 0;

  organizationCount("layers", layers.length);
  organizationCount("nodes", nodes.length);
  organizationCount("rules", layers.filter((layer) => layer.transfer_rule !== null).length);
}

async function refreshHierarchy() {
  const layersError = document.getElementById("layers-error");
  const nodesError = document.getElementById("nodes-error");
  try {
    layers = (await getJson("/organization/layers")).layers;
    layersError.hidden = true;
  } catch (error) {
    showError(layersError, error);
  }
  try {
    nodes = (await getJson("/organization/nodes")).nodes;
    nodesError.hidden = true;
  } catch (error) {
    showError(nodesError, error);
  }
  renderHierarchy();
}

function option(value, label) {
  const entry = element("option", "", label);
  entry.value = value;
  return entry;
}

// A parent is in a higher Layer and tracks its inside. The server checks the same, so this
// only keeps impossible choices out of the list.
function fillParentChoices() {
  const layerIndex = Number(document.getElementById("node-layer").value);
  const parent = document.getElementById("node-parent");
  const isTop = layerIndex === 0;
  const candidates = nodes.filter((node) => node.layer_index < layerIndex && node.is_internal_structure_tracked);
  parent.replaceChildren(
    option("", isTop ? DEFAULT_PARENT_LABEL : candidates.length ? "Pick a parent Node" : "No Node can take a child here"),
    ...candidates.map((node) => option(node.node_id, `${node.name} (Layer ${node.layer_index})`)),
  );
  parent.disabled = isTop;
  parent.required = !isTop;
}

function openNodeDialog() {
  const form = document.getElementById("node-form");
  form.reset();
  document.getElementById("node-message").textContent = "";
  document.getElementById("node-layer").replaceChildren(
    ...layers.map((layer) => option(String(layer.layer_index), `Layer ${layer.layer_index} · ${layer.name}`)),
  );
  document.getElementById("node-confidentiality").replaceChildren(
    ...CONFIDENTIALITY_LEVELS.map((level) => option(level, level)),
  );
  document.getElementById("node-confidentiality").value = "internal";
  fillParentChoices();
  document.getElementById("node-dialog").showModal();
}

function setUpNodeForm() {
  const form = document.getElementById("node-form");
  const message = document.getElementById("node-message");
  const button = document.getElementById("node-submit");
  document.getElementById("node-open").addEventListener("click", openNodeDialog);
  document.getElementById("node-layer").addEventListener("change", fillParentChoices);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fields = new FormData(form);
    button.disabled = true;
    message.className = "message";
    message.textContent = "Registering…";
    try {
      const node = await getJson("/organization/nodes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          node_id: fields.get("node_id").trim(),
          name: fields.get("name").trim(),
          layer_index: Number(fields.get("layer_index")),
          parent_node_id: fields.get("parent_node_id") || null,
          activity_area: fields.get("activity_area").trim(),
          reporting_rule: fields.get("reporting_rule").trim(),
          confidentiality: fields.get("confidentiality"),
          is_internal_structure_tracked: fields.get("is_internal_structure_tracked") === "on",
        }),
      });
      document.getElementById("node-dialog").close();
      showFlash(`Registered ${node.node_id} in Layer ${node.layer_index}.`);
      await refreshHierarchy();
      // The Submit files form picks its owner from the registered Nodes.
      loadNodes();
    } catch (error) {
      message.className = "message error";
      message.textContent = problemText(error);
    } finally {
      button.disabled = false;
    }
  });
}

function splitTopics(text) {
  return String(text || "").split(",").map((topic) => topic.trim()).filter(Boolean);
}

function openRuleDialog(layer) {
  ruleLayerIndex = layer.layer_index;
  const form = document.getElementById("rule-form");
  form.reset();
  document.getElementById("rule-message").textContent = "";
  document.getElementById("rule-title").textContent = `Layer ${layer.layer_index} transfer requirements`;
  document.getElementById("rule-summary").textContent =
    `What the TransferPackages this Layer receives from Layer ${layer.layer_index + 1} must meet.`;
  const detail = document.getElementById("rule-detail");
  detail.replaceChildren(...Object.entries(DETAIL_LEVELS).map(([value, label]) => option(value, label)));
  detail.value = layer.received_detail_level;
  const rule = layer.transfer_rule;
  if (rule !== null) {
    form.elements.required_topics.value = rule.required_topics.join(", ");
    form.elements.excluded_topics.value = rule.excluded_topics.join(", ");
    form.elements.output_format.value = rule.output_format;
    form.elements.min_judge_score.value = rule.min_judge_score;
    form.elements.max_package_length_tokens.value = rule.max_package_length_tokens;
    form.elements.source_reference_level.value = rule.source_reference_level;
  }
  document.getElementById("rule-dialog").showModal();
}

function setUpRuleForm() {
  const form = document.getElementById("rule-form");
  const message = document.getElementById("rule-message");
  const button = document.getElementById("rule-submit");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fields = new FormData(form);
    button.disabled = true;
    message.className = "message";
    message.textContent = "Saving…";
    try {
      await getJson(`/organization/layers/${ruleLayerIndex}/transfer-rule`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          received_detail_level: fields.get("received_detail_level"),
          required_topics: splitTopics(fields.get("required_topics")),
          excluded_topics: splitTopics(fields.get("excluded_topics")),
          output_format: fields.get("output_format").trim(),
          min_judge_score: Number(fields.get("min_judge_score")),
          max_package_length_tokens: Number(fields.get("max_package_length_tokens")),
          source_reference_level: fields.get("source_reference_level").trim(),
        }),
      });
      document.getElementById("rule-dialog").close();
      showFlash(`Saved the transfer requirements of Layer ${ruleLayerIndex}.`);
      await refreshHierarchy();
    } catch (error) {
      message.className = "message error";
      message.textContent = problemText(error);
    } finally {
      button.disabled = false;
    }
  });
}

for (const name of ["node", "rule"]) {
  const dialog = document.getElementById(`${name}-dialog`);
  document.getElementById(`${name}-close`).addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

document.addEventListener("viewchange", (event) => {
  if (event.detail === "hierarchy") refreshHierarchy();
});
setUpNodeForm();
setUpRuleForm();
// The first viewchange fired before this script loaded.
if (location.hash === "#hierarchy") refreshHierarchy();
