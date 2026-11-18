# 0013. Issues on the pipeline page

Date: 2026-11-18
Status: Proposed

## Context
Phase 7 added Issue Management (spec §12, §14): raising an Issue with a similar-Issue check (ADR 0012), a SubIssue tree built by hand or from LLM candidates, priority, order, dependencies, statuses and resolution. It could be used only through the `issue` CLI, which is hard to show in a demo. The pipeline page (ADR 0008) already shows ingestion live and, since ADR 0011, the hierarchy, with routes another context mounts through `extra_routers`. Decomposition calls the local LLM and takes about a minute.

## Decision
- **Page:** a fourth view, Issues, in the same tab bar and URL hash, with plain HTML, CSS and vanilla JS (`assets/issues.js`).
  - **Node and Issues:** pick a Node and see its Issues, with status, priority, SubIssue count and similar-Issue flags. Raise an Issue in a dialog; its flags are shown and link to the Issues they name.
  - **One Issue:** a priority and a status select, Resolve with a summary, and the SubIssue tree. Each SubIssue has its own status, ↑ and ↓ to reorder, Split to add a child, a "Waits for" select, and chips that remove a dependency.
  - **Decompose:** tick KnowledgeItems from the latest completed ingestions, then Decompose. A spinner counts the seconds while Gemma reads. The candidates come with their citations; tick some and accept them.
  - A short legend explains the four steps an Issue goes through.
- **New routes**, all under `/issues`:

  | Action | Route |
  |---|---|
  | Issues of a Node | `GET /issues?node=…` |
  | Raise an Issue | `POST /issues` (201) |
  | One Issue with its tree, flags and candidates | `GET /issues/{issue_id}` |
  | Add a SubIssue | `POST /issues/{issue_id}/sub-issues` (201) |
  | Ask the LLM for candidates | `POST /issues/{issue_id}/decompositions` |
  | Accept candidates | `POST /issues/{issue_id}/candidates/accepted` |
  | Set the priority | `PUT /issues/{issue_id}/priority` |
  | Move a SubIssue | `PUT /issues/{issue_id}/sub-issues/{sub_issue_id}/position` |
  | Add a dependency | `POST /issues/{issue_id}/sub-issues/{sub_issue_id}/dependencies` |
  | Remove a dependency | `DELETE /issues/{issue_id}/sub-issues/{sub_issue_id}/dependencies/{other_id}` |
  | Change a status | `PUT /issues/{issue_id}/status` |
  | Resolve | `POST /issues/{issue_id}/resolution` |

- **Same behaviour as the CLI:** the routes call the existing handlers and return the bodies of `issue/interface/response_bodies.py`, so the page and the CLI show the same thing. Errors become Problem Details through the app's handlers.
- **Wiring:**
  - The routes are an `APIRouter` in `issue/interface/api.py`. `bootstrap.build_issue_router` builds it, and the API mounts it beside the organization routes.
  - `build_issue` takes the API's Knowledge Management wiring, so both share one set of connections, and the Issue wiring then leaves it for the API to close.
- **Decomposition waits** in the request; the page shows the seconds passing.
- **`pipeline-up.sh`** starts nothing new, since Issues have no worker. It prints the link of each view and warns when Ollama is off, since Decompose needs it even with `--no-vision`.

## Alternatives
- **Decompose through a RabbitMQ lane and worker,** like page reading, with the page polling for the result. It survives a closed tab and an API restart, but needs a new lane, message, worker and stored status. The page is for demos with one person at the keyboard, so the wait in the request is enough for now.
- **A separate Issue server on another port.** Same answer as in ADR 0011: two origins and a second process to start.
- **A frontend framework.** Same answer as in ADR 0008.

## Consequences
- The API now writes to Issue Management too, still without authentication; the loopback binding stays its only guard.
- A decomposition holds one API worker thread for about a minute. Several at once queue behind each other.
- The Knowledge choices come from the latest 100 ingestions, like the Versions view, so an older item is not offered until a list route exists.
- The page sends each change on its own and shows the Issue as the server stored it, so two people editing one Issue see each other's changes only after a refresh.
