# 0011. Versions, duplicates and the hierarchy on the pipeline page

Date: 2026-11-11
Status: Proposed

## Context
The pipeline page (ADR 0008) shows ingestions moving through the workers. The work of spec phases 5 and 6 had no view: KnowledgeItem versions and the lifecycle of their chunks, the four kinds of duplicate flag, the Layer registry with its transfer requirements, and the Node tree with its parent and child links and system boundary. They could be read only through the CLI or by calling routes by hand, which is hard to show in a demo. ADR 0006 keeps the API ingestion only, and the import-linter contract stops Knowledge Management from importing the interface of Organizational Hierarchy.

## Decision
- **Page:** the page gets three views in a tab bar, kept in the URL hash: Pipeline (unchanged), Versions & duplicates, and Hierarchy. The first two are plain HTML, CSS and vanilla JS like the rest of the page (`versions.js`, `hierarchy.js`), with no CDN and no build step.
- **Versions & duplicates:** a legend of the four duplicate kinds; the items behind the latest 100 ingestions; for the selected item, its versions newest first, each with its active or superseded state, change reason, diff summary, a lifecycle (Published, chunk count, Retrievable or Superseded), its duplicate flags with a jump to the other item, and buttons for Chunks, Blocks and "Ingest again". A form publishes a new version. Completed ingestions get a Versions button.
- **Hierarchy:** the five Layers with detail level and transfer requirements, each editable; the Nodes as a tree by parent, with terminal Nodes (internal structure not tracked) drawn dashed; a dialog to register a Node whose parent choices already exclude Nodes in lower Layers and terminal Nodes. The server still enforces every rule.
- **New routes:**

  | Action | Route |
  |---|---|
  | One item with its versions, chunk counts and flags | `GET /knowledge-items/{item_id}` |
  | Layer registry with transfer rules | `GET /organization/layers` |
  | Nodes with parent and boundary | `GET /organization/nodes` |
  | Register a Node | `POST /organization/nodes` (201) |
  | Define a Layer's transfer rules | `PUT /organization/layers/{layer_index}/transfer-rule` |

- **Application:** `KnowledgeIngestionQueries.get_item(item_id)` and a new `HierarchyQueries` (`list_layers`, `list_nodes`). The routes call the existing `RegisterNodeHandler` and `DefineTransferRuleHandler` and return the same bodies as the `organization` CLI, which now share `organization/interface/response_bodies.py`.
- **Wiring:** the organization routes are an `APIRouter` in `organization/interface/api.py`. `bootstrap.build_organization_router` builds it, and `create_app` mounts routers it is given (`extra_routers`). Knowledge Management never imports the other context's interface. Errors from the router go through the app's Problem Details handlers.

## Alternatives
- **Put the organization routes in the knowledge API module.** Simpler, but it breaks the import-linter contract and mixes two contexts in one file.
- **A separate organization server on another port.** Keeps contexts apart, but the page would call two origins and need CORS, and the demo needs a second process.
- **A `GET /knowledge-items` list route.** Needs a new repository port method and adapter. The latest 100 ingestions already name every recent item, so the page groups them instead.
- **A frontend framework.** Same answer as in ADR 0008.

## Consequences
- The API now writes to Organizational Hierarchy, which ADR 0006 did not allow, and it has no authentication. The loopback binding stays its only guard. Anyone who can reach the page can register Nodes and change transfer rules.
- The Versions list only knows items that appear in the latest 100 ingestions. An older item without a recent ingestion is not listed until a list route exists.
- `get_item` loads every chunk of every version only to count them. It is fine for demo sizes. A count method on `KnowledgeChunkRepository` fixes it if it matters.
- Open question 6 in `docs/domain-model.md` still decides what happens to a flagged item. The page only shows flags and keeps both items.
