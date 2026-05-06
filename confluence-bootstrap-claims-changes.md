# Confluence Changes — CON-196: Populate claims during corpus bootstrap

Apply these changes manually to the relevant pages.

---

## Page: Functional Requirements — signal-detection (ID: 74153986)

### Section: Flow 4 — Corpus bootstrap (one-time)

**Change:** Add step 3 (claim extraction) and update the Constraints line.

#### Current Behaviour (steps 1–5):

> 1. Fetch all completed `news-retrieval` runs for the domain within the lookback window
> 2. For each run, paginate through articles and embed each (skip URLs already in Qdrant by hash)
> 3. After all articles embedded, run approximate k-means (`MiniBatchKMeans`, k configurable, default 8) over the embedding space to identify topic clusters
> 4. Create `topic_clusters` rows; compute and store initial centroid for each cluster
> 5. Log progress, document count, and cluster assignments

#### Replace with (steps 1–6):

> 1. Fetch all completed `news-retrieval` runs for the domain within the lookback window
> 2. For each run, paginate through articles and embed each (skip URLs already in Qdrant by hash)
> 3. **Claim extraction and embedding** — for each embedded article, extract 3–5 factual claims via LLM (`OPENROUTER_MODEL`), embed each claim with the claim embedding model (`CLAIM_EMBEDDING_MODEL`), and upsert into the Qdrant `claims` collection. Skip articles whose claims are already present (checked via `article_qdrant_id` payload). Failures are logged and skipped without aborting bootstrap.
> 4. After all articles embedded, run approximate k-means (`MiniBatchKMeans`, k configurable, default 8) over the embedding space to identify topic clusters
> 5. Create `topic_clusters` rows; compute and store initial centroid for each cluster
> 6. Log progress, document count, and cluster assignments

#### Current Constraints line:

> **Constraints:** Must be resumable — re-running after an interruption skips already-embedded documents

#### Replace with:

> **Constraints:** Must be resumable — re-running after an interruption skips already-embedded documents and articles whose claims are already present in Qdrant

---

*No changes required to the Technical Specifications page (74154013) — bootstrap pipeline detail lives in STRUCTURE.md, not in that doc.*
