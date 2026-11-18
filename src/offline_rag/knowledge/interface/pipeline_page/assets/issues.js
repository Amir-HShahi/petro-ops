// Issues page (spec §12, §14): a Node's Issues with their SubIssue tree, the similar-Issue
// flags found when each was raised, SubIssue candidates Gemma suggests from chosen
// KnowledgeItems, and priority, order, dependencies, status and resolution. Every action
// calls the issue routes; the server enforces every rule and its refusals are shown as is.
"use strict";

const ISSUE_PRIORITIES = ["low", "medium", "high", "critical"];
const ISSUE_STATUSES = [
  "new", "analyzing", "knowledge_identified", "executor_identified", "solution_proposed",
  "in_execution", "awaiting_decision", "resolved", "unresolved", "archived",
];
const CLOSED_SUB_ISSUE_STATUSES = ["resolved", "unresolved", "archived"];
const KNOWLEDGE_FROM_INGESTIONS = 100;
const PREFERRED_NODE = "platform_sp12";

let issueNodeId = null;
let issueSummaries = [];
let currentIssue = null;
let subParentId = null;
let knowledgeNames = new Map();

function issueProblem(error) {
  return error.code ? `${error.code}: ${error.message}` : error.message;
}

function showIssueError(error) {
  const target = document.getElementById("issue-error");
  target.textContent = error ? issueProblem(error) : "";
}

function label(value) {
  return value.replaceAll("_", " ");
}

function selectOf(values, current, placeholder) {
  const select = element("select");
  if (placeholder) select.append(option("", placeholder));
  for (const value of values) select.append(option(value, label(value)));
  select.value = current || "";
  return select;
}

function isClosed(issue) {
  return issue.status === "resolved" || issue.status === "archived";
}

function setIssueCount(name, value) {
  for (const target of document.querySelectorAll(`[data-issue-count="${name}"]`)) target.textContent = String(value);
}

async function sendJson(url, method, body) {
  const options = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) options.body = JSON.stringify(body);
  return getJson(url, options);
}

// Runs one change on the Issue, then shows the Issue as the server stored it.
async function changeIssue(url, method, body, flash) {
  showIssueError(null);
  try {
    currentIssue = await sendJson(url, method, body);
    if (flash) showFlash(flash);
  } catch (error) {
    showIssueError(error);
  }
  await refreshIssues();
  renderIssue();
}

function issuePath(suffix = "") {
  return `/issues/${encodeURIComponent(currentIssue.issue_id)}${suffix}`;
}

async function loadIssueNodes() {
  const select = document.getElementById("issue-node");
  try {
    const body = await getJson("/nodes");
    select.replaceChildren(...body.nodes.map((node) => option(node.node_id, node.node_id)));
    const ids = body.nodes.map((node) => node.node_id);
    issueNodeId = ids.includes(issueNodeId) ? issueNodeId : ids.includes(PREFERRED_NODE) ? PREFERRED_NODE : ids[0] || null;
    select.value = issueNodeId || "";
  } catch (error) {
    select.replaceChildren(option("", "Node registry unavailable"));
    showError(document.getElementById("issue-list-error"), error);
  }
}

function issueButton(summary) {
  const button = element("button", "item-button");
  button.type = "button";
  button.setAttribute("aria-pressed", String(currentIssue !== null && summary.issue_id === currentIssue.issue_id));
  const meta = element("span", "item-meta");
  meta.append(element("span", `pill${isClosed(summary) ? "" : " accent"}`, label(summary.status)));
  if (summary.priority) meta.append(element("span", `pill${summary.priority === "critical" || summary.priority === "high" ? " danger" : ""}`, summary.priority));
  meta.append(element("span", "pill", `${summary.sub_issue_count} SubIssue${summary.sub_issue_count === 1 ? "" : "s"}`));
  if (summary.similar_issue_count) meta.append(element("span", "pill attention", `${summary.similar_issue_count} similar`));
  button.append(element("span", "item-name", summary.title), meta);
  button.addEventListener("click", () => showIssue(summary.issue_id));
  const entry = element("li");
  entry.append(button);
  return entry;
}

async function refreshIssues() {
  const error = document.getElementById("issue-list-error");
  if (!issueNodeId) return;
  try {
    const body = await getJson(`/issues?node=${encodeURIComponent(issueNodeId)}`);
    issueSummaries = body.issues;
    error.hidden = true;
  } catch (caught) {
    issueSummaries = [];
    showError(error, caught);
  }
  document.getElementById("issue-list").replaceChildren(...issueSummaries.map(issueButton));
  document.getElementById("issue-list-empty").hidden = issueSummaries.length > 0;
  setIssueCount("issues", issueSummaries.length);
  setIssueCount("open", issueSummaries.filter((summary) => !isClosed(summary)).length);
  setIssueCount("resolved", issueSummaries.filter((summary) => summary.status === "resolved").length);
}

async function showIssue(issueId) {
  showIssueError(null);
  document.getElementById("decompose-message").textContent = "";
  try {
    currentIssue = await getJson(`/issues/${encodeURIComponent(issueId)}`);
  } catch (error) {
    currentIssue = null;
    showError(document.getElementById("issue-list-error"), error);
  }
  await refreshIssues();
  renderIssue();
}

function issueTitle(issueId) {
  const found = issueSummaries.find((summary) => summary.issue_id === issueId);
  return found ? found.title : `#${issueId.slice(0, SHORT_ID_LENGTH)}`;
}

function renderFlags(issue) {
  const holder = document.getElementById("issue-flags");
  holder.replaceChildren();
  if (!issue.similar_issues.length) return;
  const box = element("div", "issue-flags");
  box.append(element("strong", "", "When it was raised it looked like:"));
  const list = element("ul", "flag-list");
  for (const flag of issue.similar_issues) {
    const row = element("li");
    const jump = element("button", "link-button", issueTitle(flag.issue_id));
    jump.type = "button";
    jump.addEventListener("click", () => showIssue(flag.issue_id));
    row.append(
      element("span", `pill ${flag.kind === "duplicate" ? "danger" : "attention"}`, flag.kind),
      element("span", "hint", `score ${flag.score.toFixed(2)}`),
      jump,
    );
    list.append(row);
  }
  box.append(list, element("p", "hint", "A flag is a finding: both Issues are kept."));
  holder.append(box);
}

function allSubIssues(issue) {
  const found = [];
  const walk = (subs) => {
    for (const sub of subs) {
      found.push(sub);
      walk(sub.sub_issues);
    }
  };
  walk(issue.sub_issues);
  return found;
}

function smallButton(text, title, onClick, disabled) {
  const button = element("button", "btn btn-small", text);
  button.type = "button";
  button.title = title;
  button.disabled = disabled;
  button.addEventListener("click", onClick);
  return button;
}

function subIssueEntry(sub, siblingCount, titles, closed) {
  const item = element("li", "tree-node");
  const card = element("div", "node-card sub-card");
  card.dataset.closed = String(CLOSED_SUB_ISSUE_STATUSES.includes(sub.status));

  const head = element("div", "node-head");
  head.append(element("span", "pill", String(sub.position)), element("strong", "node-name", sub.title));
  card.append(head, element("p", "hint", sub.description));

  const controls = element("div", "sub-controls");
  const status = selectOf(ISSUE_STATUSES, sub.status);
  status.disabled = closed;
  status.setAttribute("aria-label", `Status of ${sub.title}`);
  status.addEventListener("change", () =>
    changeIssue(issuePath("/status"), "PUT", { status: status.value, sub_issue_id: sub.sub_issue_id }, `${sub.title}: ${label(status.value)}.`));
  controls.append(
    status,
    smallButton("↑", "Move up", () => moveSubIssue(sub, sub.position - 1), closed || sub.position === 1),
    smallButton("↓", "Move down", () => moveSubIssue(sub, sub.position + 1), closed || sub.position === siblingCount),
    smallButton("Split", "Add a SubIssue under this one", () => openSubDialog(sub), closed),
  );
  const others = [...titles.keys()].filter((id) => id !== sub.sub_issue_id && !sub.depends_on.includes(id));
  if (others.length && !closed) {
    const wait = element("select");
    wait.setAttribute("aria-label", `${sub.title} waits for`);
    wait.append(option("", "Waits for…"), ...others.map((id) => option(id, titles.get(id))));
    wait.addEventListener("change", () => {
      if (wait.value) {
        changeIssue(issuePath(`/sub-issues/${encodeURIComponent(sub.sub_issue_id)}/dependencies`), "POST",
          { depends_on_sub_issue_id: wait.value }, `${sub.title} now waits for ${titles.get(wait.value)}.`);
      }
    });
    controls.append(wait);
  }
  card.append(controls);

  if (sub.depends_on.length) {
    const waits = element("div", "sub-waits");
    waits.append(element("span", "hint", "Waits for:"));
    for (const id of sub.depends_on) {
      const chip = element("span", "pill accent", titles.get(id) || id);
      if (!closed) {
        const remove = element("button", "link-button", "×");
        remove.type = "button";
        remove.title = "Stop waiting";
        remove.addEventListener("click", () =>
          changeIssue(issuePath(`/sub-issues/${encodeURIComponent(sub.sub_issue_id)}/dependencies/${encodeURIComponent(id)}`), "DELETE",
            undefined, `${sub.title} no longer waits for ${titles.get(id)}.`));
        chip.append(remove);
      }
      waits.append(chip);
    }
    card.append(waits);
  }
  item.append(card);

  if (sub.sub_issues.length) {
    const list = element("ul", "tree");
    list.append(...sub.sub_issues.map((child) => subIssueEntry(child, sub.sub_issues.length, titles, closed)));
    item.append(list);
  }
  return item;
}

function moveSubIssue(sub, position) {
  changeIssue(issuePath(`/sub-issues/${encodeURIComponent(sub.sub_issue_id)}/position`), "PUT",
    { position }, `${sub.title} moved to place ${position}.`);
}

function citationLine(citation) {
  const row = element("li", "citation");
  const source = knowledgeNames.get(citation.doc_id) || `#${citation.doc_id.slice(0, SHORT_ID_LENGTH)}`;
  row.append(
    element("q", "", citation.quote),
    element("span", "hint", ` — ${source}${citation.page_or_section ? `, ${citation.page_or_section}` : ""}`),
  );
  return row;
}

function renderCandidates(issue) {
  const list = document.getElementById("candidate-list");
  const waiting = issue.sub_issue_candidates.filter((candidate) => candidate.accepted_sub_issue_id === null);
  list.replaceChildren(...issue.sub_issue_candidates.map((candidate) => {
    const item = element("li", "candidate");
    const head = element("label", "check");
    if (candidate.accepted_sub_issue_id === null) {
      const box = element("input");
      box.type = "checkbox";
      box.value = String(candidate.number);
      box.dataset.candidate = "";
      box.disabled = isClosed(issue);
      head.append(box);
    } else {
      head.append(element("span", "pill accent", "accepted"));
    }
    head.append(element("strong", "", `${candidate.number}. ${candidate.title}`));
    item.append(head, element("p", "hint", candidate.description));
    if (candidate.citations.length) {
      const citations = element("ul", "citations");
      citations.append(...candidate.citations.map(citationLine));
      item.append(citations);
    } else {
      item.append(element("p", "hint", "No citation could be found in the knowledge it was given."));
    }
    return item;
  }));
  document.getElementById("accept-row").hidden = waiting.length === 0 || isClosed(issue);
}

function renderIssue() {
  const detail = document.getElementById("issue-detail");
  detail.hidden = currentIssue === null;
  if (currentIssue === null) return;
  const issue = currentIssue;
  const closed = isClosed(issue);

  document.getElementById("issue-title").textContent = issue.title;
  document.getElementById("issue-summary").textContent =
    `#${issue.issue_id.slice(0, SHORT_ID_LENGTH)} · ${issue.owner_node_id} · raised ${relativeTime(issue.raised_at)}`;
  document.getElementById("issue-description").textContent = issue.description;

  const priority = document.getElementById("issue-priority");
  priority.replaceChildren(option("", "not set"), ...ISSUE_PRIORITIES.map((value) => option(value, value)));
  priority.value = issue.priority || "";
  priority.disabled = closed;
  const status = document.getElementById("issue-status");
  // The Issue itself becomes resolved only through Resolve, with a summary.
  status.replaceChildren(...ISSUE_STATUSES.filter((value) => value !== "resolved" || issue.status === "resolved")
    .map((value) => option(value, label(value))));
  status.value = issue.status;
  status.disabled = issue.status === "archived";
  document.getElementById("issue-resolve").hidden = closed;

  const resolution = document.getElementById("issue-resolution");
  resolution.hidden = !issue.resolution_summary;
  resolution.textContent = issue.resolution_summary ? `Resolved: ${issue.resolution_summary}` : "";

  renderFlags(issue);
  const titles = new Map(allSubIssues(issue).map((sub) => [sub.sub_issue_id, sub.title]));
  document.getElementById("sub-tree").replaceChildren(
    ...issue.sub_issues.map((sub) => subIssueEntry(sub, issue.sub_issues.length, titles, closed)));
  document.getElementById("sub-tree-empty").hidden = issue.sub_issues.length > 0;
  document.getElementById("sub-open").disabled = closed;
  document.getElementById("decompose").disabled = closed;
  renderCandidates(issue);
}

async function loadKnowledgeChoices() {
  const list = document.getElementById("knowledge-choices");
  const checked = new Set([...list.querySelectorAll("input:checked")].map((box) => box.value));
  try {
    const body = await getJson(`/knowledge-ingestions?limit=${KNOWLEDGE_FROM_INGESTIONS}`);
    knowledgeNames = new Map();
    for (const ingestion of body.ingestions) {
      if (ingestion.status === "completed" && !knowledgeNames.has(ingestion.item_id)) {
        knowledgeNames.set(ingestion.item_id, ingestion.source_file_name);
      }
    }
  } catch (error) {
    showIssueError(error);
  }
  list.replaceChildren(...[...knowledgeNames].map(([itemId, fileName]) => {
    const item = element("li");
    const row = element("label", "check");
    const box = element("input");
    box.type = "checkbox";
    box.value = itemId;
    box.checked = checked.has(itemId);
    row.append(box, element("span", "", fileName), element("span", "pill", `#${itemId.slice(0, SHORT_ID_LENGTH)}`));
    item.append(row);
    return item;
  }));
  document.getElementById("knowledge-choices-empty").hidden = knowledgeNames.size > 0;
}

function setUpDecompose() {
  const button = document.getElementById("decompose");
  const wait = document.getElementById("decompose-wait");
  const message = document.getElementById("decompose-message");
  button.addEventListener("click", async () => {
    const itemIds = [...document.querySelectorAll("#knowledge-choices input:checked")].map((box) => box.value);
    showIssueError(null);
    message.className = "message";
    if (!itemIds.length) {
      message.textContent = "Tick at least one KnowledgeItem for Gemma to read and cite.";
      return;
    }
    const started = Date.now();
    button.disabled = true;
    wait.hidden = false;
    const tick = () => {
      wait.replaceChildren(icon("spinner"), document.createTextNode(` Gemma is reading… ${Math.round((Date.now() - started) / 1000)} s`));
    };
    tick();
    const timer = setInterval(tick, 1000);
    try {
      const result = await sendJson(issuePath("/decompositions"), "POST", { knowledge_item_ids: itemIds });
      const parts = [`Gemma suggested ${result.candidates.length} SubIssue${result.candidates.length === 1 ? "" : "s"} in ${Math.round((Date.now() - started) / 1000)} s.`];
      if (result.dropped_citation_count) parts.push(`${result.dropped_citation_count} citation(s) were dropped: their quote is not in the item they name.`);
      if (result.missing_information) parts.push(`Missing: ${result.missing_information}`);
      message.textContent = parts.join("\n");
      currentIssue = await getJson(issuePath());
      renderIssue();
    } catch (error) {
      message.className = "message error";
      message.textContent = issueProblem(error);
    } finally {
      clearInterval(timer);
      wait.hidden = true;
      button.disabled = isClosed(currentIssue);
    }
  });

  document.getElementById("accept-candidates").addEventListener("click", () => {
    const numbers = [...document.querySelectorAll("#candidate-list input[data-candidate]:checked")].map((box) => Number(box.value));
    if (!numbers.length) {
      showIssueError({ message: "Tick the candidates to accept." });
      return;
    }
    changeIssue(issuePath("/candidates/accepted"), "POST", { numbers }, `Accepted ${numbers.length} candidate(s) as SubIssues.`);
  });
}

function openSubDialog(parent) {
  subParentId = parent ? parent.sub_issue_id : null;
  const form = document.getElementById("sub-form");
  form.reset();
  document.getElementById("sub-form-message").textContent = "";
  document.getElementById("sub-dialog-summary").textContent = parent
    ? `Under “${parent.title}”, last among its SubIssues.`
    : "Right under the Issue, last among its SubIssues.";
  document.getElementById("sub-dialog").showModal();
}

// Sends a dialog form and shows the refusal inside the dialog, so it can be fixed there.
function setUpDialogForm(name, submit) {
  const form = document.getElementById(`${name}-form`);
  const message = document.getElementById(`${name}-form-message`);
  const button = document.getElementById(`${name}-submit`);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    message.className = "message";
    message.textContent = "Saving…";
    try {
      await submit(new FormData(form));
      document.getElementById(`${name}-dialog`).close();
    } catch (error) {
      message.className = "message error";
      message.textContent = issueProblem(error);
    } finally {
      button.disabled = false;
    }
  });
  const dialog = document.getElementById(`${name}-dialog`);
  document.getElementById(`${name}-dialog-close`).addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

function setUpIssueForms() {
  setUpDialogForm("issue", async (fields) => {
    const tags = String(fields.get("tags") || "").split(",").map((tag) => tag.trim()).filter(Boolean);
    const raised = await sendJson("/issues", "POST", {
      owner_node_id: issueNodeId,
      title: fields.get("title").trim(),
      description: fields.get("description").trim(),
      domain: fields.get("domain").trim() || null,
      tags,
    });
    const flagged = raised.similar_issues.length;
    showFlash(flagged ? `Raised, and flagged as like ${flagged} earlier Issue(s).` : "Raised. No similar Issue of this Node was found.");
    currentIssue = raised;
    await refreshIssues();
    renderIssue();
  });
  setUpDialogForm("sub", async (fields) => {
    currentIssue = await sendJson(issuePath("/sub-issues"), "POST", {
      parent_id: subParentId,
      title: fields.get("title").trim(),
      description: fields.get("description").trim(),
    });
    showFlash("SubIssue added.");
    await refreshIssues();
    renderIssue();
  });
  setUpDialogForm("resolve", async (fields) => {
    currentIssue = await sendJson(issuePath("/resolution"), "POST", {
      resolution_summary: fields.get("resolution_summary").trim(),
    });
    showFlash("Issue resolved.");
    await refreshIssues();
    renderIssue();
  });

  document.getElementById("issue-open").addEventListener("click", () => {
    document.getElementById("issue-form").reset();
    document.getElementById("issue-form-message").textContent = "";
    document.getElementById("issue-dialog-summary").textContent =
      `For ${issueNodeId}. It is compared with this Node's other Issues before it is created.`;
    document.getElementById("issue-dialog").showModal();
  });
  document.getElementById("sub-open").addEventListener("click", () => openSubDialog(null));
  document.getElementById("issue-resolve").addEventListener("click", () => {
    document.getElementById("resolve-form").reset();
    document.getElementById("resolve-form-message").textContent = "";
    document.getElementById("resolve-dialog").showModal();
  });
  document.getElementById("issue-priority").addEventListener("change", (event) => {
    if (event.target.value) changeIssue(issuePath("/priority"), "PUT", { priority: event.target.value }, `Priority: ${event.target.value}.`);
  });
  document.getElementById("issue-status").addEventListener("change", (event) => {
    changeIssue(issuePath("/status"), "PUT", { status: event.target.value }, `Status: ${label(event.target.value)}.`);
  });
  document.getElementById("issue-node").addEventListener("change", (event) => {
    issueNodeId = event.target.value;
    currentIssue = null;
    renderIssue();
    refreshIssues();
  });
}

async function refreshIssuePage() {
  await loadIssueNodes();
  await Promise.all([refreshIssues(), loadKnowledgeChoices()]);
  if (currentIssue !== null) await showIssue(currentIssue.issue_id);
}

document.addEventListener("viewchange", (event) => {
  if (event.detail === "issues") refreshIssuePage();
});
setUpIssueForms();
setUpDecompose();
// The first viewchange fired before this script loaded.
if (location.hash === "#issues") refreshIssuePage();
