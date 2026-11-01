---
name: write-tests
description: Write pytest tests for new or changed Python code, choosing the right level (unit, integration, smoke, regression, e2e). Use after implementing or changing code, or when asked to add tests.
---

1. Read the code under test and find its rules: what it accepts, what it rejects, what it returns.
2. Pick the level and folder:
   - `tests/unit/<ctx>/`: domain and application logic, with fakes from `tests/fakes/`. No real models, files or network.
   - `tests/integration/<ctx>/`: a real adapter (parser, store, local model). Mark `@pytest.mark.integration`.
   - `tests/smoke/`: the full pipeline on tiny files from `fixtures/`. Mark `@pytest.mark.smoke`.
   - `tests/regression/`: golden answers and judge scores. Mark `@pytest.mark.regression`.
   - `tests/e2e/`: ingest, ask, build a transfer package. Mark `@pytest.mark.e2e`.
   - Tests that load real models also get `@pytest.mark.slow`.
3. Cover the happy path, the edge cases, and one test per rule violation.
4. For chunking, versioning and duplicate detection, add a Hypothesis property test where it makes sense.
5. Style:
   - name tests `test_<behavior>_when_<condition>`
   - arrange, act, assert, with one behavior per test
   - use fixtures for setup that repeats, not helper classes
6. Run the new tests and report the real result, including failures.
