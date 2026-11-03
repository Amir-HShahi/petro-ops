# 0001. Local models and runtime

Date: 2026-11-02
Status: Proposed

## Context
The core must run fully offline on small local models (spec §8.2, phase 2). It needs an LLM for generation and judging, an embedding model for retrieval and duplicate detection, and later a vision model (LVM) for scanned PDFs and possibly a reranker.

The team develops on two machines: a MacBook Air M5 with 16 GB unified memory, and a laptop with an RTX 3060 Mobile (6 GB VRAM) and 15 GB RAM. Most sample documents are English.

## Decision
- **LLM:** `gemma4:12b-it-qat`, the quantization-aware Q4_0 build. Thinking is turned off.
- **Language:** documents, prompts and answers are English only.
- **Embedding:** `embeddinggemma:300m`. It has 768 dimensions and a 2048-token input limit, so chunks must stay under that.
- **LVM:** the same model as the LLM, see ADR 0002.
- **Reranker:** deferred. It is decided when retrieval quality (phase 8) needs it.
- **Runtime:** Ollama, reached only on the local loopback address (`127.0.0.1` or `localhost`). No call leaves the machine.
- The chosen models, their exact digests and limits are listed in `models/manifest.yaml`.

## Alternatives
- **llama.cpp embedded in the process.** It needs no local server, but models must be managed by hand as GGUF files. Ollama was already installed and in use.
- **Other embedding models already pulled:** `bge-m3:567m` and `qwen3-embedding:8b`. bge-m3 is about twice the size, and qwen3-embedding is too large to run next to the LLM on this machine. Neither was evaluated on the golden set yet.
- **A smaller LLM such as `qwen3.5:4b`.** It is faster and fits in VRAM, but is expected to be weaker as a judge, which spec §16 depends on.
- **`qwen3.5:9b`.** Benchmarked against Gemma on the M5 (results below). It ties on short documents and generates about twice as fast, but it fails more on long documents, needs much more memory and gets no JSON schema support in Ollama.
- **Persian documents.** A Persian pilot was dropped: Gemma leaked Korean or Chinese tokens into about 6% of Persian answers. In English the rate was 0.

The benchmark ran on the M5 with Ollama 0.40, fully offline, on its own English corpus of fictional "Platform Alpha" documents. Short documents were 7 files (3 PDF, 2 DOCX, 2 DOC); long documents were 4 operations logs with facts hidden at 10%, 50% and 90% depth. Full results: [Phase 2 — Generator LLM & LVM Baseline](https://claude.ai/artifact/E2HZRGNxhpcqdCZmxibvAW).

| Metric | `qwen3.5:9b` | `gemma4:12b-it-qat` |
|---|---|---|
| Short documents, 26 tests × 3 runs | 72/78 (≈96% after 2 over-strict checks were fixed) | 71/78 (≈95%) |
| Long documents, 20 tests | 15/20 | 20/20 |
| Long documents by length (5.6K / 11K / 23K / 46K tokens) | 4 / 5 / 3 / 3 | 5 / 5 / 5 / 5 |
| Stability across 3 runs (temperature 0.3) | 100% | 96% |
| Generation speed | 29.7 tokens/s | 14.0 tokens/s |
| Average latency, short documents | 3.3 s | 6.7 s |
| Memory at 46K tokens | 13 GB | 7.8 GB |
| Cold prefill at 46K tokens | 121 tokens/s (6.4 min) | 190 tokens/s (4.2 min) |
| JSON schema in Ollama | No (MLX runner) | Yes |

These numbers are not the project baseline. The baseline is measured on `fixtures/golden/` later and recorded in `docs/evaluation-baseline.md`.

## Consequences
- Prompts must stay small. Prefill runs at only 120–240 tokens/s on the M5, so a 46K-token prompt waits 4–6 minutes. An answer gets about 5 chunks (about 1.5K tokens), and fixed text such as the system prompt comes first so Ollama's prompt cache can reuse it.
- Gemma's memory stayed flat at about 7.8 GB up to 46K tokens on the M5. It will not fit in the 3060 laptop's 6 GB VRAM, so part of it runs on the CPU there. Latency on that laptop must be measured before the processing cycle and judge loops are sized.
- Structured outputs use Ollama's JSON schema and are also validated in code, with a retry when validation fails.
- Wording drives refusals. "Reply exactly: not in the documents" made both models refuse too often. Asking what is known and what is still unconfirmed fixed it.
- The Ollama HTTP call is local but still a socket. Adapters must refuse any non-loopback URL so the offline rule holds.
- Embedding similarity thresholds in `docs/evaluation-baseline.md` were set before this choice and must be re-tuned on the fixtures.
- Changing either model means a new digest in the manifest and re-running the golden set. Changing the embedding model also means re-indexing.
