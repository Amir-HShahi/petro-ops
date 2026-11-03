# 0001. Local models and runtime

Date: 2026-11-02
Status: Proposed

## Context
The core must run fully offline on small local models (spec §8.2, phase 2). It needs an LLM for generation and judging, an embedding model for retrieval and duplicate detection, and later a vision model (LVM) for scanned PDFs and possibly a reranker.

The development machine has an RTX 3060 Mobile with 6 GB VRAM and 15 GB RAM. Most sample documents are English.

## Decision
- **LLM:** `gemma4:12b`.
- **Embedding:** `embeddinggemma:300m`. It has 768 dimensions and a 2048-token input limit, so chunks must stay under that.
- **LVM and reranker:** deferred. They are decided when scanned PDFs (phase 4–5) and retrieval quality (phase 8) need them.
- **Runtime:** Ollama, reached only on the local loopback address (`127.0.0.1` or `localhost`). No call leaves the machine.
- The chosen models, their exact digests and limits are listed in `models/manifest.yaml`.

## Alternatives
- **llama.cpp embedded in the process.** It needs no local server, but models must be managed by hand as GGUF files. Ollama was already installed and in use.
- **Other embedding models already pulled:** `bge-m3:567m` and `qwen3-embedding:8b`. bge-m3 is about twice the size, and qwen3-embedding is too large to run next to the LLM on this machine. Neither was evaluated on the golden set yet.
- **A smaller LLM such as `qwen3.5:4b`.** It is faster and fits in VRAM, but is expected to be weaker as a judge, which spec §16 depends on.

No evaluation numbers yet. The baseline is measured on `fixtures/golden/` later and recorded in `docs/evaluation-baseline.md`.

## Consequences
- A 12B model will likely not fit fully in 6 GB VRAM, so part of it runs on the CPU and generation is slow. Latency must be measured before the processing cycle and judge loops are sized.
- The Ollama HTTP call is local but still a socket. Adapters must refuse any non-loopback URL so the offline rule holds.
- Embedding similarity thresholds in `docs/evaluation-baseline.md` were set before this choice and must be re-tuned on the fixtures.
- Changing either model means a new digest in the manifest and re-running the golden set. Changing the embedding model also means re-indexing.
