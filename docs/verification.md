# Verification summary

This is a local document-research prototype. The following are observed development checks, not a clinical accuracy estimate or independent medical validation.

## Automated checks

The latest implementation run passed **201 tests with no skips**, including real PostgreSQL/pgvector integration and API/UI checks. Six upstream deprecation warnings were reported. Coverage includes ingestion failures, per-session/document scope, citation resolution, blank versus filled fields, table projection, Word conversion, original-byte preservation, concise summaries and rejection of changed values/units/identifiers or unsupported certainty.

Tests inject model responses for deterministic behavior. They do not measure the medical accuracy of the live model. For commands and the isolated test database setup, see the [README](../README.md#verification-and-developer-checks).

## Live-model development checks

The configured local models are `gemma3:4b` and `qwen3-embedding:0.6b` through Ollama.

- Earlier evidence-selection/table repairs passed 53 development scenarios and three Labcorp table checks. The table checks included TP53 variant allele frequency (17.9%) and ERBB2 gain fold change (7.1), with citations to physical page 4. Production code derives fields from document text coordinates; these expected values appear only in tests/evaluation.
- Word support passed three live cases across mixed DOCX, DOC and PDF uploads, with converted-page citations and original-file preservation.
- The later paraphrasing change initially passed **50/56** automatic live checks. Four valid answers were rejected by conservative checks; two supported weekly-activity answers missed a narrow wording regex. After refinements, all six cases passed targeted replay against unchanged expectations. The other 50 were not rerun on that last refinement; this was not a fresh all-56 final-revision run.
- Three final case-report checks covered a treatment/outcome paraphrase, age/location and an explicit verbatim request. Exact quotations were checked against stored page text, cited PDFs were fetched, and original uploaded bytes were preserved.

The summary verifier uses the same local model family as the writer. It can make mistakes and is not an independent clinical reviewer. Automatic string/status/page checks can miss unsupported meaning or reject valid wording. Independent held-out documents and human/clinical acceptance remain pending.

## Setup documentation checks

The verified host profile is Apple M3 / 16 GB, Python 3.11.0, Ollama 0.40.11, PostgreSQL 17.11, pgvector 0.8.7 and LibreOffice 26.8.1.1. `requirements.resolved.txt` matches the installed Python environment and `pip check` passes. The database image is pinned in `compose.yaml`.

README shell syntax, local document links, settings defaults, preservation of an existing `.env`, Docker Compose configuration, backend/model/database readiness, Streamlit health and LibreOffice detection were checked. This is verification of the existing installation, not a clean-machine execution of every external installer.

## Repository contents

Source code, tests, synthetic fixture generators, evaluation specifications and setup/architecture documentation are included. Local `.env` files, uploads, extracted content, model files, caches, screenshots, raw evaluation responses and agent/planning history are excluded by `.gitignore` and retained locally. In particular, `evaluation/*.json` contains test specifications; it is separate from ignored raw `docs/evaluations/` outputs.

Run the generators to create synthetic sample PDFs locally. Optional real-document manifests name their required inputs but do not distribute those PDFs. Never substitute the application's database for the separate test database.
