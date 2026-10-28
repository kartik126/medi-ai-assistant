# PDF and Word uploads

The document picker and upload API accept `.pdf`, `.doc` and `.docx`, including mixed batches. The existing single document-selection control still searches all ready uploads by default, with optional narrowing. Session boundaries, duplicate detection, limits and grounded answering apply to every format.

## Local conversion and citations

PDF uploads retain their existing extraction and physical-page behavior. Word files are validated and converted locally with LibreOffice into a saved PDF, then use the same extraction, chunking, embedding, retrieval and citation pipeline. The original `.doc`/`.docx` bytes and filename are retained. Source cards label Word citations as **converted PDF pages**, because Word pagination can change with fonts or renderer. A download link in the Documents sidebar retrieves the original Word file.

- `GET /sessions/{sid}/documents/{did}/file` serves the cited PDF for every supported type. For Word, this is the saved conversion.
- `GET /sessions/{sid}/documents/{did}/original` downloads the original uploaded bytes with the appropriate content type.
- `GET /sessions/{sid}/documents/{did}/pages/{number}` returns the exact stored extracted text for the cited PDF page.

Both file routes enforce session membership. Existing PDFs and document IDs require no migration or re-upload. Word originals are stored as generated `<document-id>.doc[x]` names beside `<document-id>.pdf`; original hashes and byte counts refer to the uploaded Word file. Database metadata/pages/vectors and both files are committed together with staging/rollback cleanup. Expiry/reset removes both forms. Startup reconciliation removes generated orphan Word files while preserving unrelated notes.

## Setup

Install LibreOffice on the host, alongside the existing host Python/Ollama services:

```bash
brew install --cask libreoffice
```

The app detects `soffice`, `libreoffice`, or `/Applications/LibreOffice.app/Contents/MacOS/soffice`. Override `LIBREOFFICE_BIN` when needed. `WORD_CONVERSION_TIMEOUT_SECONDS` defaults to 90 seconds. `/health` reports `word_converter_ready` separately; a missing converter does not disable existing PDF/model/database readiness. The UI shows a Word-conversion availability message and the API returns an actionable error for Word intake if it is unavailable.

Conversion uses LibreOffice's [documented headless conversion and isolated-profile options](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html) and [Writer PDF export](https://help.libreoffice.org/latest/en-US/text/shared/guide/pdf_params.html). Each conversion gets a temporary private profile and generated input name, disabled macro execution/active embedded content, highest macro-security setting and no automatic link updates; document contents and conversion output are not logged. Conversion is serialized and bounded by a timeout; timeout kills only its own process group. Profiles and intermediate files are removed afterward. This is a local demo converter, not a process/container sandbox for hostile Office files.

## Validation and limits

- DOCX must be a valid Word OOXML ZIP package. Expanded data is limited to 100 MiB and 5,000 entries. Duplicate package entries, encrypted ZIP entries and embedded VBA payloads are rejected.
- Legacy DOC must have a Word compound-file signature/stream. RTF/HTML renamed `.doc`, `.docm` and `.dotx` are not accepted; save as `.docx` instead.
- Input size/file-count/aggregate-page budgets still apply. Each converted PDF must fit the per-file size budget; derived Word PDFs additionally share an aggregate size budget. Over-page, conversion, model or transaction failures preserve previously ready documents.
- Locked/corrupt Word documents may fail conversion; unlock/re-save or export a PDF locally. Scans/images still need OCR and remain unsupported. Complex tables, tracked changes, missing fonts and renderer layout differences remain limitations. Inspect the cited saved PDF to confirm the actual rendered content/page.

Tests cover real DOCX and legacy DOC conversion, forced page breaks and table text, mixed upload/error handling, original/downloaded bytes, duplicate uploads, source/answer page citations, cross-session isolation, page limits, conversion timeout/missing dependency, rollback of both files and cleanup. **Final verification:** 172 automated tests passed, no skips; all three live Word/PDF cases passed. LibreOffice 26.8.1.1 was installed and used on this Mac. Both pages of the converted synthetic fixture were rendered and visually inspected. Eight existing uploaded documents and their saved PDF hashes are unchanged. All temporary live-test documents/directories were removed. Raw local responses and uploaded source documents are excluded from Git. See the [verification summary](verification.md). Human/clinical validation remains pending.
