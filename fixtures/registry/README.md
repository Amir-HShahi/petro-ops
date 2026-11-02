# Layer and Node registry

The sample registry from spec §6.1 for the offshore scenario in `docs/scenario-offshore-fa.md`.

## `layers.csv`

- `layer_index`: 0 (strategic) to 4 (knowledge sources), as in spec §6.2.
- `received_detail_level`: the transfer detail level the Layer expects from the Layer below, as in spec §6.4: `top_executive`, `managerial`, `technical_summary` or `detailed_technical`. Empty for Layer 4, which only provides knowledge.

## `nodes.csv`

- `parent_node_id`: empty only for the Layer 0 Node. A parent is always in a higher Layer (lower index), but it can skip Layers. Regional teams and the archive belong directly to the regional operator.
- `activity_area`: what the Node works on.
- `reporting_rule`: how often the Node reports to its parent.
- `confidentiality`: the visibility limit of the Node's knowledge: `public`, `internal` or `confidential`.
- `is_internal_structure_tracked`: `true` when the Node's children are modelled. Otherwise the inside of the Node is outside the system boundary.

`tests/unit/test_fixture_registry.py` checks these rules and that every Node in `fixtures/docs/manifest.csv` is here with the same Layer.
