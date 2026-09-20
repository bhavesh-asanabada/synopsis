# Synopsis

A local-first research library built with **Python and Flask**, SQLite, and a browser interface. Add a document, extract or OCR its text, retrieve metadata from its DOI, and keep your references, notes, and citations together.

Synopsis includes a working library and an advanced research workspace, **not yet a complete Zotero replacement**. See [the feature matrix](docs/FEATURES.md) for implemented features and the remaining parity work.

![Synopsis home page](synopsis/static/home-page.png)

## Install

Python 3.11+ and the Tesseract command-line engine are required.

```sh
# macOS
brew install tesseract

# Ubuntu/Debian alternative
# sudo apt-get install tesseract-ocr

python3 -m venv .venv
source .venv/bin/activate
pip install .
```

Once installed, type `synopsis` in the terminal (or Command Prompt/PowerShell on Windows) to start the app and open it in your browser, the same way you'd launch a desktop app like Zotero:

```sh
synopsis
```

Run it again any time to reopen your library. Data is stored in `~/.synopsis/data` by default; set `SYNOPSIS_DATA_DIR=/absolute/path` before running `synopsis` to use another location, and `PORT=5002 synopsis` to use another port. Set `SYNOPSIS_NO_BROWSER=1` to start the server without opening a browser tab automatically.

On Windows, install Tesseract and add it to PATH. OCR settings show whether the engine is available. For additional OCR languages, install the corresponding Tesseract language data (`brew install tesseract-lang` on macOS); installed languages appear in Settings.

## Run from source

To run from a source checkout instead of installing the package, there is no Node.js or frontend build requirement:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5001**. The application uses Waitress and binds to the loopback interface. Change the port with `PORT=5002 python app.py`. Data is stored in `data/` next to `app.py` in this mode.

## Your first reference

1. Click **Add to library**, or drop documents anywhere on the page. Supported files: PDF, PNG, JPEG, TIFF, WebP, DOCX, UTF-8 TXT, and Markdown. A batch may contain up to 20 documents and 100 MB total.
2. The original file is saved immediately. A background job extracts text from every PDF page, using Tesseract on pages with little or no embedded text. Images and multi-page TIFFs are OCR'd. DOCX text and tables are extracted directly.
3. When a DOI is found near the beginning of the document, Synopsis queries Crossref for title, authors, year, publication, and other bibliographic fields. Without a matching DOI it uses embedded metadata and conservative text heuristics. Uncertain fields remain editable, and every processed document goes to **Needs review**.
4. Select the reference to review or edit metadata, add tags/collections, take notes, or open its original document and extracted text.
5. Use **Cite** for APA, MLA, Chicago author–date, or Vancouver bibliographies, or export selected references as BibTeX, RIS, or CSL-JSON.

The library starts empty. No sample references are inserted into your research.

To remove documents permanently, open **Trash**, check the references to remove, and click **Delete permanently**. Review the titles in the confirmation dialog before confirming. This deletes the selected references and their saved document files. References still cited by research records or attached to other references are kept, with the reason shown. You can also permanently delete a single trashed reference from its details pane.

## Advanced research workspace

Open **Research workspace** to use semantic search, source-linked questions and summaries, evidence notebooks, comparison matrices, an advanced reader, research graphs, version diffs, systematic reviews, watched folders, automation rules, and publication-status alerts. Optional generative AI supports configurable external or local compatible providers.

Configure generated answers in **Settings & backup → AI model**: enter the provider API URL, model identifier, and optional API key, then **Test model** and **Save preferences**. Enable AI answers and summaries to use the selected model on requested synthesis.

Read the [advanced feature guide](docs/ADVANCED.md) for workflows, provider configuration, source-validation behavior, and accuracy boundaries. The [test guide](docs/TESTING.md) explains what is verified and what requires real-corpus review.

## Chat workspace

Use **Ask Synopsis** at the bottom right or **Chat workspace** in the sidebar. Select or upload documents, ask follow-up questions with source links, optionally search the web, generate images, and create downloadable architecture diagrams. Conversations and generated artifacts are saved locally and included in backups.

Configure the text model and optional image model and Brave Search key in **Settings & backup**. See the [chat setup and usage guide](docs/CHAT.md) for supported providers, modes, downloads, and processing boundaries.

## Cloud document storage

Connect **Google Drive** or **OneDrive** in **Settings & backup → Cloud document storage**, then choose where new documents should be saved. Local originals remain available for OCR and offline reading. Each document shows transfer status and retry controls; existing documents can be copied using **Save to cloud** in their details pane.

Each connector requires an OAuth application registration and account consent. Follow the [cloud storage setup guide](docs/CLOUD_STORAGE.md). Cloud copies are retained when a local reference is deleted; metadata and notes are not synchronized.

## Storage and privacy

- SQLite metadata: `data/synopsis.sqlite3`; original documents: `data/uploads/`.
- Change **Settings & backup → Document storage → Upload folder** to save new documents elsewhere. Enter an absolute path or a path starting with `~`, or click **Browse…** to pick a folder with the operating system's native folder dialog (requires Tk on the computer running Synopsis). Missing folders are created and write access is checked when saving. This includes watched-folder imports. Existing documents stay in their original folders and remain readable. **Use default folder** resets the destination for future uploads. Keep old folders available while their documents remain in your library.
- Library backups include registered documents from all storage folders, excluding unrelated files. Restoring places the documents in the restored library's `uploads/` folder.
- Search includes bibliographic fields, extracted/OCR text, tags, notes, and highlights.
- OCR and semantic embedding inference run locally. DOI lookup, status checks, and citation discovery send identifiers to Crossref/OpenAlex when requested or enabled. Optional AI synthesis sends selected passages to the configured provider only when requested. Connected cloud storage sends the full original document to the selected drive. See [processing controls](docs/ADVANCED.md).
- Identical files are detected with SHA-256 and are not stored twice in the active library.
- Processing failures retain the original attachment and display a retry option. Incomplete jobs resume when the app starts again. Manual field corrections are preserved during processing and retries.
- Use `SYNOPSIS_DATA_DIR=/absolute/path/to/library synopsis` (or `... python app.py` when running from source) to choose another storage directory. The default is `~/.synopsis/data` when installed via `pip install .`, or `data/` next to `app.py` when running from source.
- This release is a single-user application intended to run on localhost. It does not have accounts, remote authentication, cloud sync, or access control for multiple users. Keep the default loopback binding. A public deployment needs authentication, authorized file access, a durable job queue, resource isolation, and operational backups first.

## Backup and recovery

In **Settings & backup**, download a ZIP containing references, notes, highlights, collection hierarchy, OCR text, research workspace records, preferences, and original attachments. Bibliography exports are for exchanging citations; they do not include files or notes.

Restore a ZIP into a **new directory**:

```sh
source .venv/bin/activate
python manage.py restore /path/to/synopsis-backup.zip --data-dir ./recovered-library
SYNOPSIS_DATA_DIR=./recovered-library python app.py
```

The recovery command refuses to overwrite any existing directory and validates attachment paths. Restored watchers and generative AI are paused until you re-enable them. It constructs the recovered library in a temporary directory before making it available. For very large libraries, stop the application and copy the entire `data/` directory instead of generating an in-memory ZIP.

## Development and tests

```sh
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q
```

Tests create isolated temporary libraries. See [the verification matrix](docs/TESTING.md) for the advanced tests. The core tests cover real image/scanned/mixed-PDF OCR, metadata extraction, preserved manual edits, original-file retention on errors, DOCX extraction, collections, searchable notes/highlights, citation styles, reference format round-trips, backup recovery, and a Chromium desktop/mobile workflow. OCR integration tests skip when Tesseract is unavailable. Browser test screenshots are written to `artifacts/`.

For UI development, restart `python app.py` after Python changes and refresh the browser for static files. Use a single server process: PDFium is accessed through one background worker because it is not thread-safe. Do not start multiple WSGI processes against the same library.

## Project structure

- `app.py`: local Waitress entry point and Flask application, for running from a source checkout.
- `pyproject.toml`: packaging metadata and the `synopsis` console-script entry point.
- `synopsis/cli.py`: the `synopsis` command — starts the server and opens it in the browser.
- `synopsis/_paths.py`: default data/model-cache locations for source checkouts vs. installed packages.
- `synopsis/__init__.py`: API, request validation, document access, and backup export.
- `synopsis/storage.py`: SQLite persistence and atomic record updates.
- `synopsis/processing.py`: background text extraction/OCR pipeline.
- `synopsis/cloud.py`, `synopsis/static/cloud.js`: Google Drive/OneDrive account connections, background transfers, and storage controls.
- `synopsis/metadata.py`: metadata heuristics and Crossref lookup.
- `synopsis/citations.py`: CSL bibliography formatting, BibTeX/RIS/CSL import/export.
- `synopsis/templates/index.html`, `synopsis/static/`: responsive, dependency-free browser UI.
- `synopsis/documents.py`: page geometry, OCR confidence, captures, and annotated-PDF export.
- `synopsis/intelligence.py`: local semantic retrieval and source-validated optional synthesis.
- `synopsis/research.py`: advanced research API.
- `synopsis/chat.py`, `synopsis/chat_tools.py`, `synopsis/diagrams.py`: conversations, optional web/image providers, and passive SVG architecture rendering.
- `synopsis/workflows.py`: systematic reviews, diffs, and research graph.
- `synopsis/services.py`: status/discovery services, folder intake, and organization rules.
- `synopsis/static/research.js`, `synopsis/static/research.css`: research workspace interface.
- `manage.py`: offline backup recovery.
- `tests/`: API, processing, storage, and browser integration tests.

## Current limits

OCR quality depends on scan quality and the installed language. Pages with at least 40 non-whitespace embedded characters use their existing text layer; image regions on those pages are not independently OCR'd. DOCX embedded images are not OCR'd. Handwriting, complex layouts, and encrypted PDFs need manual attention. DOI detection currently scans the first 20,000 extracted characters; metadata enrichment uses Crossref, not arbitrary title matching or ISBN/PubMed lookup.

The advanced reader supports geometric highlights and region comments and exports a new annotated PDF. Text without geometry remains explicitly unpositioned. Additional originals can be linked as attachments or versions. Search is aimed at personal libraries, not millions of records; semantic vectors are cached locally. Backups are generated in memory. The four built-in citation options use packaged CSL definitions through citeproc-py; verify publisher-specific formatting requirements before submission.

Built using [Flask](https://flask.palletsprojects.com/), [Tesseract](https://github.com/tesseract-ocr/tesseract), [pypdf](https://pypdf.readthedocs.io/), [pypdfium2](https://pypdfium2.readthedocs.io/), [Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/), and [citeproc-py](https://github.com/citeproc-py/citeproc-py).
