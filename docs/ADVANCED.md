# Advanced research workspace

Open **Research workspace** beside Add to library, or select a reference and use its Research tools. These workflows run in the existing Python/Flask application.

## Features and their accuracy boundaries

| Feature | Available workflow | Important boundary |
|---|---|---|
| Intelligent intake | Page-level text; local OCR; orientation detection/correction; word boxes; mean OCR confidence; detected language; document-type suggestion; metadata provenance; native PDF/DOCX tables; bibliography candidates | OCR confidence is an engine score, not a calibrated probability. Detected language is informational; choose the installed OCR language in Settings. Structure and type suggestions require review. Image-only tables can be captured as regions; their cells are not automatically reconstructed. |
| Semantic search | Local BGE-small ONNX embeddings; cached passage vectors in SQLite; filters for document scope, author, year, collection, and type | Similarity is not evidence quality. This model is English-oriented. It retrieves extracted passages, not metadata-only records. |
| Ask your library | Relevant passages with source links; optional provider-generated answers; explicit no-evidence result | Local mode returns excerpts rather than fabricating a synthesized answer. AI citation IDs and exact quotes are checked; semantic support for the generated interpretation still needs human review. |
| Structured summaries | Extractive question, methods, datasets, findings, limitations, and open-question sections; optional AI summary draft | Local section selection is heuristic. AI synthesis uses a bounded selection of passages and reports its coverage; it does not claim to have read every page. |
| Comparison matrices | Multiple documents, standard/custom columns, source-linked cells, manual corrections, edit history, CSV export | Uncited user entries and unreviewed extraction results are labeled separately. A cited quote is not automatic confirmation of the interpretation. |
| Evidence notebooks | Claims/questions, exact quotations, supporting/conflicting/qualifying/context classifications, separate user interpretation, CSV export | Relationship classifications are user assertions. Saved evidence retains its quotation and version-specific source ID. Reprocessed source links are checked for staleness. |
| Advanced reader | Page image and text, precise page links, text highlights, rectangular annotations/comments, side-by-side documents, PDF region capture, annotated-PDF export | Export creates a new PDF; originals are unchanged. Geometric text highlights require available word boxes. Legacy/unlocatable excerpts export as labeled comments. Stale annotations block PDF export until reviewed/removed. |
| Research graph | Interactive papers/authors/tags, manual relationships, extracted citation candidates, optional OpenAlex citation edges | Edge types and provenance are distinct. Shared authors/tags and citation links are not evidence that papers agree. Graph display is capped at 70 nodes; a relationship list is available. |
| Version tracking | User-confirmed version groups; line-based text differences; preserved annotations on each original; additional attachments; non-destructive duplicate merge | Versions are linked manually. Extracted-text differences may reflect layout/OCR changes. Annotations are never silently moved between versions. |
| Systematic reviews | Criteria, assigned reviewer labels, abstract/full-text stages, exclusion reasons, conflicts, adjudication, screening counts, immutable decision events, audit CSV | Reviewer names are local labels, not authenticated identities. Counts describe records assigned to the review; they are not an automatically certified PRISMA report. Changing abstract decisions invalidates dependent full-text decisions until reassessed. |
| Research status alerts | On-demand Crossref checks, optional daily polling, reported updates/retractions in the library, links to notices, checked timestamps, stale-on-failure results | Coverage depends on deposited metadata. “No updates reported” is not “verified safe.” Network services can be unavailable. |
| Smart inbox/automation | Existing-tag and collection-name suggestions in Insights; watched folders; post-processing rules; apply rules to existing items; exact duplicate prevention | Suggestions are conservative text matches, not automatic judgments. Watched folders poll every 30 seconds while the app runs; only direct supported files are copied, and originals remain untouched. |

## Configure generative AI

1. Open **Research workspace → AI & alerts**.
2. Enter a Chat Completions-compatible API base URL, such as the provider's documented `/v1` endpoint, and an exact model identifier supported by that provider.
3. Set the credential in the environment of the Flask process, then restart it:

   ```sh
   source .venv/bin/activate
   export SYNOPSIS_AI_API_KEY='your-provider-key'
   python app.py
   ```

4. Enable the provider in the application. In Search & ask, explicitly select **Request AI synthesis**, or click **AI summary draft** in Insights.

The connector sends `POST {base_url}/chat/completions` with `messages` and `response_format: {"type":"json_object"}`. The provider/model must support that interface. A compatible local server can use an HTTP loopback URL, for example `http://127.0.0.1:11434/v1`; a model must actually be installed and served there. External endpoints require HTTPS. API keys are not returned to the browser or included in library backups.

External processing is never silently substituted for local search. Provider failures, invalid JSON, missing citations, unknown passage IDs, invented quotes, and stale sources reject the generated answer. Even an exact valid quotation can be misinterpreted by a model; generated claims remain reviewable drafts.

The optional interface follows the [Chat Completions JSON-output contract](https://developers.openai.com/api/docs/guides/structured-outputs). No credentialed external generative model was used in the automated test suite; its HTTP contract is tested against a local controlled provider fixture.

## Local model and optional data services

Semantic search uses `BAAI/bge-small-en-v1.5` through FastEmbed/ONNX. Its initial setup downloads model weights; inference runs locally. The default model cache is `data/models/` under the application directory. Set `SYNOPSIS_MODEL_CACHE` to use another cache location. The setup for this workspace has already downloaded and exercised the model.

OpenAlex discovery uses a DOI and adds cited-work identifiers from its record. Optionally set `SYNOPSIS_OPENALEX_KEY` for authenticated API requests. The key is sent as a bearer header, not in the URL. Crossref status checks query update notices targeting a DOI. These actions send identifiers, not full document text.

References: [FastEmbed](https://github.com/qdrant/fastembed), [OpenAlex authentication](https://help.openalex.org/api/authentication/), [Crossref update filters](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/).

## Recovery and existing libraries

SQLite tables are added without replacing existing library records. Existing documents continue to work; **Paper insights → Reprocess OCR** upgrades a document with page geometry, language, provenance, and tables. Preserve old evidence as a historical snapshot if OCR changes: the reader flags stale passage links, and PDF export rejects stale geometric annotations.

Version-2 backups include research entities (notebooks, matrices, reviews, versions, relations, rules, watcher configurations, and status snapshots) alongside original files and metadata. The recovery command accepts both original version-1 and version-2 backups. Recovered watchers and generative AI are disabled until explicitly re-enabled; this avoids automatically scanning obsolete local paths or transmitting text after a restore. Search vectors can be rebuilt and model weights are not included in a backup.

This remains a local single-user web application. Browser capture extensions, authenticated multi-user sync, shared cloud libraries, and Word/Google Docs/LibreOffice live citation integrations remain separate work; advanced research features do not imply those integrations exist.
