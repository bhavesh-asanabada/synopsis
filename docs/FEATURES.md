# Zotero parity: implementation status

Synopsis now includes the advanced research workspace described in [ADVANCED.md](ADVANCED.md), with its verification matrix in [TESTING.md](TESTING.md). The table below tracks broader Zotero parity; these integrations are distinct from the advanced research feature set. This matrix makes the larger requirement explicit; planned work is not represented as available functionality.

Zotero's [quick-start guide](https://www.zotero.org/support/quick_start_guide), [collections and tags documentation](https://www.zotero.org/support/collections_and_tags), and [sync documentation](https://www.zotero.org/support/sync) informed the scope.

| Area | Available in Synopsis | Remaining work |
|---|---|---|
| Reference library | Persistent SQLite records; eight item types; editable bibliographic fields; list, grid, and table views; selectable and reorderable table columns with browser-saved preferences | Complete Zotero item-type/field schema; multiple creator roles |
| Direct document intake | Multi-file picker and drag/drop; original-file storage; identical-file detection; linked additional attachments; watched-folder copy intake | External linked-file paths without copy; attachment-specific metadata editing |
| OCR | Local Tesseract for images and scanned PDF pages; mixed PDFs; multi-page TIFF; installed language selection; progress; retry; restart recovery; rotation correction; word positions and confidence; language detection; table extraction | Further layout improvements; handwriting; region OCR; job cancellation and distributed workers |
| Automatic metadata | Embedded PDF/DOCX properties; conservative text hints; detected DOI lookup using Crossref; review queue; preserved manual corrections; field provenance | ISBN, PMID, arXiv identifier lookup; publisher translators; metadata reconciliation; title-based matching |
| Organization | Nested collections; tags; stars; read/unread; bulk organization; collection rename/delete; suggestions and automation rules | Saved searches; advanced query builder; tag management and color customization |
| Search | Bibliographic metadata, extracted full text, notes, highlights, tags; local semantic passage retrieval with filters | Indexed full-text ranking, stemming, fuzzy search, large-library pagination |
| Reading | Browser PDF/image reader; page images and text; download original; side-by-side reading; region capture | EPUB/snapshot readers; synchronized page/text view; richer reading controls |
| Notes and annotations | Attached notes; anchored text/region annotations and comments; searchable contents; new annotated-PDF export; evidence notebooks | Standalone/rich-text notes; note editing; ink annotations |
| Citations | CSL-formatted APA, MLA, Chicago author–date, Vancouver; copy bibliography | Custom style installation; citation previews; locale choice; in-text citation editor; complete citeproc compatibility |
| Interchange | BibTeX, RIS, CSL-JSON reference import/export | Zotero RDF/full library import; other translator formats; attachment migration |
| Duplicates | Exact file duplicate prevention; DOI/title duplicate view; non-destructive merge preserving source records, files, and annotations | Fuzzy duplicate suggestions and fine-grained field reconciliation |
| Recovery | Trash, restore, explicit permanent delete, source-deletion protection, version-2 ZIP backup and offline recovery including research records | Scheduled/incremental backup; selective in-app restore |
| Browser capture | Manual entry and DOI lookup | Browser extension; website-specific translators; snapshots; one-click multi-item capture |
| Writing integrations | Copy/paste citations and bibliography exports | Word, LibreOffice, and Google Docs integrations; live citation fields |
| Accounts and sync | Local, single-user library | Authentication; per-user authorization; cross-device sync/conflicts; attachment storage; WebDAV support |
| Collaboration | Not implemented | Group libraries; permissions; invitations; shared annotations; public profiles/publications |
| Extensibility | Python modules and documented application layout | Plugin API; connector protocol; third-party translator ecosystem |
| Deployment | Loopback web application served by Waitress; responsive desktop/mobile UI | Authenticated hosted deployment; resource isolation; durable queue; observability and scaling |

## Suggested implementation sequence

1. Extend the item/attachment model, indexed search, metadata providers, duplicate merging, and reader annotations.
2. Add browser capture and comprehensive Zotero library migration.
3. Introduce authenticated accounts and per-user ownership before any public hosting; add durable jobs and object storage.
4. Implement synchronization and shared/group libraries with explicit conflict handling.
5. Build word-processor integrations and finish citation/translator compatibility.

Cloud and collaboration features require deployment and storage choices. Word-processor integrations and browser capture require separate client applications/extensions, not only Flask routes.
