# Medical Document Assistant

Upload PDF or Word documents, ask questions in plain English, and check each answer against its original source. The app runs locally and provides concise answers with filename, page and supporting quotation citations.

This guide takes you from installing the required software to asking your first question. The tested setup is a **MacBook Air with an Apple M3 chip and 16 GB memory**. Follow these instructions on an **Apple Silicon Mac running macOS 15 or newer**. Windows, Linux and Intel Mac setup have not been verified for this project; the supplied database image is pinned to the tested ARM64 build.

This is a document research prototype. Its answers require source verification and have not been validated for clinical decisions.

**Jump to:** [First-time setup](#first-time-setup) · [Using the app](#ask-your-first-question) · [Daily startup](#start-again-on-another-day) · [Architecture](#brief-architecture-explanation) · [Troubleshooting](#troubleshooting)

## What you will install

| Software | Purpose | Where it runs |
| --- | --- | --- |
| Python 3.11 | Runs the application | On your Mac, in a project-specific environment |
| Docker Desktop | Runs PostgreSQL and its pgvector extension, which store and search document text | In a local container |
| Ollama | Runs the answer and text-search models | On your Mac |
| LibreOffice | Converts Word documents into PDFs for page citations | On your Mac |

You need an internet connection for the initial software/model downloads. The two models total approximately **4 GB**, with additional disk space needed for Docker, Python, LibreOffice and uploaded files. Once installation and downloads are complete, document processing and answering use local services. **No OpenAI key, cloud account or paid model API is required.**

If the software is already installed, check it using the commands below and skip its installation.

## First-time setup

### 1. Open Terminal

Press **Command + Space**, type **Terminal**, and press **Return**.

For every command block in this guide, copy the text inside the block into Terminal and press Return. Wait until the command finishes and the command prompt returns before continuing. Do not copy the surrounding backticks. If a command reports an error, use the troubleshooting section before moving on.

Some installers ask for your Mac login password. Terminal does not show password characters as you type; type the password and press Return.

### 2. Install Homebrew and Python 3.11

Homebrew installs developer tools on your Mac. Check whether it is present:

```bash
brew --version
```

If you see a version, continue to the Python installation below. If you see `command not found`, install Homebrew using its [official installation command](https://brew.sh/):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the installer prompts, including any Apple Command Line Tools installation. At the end, **run the exact commands shown under “Next steps”** to make `brew` available in Terminal. Then check `brew --version` again. On Apple Silicon, Homebrew normally installs under `/opt/homebrew`.

Install the project's [Python 3.11 version](https://formulae.brew.sh/formula/python@3.11):

```bash
brew install python@3.11
python3.11 --version
```

**Checkpoint:** the last command prints `Python 3.11.x`. The final number can vary. Use `python3.11` when creating the environment below, even if another Python version is installed.

### 3. Install and start Docker Desktop

1. Open the [official Docker Desktop for Mac installation page](https://docs.docker.com/desktop/setup/install/mac-install/).
2. Download **Docker Desktop for Mac with Apple silicon**.
3. Open the downloaded `.dmg` file and drag Docker into **Applications**.
4. Open **Docker** from Applications, complete its setup prompts and wait for its engine to be running. Keep Docker open while using the app.

In Terminal, run:

```bash
docker --version
docker compose version
docker info
```

**Checkpoint:** the first two commands show version numbers, and `docker info` shows a Server section without a connection error. Docker Desktop includes Docker Compose; you do not need to install PostgreSQL separately.

### 4. Install Ollama and download both models

Download the Mac app from [Ollama](https://ollama.com/download/mac), move it into **Applications**, then open it. Follow its setup prompts, including installation of the `ollama` command if requested. See the [official macOS instructions](https://docs.ollama.com/macos). Keep Ollama running.

Open a fresh Terminal tab if the command is not available immediately, then run:

```bash
ollama --version
ollama list
```

Download the two exact model names used by this project:

```bash
ollama pull qwen3-embedding:0.6b
ollama pull gemma3:4b
ollama list
```

Downloads can take time depending on your connection. Wait for each pull to finish successfully. If a download is interrupted, repeat the same pull command; Ollama reuses completed download data.

**Checkpoint:** `ollama list` contains **both** `qwen3-embedding:0.6b` and `gemma3:4b`. The first model finds relevant passages; the second selects evidence, writes answers and checks summaries. You do not need to chat in the Ollama app or run `ollama run`.

The Ollama desktop app starts its local service. Use `ollama serve` only if you are using the command-line installation without a running service; leave that command in its own Terminal tab. An “address already in use” message on port 11434 usually means Ollama is already running.

### 5. Install LibreOffice for Word uploads

```bash
brew install --cask libreoffice
```

Open **LibreOffice** from Applications once and complete any first-launch prompts. You may close its document window afterward; the application starts its converter automatically when needed.

Check the converter:

```bash
/Applications/LibreOffice.app/Contents/MacOS/soffice --version
```

**Checkpoint:** a LibreOffice version is displayed. PDF uploads work without LibreOffice, but `.doc` and `.docx` uploads need it. You can also use the [official LibreOffice download](https://www.libreoffice.org/download/) and install the Apple Silicon Mac version into Applications.

### 6. Open the project folder in Terminal

Download the [project ZIP from GitHub](https://github.com/kartik126/medi-ai-assistant/archive/refs/heads/main.zip), or copy the complete project folder to your Mac. Double-click the ZIP in Finder to extract it. The folder must contain `README.md`, `requirements.resolved.txt`, `compose.yaml`, `.env.example`, `backend` and `frontend`.

To enter the correct folder without typing a long path:

1. In Terminal, type `cd` followed by a space. **Do not press Return yet.**
2. Drag the extracted project folder from Finder into the Terminal window.
3. Press Return, then run:

```bash
pwd
ls
```

**Checkpoint:** `pwd` prints the project folder's location and `ls` lists the files above. All remaining project commands must run from this folder. Its name may differ if the download added a suffix.

### 7. Create the Python environment and install dependencies

A virtual environment keeps this app's Python packages together, separate from other projects. Run:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.resolved.txt
python -m pip check
```

**Checkpoint:** `python --version` shows Python 3.11, and the final command says `No broken requirements found`. Your prompt will usually start with `(.venv)` while this environment is active.

`requirements.resolved.txt` contains the exact package versions in the verified local environment. `requirements.txt` contains broader compatibility ranges for development; use the resolved file for this walkthrough. Installation still needs to succeed on your machine before that machine is considered verified.

Run `source .venv/bin/activate` again whenever you open a new project Terminal tab. You only create the environment and install packages once.

### 8. Create the settings file (`.env`)

The `.env` file tells the app where its local database and models live. Create it from the supplied template, preserving any existing settings:

```bash
if [ ! -f .env ]; then
  cp .env.example .env
fi
```

**No editing is needed for a fresh local installation.** These are the important defaults already in the template:

```dotenv
DATABASE_URL=postgresql://medical_ai:local_dev_only@127.0.0.1:5433/medical_ai
POSTGRES_USER=medical_ai
POSTGRES_PASSWORD=local_dev_only
POSTGRES_DB=medical_ai
API_BASE_URL=http://127.0.0.1:8000
OLLAMA_BASE_URL=http://127.0.0.1:11434
CHAT_PROVIDER=ollama
CHAT_MODEL=gemma3:4b
EMBEDDING_MODEL=qwen3-embedding:0.6b
DATA_DIR=./data
```

The sample database password is for this localhost demo. If you customize credentials, the username/password/database in `DATABASE_URL` must match the three `POSTGRES_*` settings. The database uses **5433 on your Mac** and **5432 inside Docker**. Changing `.env` does not change credentials in an already initialized database volume; see troubleshooting before making that change.

The `.env` file is hidden in Finder by default and is excluded from Git. Python loads it automatically when started from the project folder; Docker Compose also reads it. Restart the Python services after changing settings. Existing shell environment variables can override `.env` values.

### 9. Start the database and create its tables

Make sure Docker Desktop is still running. In the project Terminal tab, run:

```bash
docker compose up -d --wait db
docker compose ps
python scripts/migrate.py
```

The first run downloads the database image. `-d` keeps the database running in the background; `--wait` waits for its health check. The migration command creates the required tables and vector extension and can be repeated safely.

**Checkpoint:** `docker compose ps` shows `db` as healthy and Python prints `Database migrations applied.` The supplied `compose.yaml` already configures PostgreSQL, pgvector, local credentials, a health check and persistent storage.

### 10. Start the backend — Terminal tab A

The backend processes uploads and questions. In the same tab, with `(.venv)` active:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

**Leave this tab open.** The command keeps running, so you will not get a new prompt. Wait for `Application startup complete`.

Open [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) in your browser. It displays a small status report.

**Checkpoint:** the top-level `ready` is `true`, both `database.ready` and `models.ready` are `true`, and `config.word_converter_ready` is `true` for Word support. A running backend can still report `ready: false` if the database or models are unavailable. Word-converter readiness is reported separately.

### 11. Start the interface — Terminal tab B

Press **Command + T** in Terminal to open another tab. Enter the same project folder using the Finder drag method from step 6, then run:

```bash
source .venv/bin/activate
python -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501 --server.maxUploadSize 20
```

**Leave this tab open too.** Open [http://127.0.0.1:8501](http://127.0.0.1:8501) in your browser. This is the chat interface; port 8000 is the backend.

**Checkpoint:** the sidebar says **Local services connected**. Your local installation is ready.

## Ask your first question

1. In the sidebar, choose one or more `.pdf`, `.doc` or `.docx` files.
2. Click **Upload selected files** and wait until the documents are marked ready.
3. All uploaded documents are searched by default. Use **Documents to use for answers** above the chat to narrow the search when desired.
4. Ask a complete question, such as “What was the patient's age, and where was the mass located?” if those facts are in your document.
5. Expand a citation such as `[S1]` to inspect its supporting quotation. Use **Open original PDF** / **Open cited PDF**, or **Show extracted page text**, to verify it.

For a sample without supplying your own documents, open another project Terminal tab, activate `.venv`, and run:

```bash
python scripts/create_demo_fixtures.py
```

Upload `data/fixtures/training-a.pdf` and `data/fixtures/training-b.pdf` through the interface. Ask **“Who is the fictional training coordinator?”** The expected fact is **Mira**, cited to physical page 1 of `training-a.pdf`. Ask **“What color is the badge printer?”** to check retrieval from the second document: **violet**, page 1 of `training-b.pdf`. The fixtures contain fictional training facts and are marked synthetic.

The first model request can be slower while weights load. Questions are standalone: the app displays previous messages but does **not** send chat history into retrieval or the model. Include the document or subject in each question rather than relying on “What about that?”

## Start again on another day

You do not need to reinstall software or download models again.

1. Open **Docker Desktop** and **Ollama** and wait for them to start.
2. In Terminal tab A, enter the project folder, then run:

```bash
source .venv/bin/activate
docker compose up -d --wait db
python scripts/migrate.py
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

3. In Terminal tab B, enter the same project folder, then run:

```bash
source .venv/bin/activate
python -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501 --server.maxUploadSize 20
```

4. Open [http://127.0.0.1:8501](http://127.0.0.1:8501). Check `/health` if the sidebar reports a connection problem.

If the app is already running, use the existing tabs and browser window instead of starting duplicate processes.

## Stop the app and retain your data

Press **Control + C** in tab B to stop the interface, then **Control + C** in tab A to stop the backend. In a project tab, stop the database:

```bash
docker compose stop db
```

You may then quit Ollama and Docker Desktop. These steps keep the model downloads and stored documents, subject to the session-expiry behavior below.

The sidebar button **Clear session and documents** intentionally deletes that session's uploaded files and database records. It is not required for shutdown. Avoid `docker compose down -v`: it removes the database volume.

## Brief architecture explanation

The app uses **retrieval-augmented generation (RAG)**: it searches the uploaded documents for relevant passages before asking the model to answer.

```mermaid
flowchart LR
    U[Browser / Streamlit] --> A[FastAPI backend]
    A --> P[PDF extraction / local Word conversion]
    P --> E[Ollama: text embeddings]
    E --> D[(PostgreSQL + pgvector)]
    A --> R[Search selected documents]
    D --> R
    R --> G[Gemma 3: evidence selection and checked summary]
    G --> C[Answer + exact quotation + filename/page citation]
    C --> U
```

- **Ingestion:** LibreOffice converts Word uploads locally into saved PDFs. PyMuPDF extracts text per physical page. Structure-aware chunks preserve nearby sections/paragraphs within size limits and never cross pages. Ollama's `qwen3-embedding:0.6b` turns chunks into searchable numeric representations stored with their source metadata in PostgreSQL/pgvector.
- **Answering:** FastAPI searches only the current session's selected documents. `gemma3:4b` selects evidence and drafts concise prose. Checks cover citations, values, units, identifiers and qualifications; a separate local-model request checks summary support/completeness. Bounded repair is allowed, otherwise the app abstains. Supported table lookups retain precise field/value statements.
- **Verification:** the backend attaches original quotations and server-resolved filename/page citations. Source cards keep quotes separate from the paraphrased answer. PDF citations use physical pages; Word citations use the saved **converted PDF page**, which can differ from Word-editor pagination.

Only PostgreSQL runs in Docker. Python, Ollama and LibreOffice run directly on the Mac. The model is not fine-tuned; no vision/OCR pipeline or hosted inference adapter is used. The implemented generator is Gemma 3 through Ollama; the earlier MedGemma/MLX candidate was not verified. See the [architecture details](docs/architecture.md), [question flow](QUESTION_FLOW.mmd) and [summary safeguards](docs/grounded-summaries.md).

## Data, sessions and supported inputs

| Item | Default behavior |
| --- | --- |
| Supported files | Text-based PDF, DOC and DOCX; mixed uploads allowed |
| Upload limits | 5 documents/session, 20 MiB/file, 50 MiB total uploaded bytes, 300 total PDF/converted pages |
| Database storage | Metadata, extracted pages, chunks and vectors in Docker's `postgres_data` named volume |
| File storage | Originals and converted PDFs under `data/sessions/` |
| Model storage | Managed separately by Ollama, normally under `~/.ollama/` on macOS |
| Session recovery | The browser URL includes a session ID; retain that URL to reopen its documents |
| Chat memory | Display-only within the Streamlit browser session; never model memory and not durably saved as conversation history |
| Expiry | Backend startup removes sessions whose last recorded upload/chat activity is older than the configured 24-hour TTL |

Keep the database volume **and** `data/sessions/` together when preserving an installation. Quitting the browser does not itself delete uploaded files. The session link grants access to that local session; the prototype has no user login and binds to localhost. Document processing uses the configured local Ollama service; there is no automatic cloud fallback. App logs avoid document/question content, and the documented backend command disables URL access logs.

Scanned/image-only documents need OCR and are unsupported. Corrupt/encrypted PDFs and unconvertible Word files return errors. Mixed PDFs can retain extractable pages with warnings. Complex tables and multi-column layouts can fail or cause abstention. A citation proves where a quotation came from, not that an answer is medically correct; review sources. The same-model summary checker is not independent clinical validation.

## Configuration reference

For normal use, leave the supplied defaults unchanged. The complete editable template is [`.env.example`](.env.example); validation rules are in [backend/config.py](backend/config.py). If you adjust file size, also align Streamlit's `--server.maxUploadSize` flag.

<details>
<summary>Optional settings and their defaults</summary>

| Settings | Defaults / meaning |
| --- | --- |
| `MAX_FILES`, `MAX_FILE_MB`, `MAX_TOTAL_MB`, `MAX_TOTAL_PAGES` | `5`, `20`, `50`, `300`; session upload limits |
| `CHUNK_TARGET_CHARS`, `CHUNK_OVERLAP_CHARS`, `CHUNK_MAX_CHARS` | `1500`, `200`, `2000`; chunk size/overlap bounds |
| `EMBEDDING_BATCH_SIZE` | `8`; chunks embedded per batch |
| `RETRIEVAL_CANDIDATES` | `8`; initial retrieval candidates |
| `MAX_CONTEXT_CHUNKS`, `MAX_CONTEXT_CHARS` | `6`, `8000`; evidence budget |
| `MODEL_CONTEXT_TOKENS`, `MAX_OUTPUT_TOKENS` | `16384`, `512`; local model context/output budgets |
| `MODEL_TIMEOUT_SECONDS` | `120`; model HTTP timeout; UI requests have a separate 300-second timeout |
| `MIN_SIMILARITY` | `-1.0`; uncalibrated retrieval floor, not a confidence score |
| `SESSION_TTL_HOURS` | `24`; session-expiry threshold at backend startup |
| `WORD_CONVERSION_TIMEOUT_SECONDS` | `90`; bounded Word conversion |
| `LIBREOFFICE_BIN` | Auto-detected; set to `/Applications/LibreOffice.app/Contents/MacOS/soffice` for a custom override |

Changing the embedding model or its identity can make an existing session incompatible; start a new session and upload documents again. Changing ports requires matching settings and launch/Compose commands. Keep PostgreSQL's container port at 5432.

</details>

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `brew`, `python3.11`, `docker` or `ollama`: command not found | Complete that tool's installation and PATH/command-line prompts, then open a new Terminal tab. For Homebrew, run the installer's “Next steps.” |
| Cannot open `requirements.resolved.txt`, missing `backend`, or cannot activate `.venv` | You are probably in the wrong folder. Repeat the Finder drag method, run `ls`, then activate the environment. |
| `ModuleNotFoundError` | From the project folder run `source .venv/bin/activate`, then repeat the dependency installation and `python -m pip check`. |
| Cannot connect to Docker daemon | Open Docker Desktop and wait for its engine. Check `docker info`, then retry database startup. |
| Database unhealthy / backend says database unavailable | Run `docker compose ps` and `docker compose logs --tail 50 db`. Confirm `.env` credentials/port, then run `python scripts/migrate.py`. |
| Database password authentication failed after editing `.env` | An existing volume retains its original credentials. Restore the matching settings or arrange an intentional credential change. Do not delete the volume as a routine fix. |
| Ollama unavailable / failed connection to port 11434 | Open Ollama, run `ollama list`, and confirm both exact tags are installed. A CLI-only installation needs `ollama serve` in its own tab. |
| Download interrupted or disk full | Free disk space, then repeat the same `ollama pull` command. Check that both models appear in `ollama list`. |
| `word_converter_ready: false` | Install LibreOffice into Applications, complete its first launch and restart the backend. Use the optional `LIBREOFFICE_BIN` override for another location. |
| Address/port already in use | Check for an already running app in your other tabs. Use it or stop that specific process with Control + C before restarting. Do not start a second Ollama server. |
| Interface cannot reach API | Leave tab A running, check [backend health](http://127.0.0.1:8000/health), and confirm `API_BASE_URL=http://127.0.0.1:8000` in `.env`. |
| Slow request / model busy | Wait for the current request to finish and close memory-heavy apps. One model operation runs at a time. Initial loading is slower; Word conversion and indexing add work. |
| Session no longer exists | It may have expired or been cleared. Click **Start a new session**, then upload documents again. |
| Not enough evidence / summary validation failed | Check the selected documents and extracted page text, then ask a specific question. Blank form fields, missing text and unsupported facts should not be guessed. |

Useful service addresses:

| Service | Address |
| --- | --- |
| Chat interface | [http://127.0.0.1:8501](http://127.0.0.1:8501) |
| Backend readiness | [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) |
| Interactive API documentation | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |
| Ollama service | `http://127.0.0.1:11434` |
| PostgreSQL from your Mac | `127.0.0.1:5433` |

## Verification and developer checks

Verified local profile: Python 3.11.0, Ollama 0.40.11, PostgreSQL 17.11, pgvector 0.8.7 and LibreOffice 26.8.1.1 on Apple M3 / 16 GB. The database image digest is pinned in `compose.yaml`; exact Python package versions are recorded in `requirements.resolved.txt`. Installer updates can change tool versions, so use the readiness checks on your installation.

The latest implementation verification passed **231 automated tests**, including real PostgreSQL integration. Live summary checks initially passed 50/56 automatic cases; all six remaining cases passed targeted replay after fixes, while the other 50 were not rerun on that final refinement. These are development results, not a clinical accuracy estimate. See the [verification summary](docs/verification.md). Raw local evaluation outputs and uploaded source documents are excluded from Git.

Optional tests, from an activated project Terminal tab:

```bash
python -m pytest -q
```

Without a test database, database integration tests skip. For the full suite, create a **separate test database** once, using the defaults below. If you customized `.env`, adapt the test credentials too.

```bash
docker compose exec db createdb -U medical_ai medical_ai_test
TEST_DATABASE_URL=postgresql://medical_ai:local_dev_only@127.0.0.1:5433/medical_ai_test python -m pytest -q
```

If `medical_ai_test` already exists, skip its creation. Never point `TEST_DATABASE_URL` at the application's `medical_ai` database; tests require a name ending in `_test`. Integration tests apply their own migrations and clean up their generated sessions. Word conversion tests require LibreOffice.

For optional real-model evaluation, leave all services running and first generate the sample fixtures. Choose a new output filename on each run to preserve results:

```bash
python scripts/evaluate.py --live --output docs/evaluation-local-new.json
```

The script creates its own synthetic-document session, checks expected facts/pages and quote resolution, records actual outputs/timings, and cleans up that session. A nonzero exit can mean failed checks or pending human support review; inspect the report. It does not establish clinical correctness. To annotate that same saved run without new model calls, use a JSON mapping case IDs to `"pass"` or `"fail"`:

```bash
python scripts/evaluate.py --review-results docs/evaluation-local-new.json --reviews path/to/reviews.json
```
