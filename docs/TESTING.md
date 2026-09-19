# Workflow verification and accuracy

The application does not claim 100% accuracy on arbitrary documents. OCR, document layout inference, language/type suggestions, semantic retrieval, external metadata coverage, and generated interpretations have different failure modes. Tests establish behavior on known cases and protect invariants; they cannot prove universal correctness.

## Run the complete suite

```sh
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q
```

Tesseract is needed for actual OCR integration tests. A local BGE model must be cached (or downloadable) for the real semantic inference test. The workspace's cache is prepared. Tests use temporary libraries and never insert test research into the user's `data/` library.

To generate coverage evidence:

```sh
python -m pytest -q --cov=synopsis --cov=manage \
  --cov-report=term-missing \
  --cov-report=html:artifacts/coverage \
  --cov-report=json:artifacts/coverage.json
```

Coverage is code-execution coverage, not OCR quality, factual correctness, or scientific validity.

## Test cases

| Workflow | Checks |
|---|---|
| Upload → extraction → review | Original saved; OCR produces known text from actual PNG/scanned PDF/mixed PDF; editable metadata; unsupported/empty/password-protected/corrupt files; original retention after errors |
| Structure extraction | DOCX properties/text/tables; native PDF word positions and tables; language/type/provenance; exact text offsets and page hashes |
| Persistence | Reloaded library and notes; processing resumed after restart; concurrent evidence writes do not lose records |
| Semantic retrieval | Actual ONNX inference ranks a paraphrased relevant passage above an unrelated document; deterministic fixtures exercise author/year/scope filters and excluded/trash records |
| Ask / generated answers | Local mode does not transmit text; no-evidence response; explicit provider enablement; validated source IDs/quotes; missing/forged/stale citations rejected; invalid provider response and timeouts |
| Provider transport | Actual HTTP request/response against a controlled loopback provider; JSON response contract; secret is not exposed to browser/backup; insecure remote URL rejected |
| Evidence notebooks | Exact quotation validation; separate user stance/interpretation; persistence; source deletion protection; stale source rejection; CSV export |
| Matrices | Multiple sources/custom columns; not-found cells; row/source identity validation; manual correction history; spreadsheet formula escaping; CSV export |
| Reader | Browser page selection; region annotation; image capture; precise quote boxes; repeated text offset; new annotated PDF while original bytes remain unchanged; stale geometry blocked |
| Versions / attachments / merge | Text differences; annotations remain on source version; grouping validation; merged originals/notes/tags retained; merged records remain addressable |
| Graph | Different edge kinds for candidates, user assertions, and provider citations; interactive filtering; no automatic agreement inferred from citations |
| Systematic review | Full-text gating; required exclusion reasons; assigned reviewers; conflict detection; adjudication; revised decisions invalidate old dependent assessments; append-only audit export |
| Status services | Update direction matches target DOI; successful checks retained after subsequent outage with a stale/error indicator; provider graph discovery |
| Automation | Stable watched files copied, never moved; duplicate scans are idempotent; forbidden storage-folder watch; post-OCR tag/collection rules |
| Recovery | Original and version-2 ZIP restore; notes, attachments, research evidence, and preferences retained; existing directories never overwritten; AI and watchers paused on restore |
| Browser journeys | Main library workflow; search → evidence → comparison → versions → graph → review → automation → preferences; PDF capture/export; persistence and mobile layout; no browser JavaScript errors |

## Evidence and remaining verification limits

Browser screenshots are generated under `artifacts/`. Live DOI lookup, Crossref publication-status lookup, and OpenAlex citation discovery were smoke-tested separately; deterministic automated tests do not depend on external service uptime.

A real local semantic model is exercised, but the test corpus is small; no benchmark-wide retrieval accuracy percentage is claimed. The tests do not validate every publisher layout, language, handwritten scan, or CSL publishing rule. External generative model behavior requires a configured service/model/key and real-corpus evaluation; the suite tests transport and output validation without claiming those models produce correct interpretations.

Decision identities in a systematic review are user-selected local labels. Authentication, independent reviewer accounts, distributed worker recovery, and cloud synchronization are outside this release's tested scope.

## Latest verification run

Verified on this workspace with Python 3.14.5, Chromium, and installed Tesseract:

- **60 tests passed**, including three browser journeys and actual local OCR/embedding inference.
- **88.27% Python statement coverage** across `synopsis` and `manage.py` (1,467 of 1,662 statements). This is explicitly not 100% coverage or a factual-accuracy percentage.
- JavaScript syntax checks, Python compilation, and `pip check` passed.
- Live Crossref status and OpenAlex citation discovery succeeded for DOI `10.1038/nature14539`.
- Five dependency deprecation warnings originate from PyMuPDF's SWIG types; no test failures occurred.

Coverage details: `artifacts/coverage/index.html` and `artifacts/coverage.json`. The test count and coverage above describe this run, not a guarantee about future inputs or external services.
