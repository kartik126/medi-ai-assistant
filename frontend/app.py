import os
from pathlib import Path
from uuid import UUID
import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
st.set_page_config(page_title="Medical Document Assistant", page_icon=":material/description:", layout="wide")
st.markdown("<style>" + Path(__file__).with_name("style.css").read_text() + "</style>", unsafe_allow_html=True)


def request(method, path, **kwargs):
    try:
        with httpx.Client(base_url=BASE, timeout=300, trust_env=False) as client:
            response = client.request(method, path, **kwargs)
        if response.is_error:
            try:
                detail = response.json().get("error", {}).get("message", "Request failed.")
            except ValueError:
                detail = "Request failed. Check the API."
            st.error(detail)
            return None
        return response.json() if response.content else {}
    except httpx.HTTPError:
        st.error("Cannot reach the API, or the request timed out. Check the backend and local services.")
        return None


def start_new_session_button():
    if st.button('Start a new session', key='restart_missing_session'):
        st.session_state.pop('sid', None)
        st.session_state.messages = []
        st.query_params.clear()
        st.rerun()


st.markdown("""<header class="workspace-header">
<div><p class="eyebrow">Document workspace</p><h1>Medical Document Assistant</h1>
<p class="workspace-subtitle">Focused questions. Answers grounded in your documents.</p></div>
<span class="workspace-badge">LOCAL · PAGE-CITED</span></header>""", unsafe_allow_html=True)

if "sid" not in st.session_state:
    resume = st.query_params.get('session')
    if resume:
        try:
            resume = str(UUID(resume))
        except ValueError:
            st.error('Invalid session link.')
            st.stop()
        if request('GET', f'/sessions/{resume}/documents') is None:
            start_new_session_button()
            st.stop()
        st.session_state.sid = resume
    else:
        session = request("POST", "/sessions")
        if session is None:
            st.stop()
        st.session_state.sid = session["session_id"]
    st.session_state.messages = []
sid = st.session_state.sid
if st.query_params.get('session') != sid:
    st.query_params['session'] = sid

with st.sidebar:
    st.markdown("""<div class="brand"><span class="brand-mark">M</span>
    <div class="brand-name">Medical Document Assistant<span class="brand-note">Your research workspace</span></div></div>""", unsafe_allow_html=True)
    st.header("Documents")
    health = request("GET", "/health")
    config = health.get("config", {}) if health else {}
    if health and not health["ready"]:
        st.warning("Database or local models are not ready. Check API /health.")
    if health and health["ready"]:
        st.markdown('<div class="service-status"><span class="service-dot"></span>Local services connected</div>', unsafe_allow_html=True)
    st.caption(f"Up to {config.get('max_files', 5)} files · {config.get('max_file_mb', 20)} MiB per file")
    uploads = st.file_uploader("Choose PDF or Word documents", type=["pdf", "doc", "docx"], accept_multiple_files=True)
    st.caption("PDF · DOC · DOCX. Word citations use converted PDF pages.")
    if config.get("word_converter_ready") is False:
        st.warning("Word conversion is unavailable. Install LibreOffice locally or upload a PDF.")
    if st.button("Upload selected files", disabled=not uploads, type="primary", width="stretch"):
        with st.spinner("Extracting and indexing locally…"):
            results = request("POST", f"/sessions/{sid}/documents", files=[("files", (f.name, f.getvalue(), f.type or "application/octet-stream")) for f in uploads])
        if results is not None:
            for item in results:
                if item["status"] == "ready":
                    doc = item["document"]
                    st.success(f"{item['filename']}: {'already indexed' if doc['duplicate'] else 'ready'}")
                else:
                    st.error(f"{item['filename']}: {item['message']}")
    docs = request("GET", f"/sessions/{sid}/documents")
    if docs is None:
        start_new_session_button()
        st.stop()
    from collections import Counter
    filename_counts = Counter(d["filename"] for d in docs)
    labels = {d["document_id"]: d["filename"] + (f" · {i+1}" if filename_counts[d["filename"]] > 1 else "")
              for i, d in enumerate(docs)}
    if st.session_state.get('selection_sid') != sid or st.session_state.get('selection_ui_version') != 3:
        st.session_state.selected_document_ids = list(labels)
        st.session_state.known_document_ids = list(labels)
        st.session_state.selection_sid = sid
        st.session_state.selection_ui_version = 3
    else:
        # Include new uploads when searching the whole collection. Preserve a
        # deliberate subset (or empty selection) instead of widening it.
        searching_all = set(st.session_state.selected_document_ids) == set(st.session_state.known_document_ids)
        st.session_state.selected_document_ids = (list(labels) if searching_all else
            [did for did in st.session_state.selected_document_ids if did in labels])
    st.session_state.known_document_ids = list(labels)
    names = {d['document_id']: d['filename'] for d in docs}
    if docs:
        st.divider()
        st.caption(f"LIBRARY · {len(docs)} {'DOCUMENT' if len(docs) == 1 else 'DOCUMENTS'}")
    for doc in docs:
        with st.container(border=True, key=f"library-{doc['document_id']}"):
            st.text(doc["filename"])
            file_type = doc["filename"].rsplit(".", 1)[-1].upper()
            st.caption(f"{file_type} · {doc['indexed_page_count']}/{doc['page_count']} pages indexed")
            if doc["filename"].lower().endswith((".doc", ".docx")):
                st.link_button("Download original Word", BASE + f"/sessions/{sid}/documents/{doc['document_id']}/original")
            for warning in doc["warning_pages"]:
                st.caption(f"Page {warning['page_number']}: {warning['warning']}")
    st.divider()
    if st.button("Clear session and documents", width="stretch"):
        if request("DELETE", f"/sessions/{sid}") is not None:
            del st.session_state.sid
            st.query_params.clear()
            st.session_state.messages = []
            st.rerun()


with st.container(border=True, key="source-scope"):
    selected = st.multiselect('Documents to use for answers', list(labels), key='selected_document_ids',
                              format_func=labels.get,
                              placeholder="Select documents to search",
                              help='All uploaded documents are selected by default. Remove documents here only when you want to narrow the search.')
    selected_names = [names[did] for did in selected]
    if docs:
        page_total = sum(d['indexed_page_count'] for d in docs if d['document_id'] in selected)
        st.caption(f"{len(selected)} of {len(docs)} documents selected · {page_total} indexed pages")
    else:
        st.caption("Your indexed documents will appear here.")

empty_welcome = st.empty()
if not st.session_state.messages:
    with empty_welcome.container():
        ready = bool(docs)
        title = "Ready for your first question" if ready else "Start with your documents"
        st.markdown(f"""<section class="empty-workspace"><p class="eyebrow">Research, with evidence</p>
        <h2>{title}</h2><p>Ask a focused, standalone question. Each supported answer links back to the document and page it came from.</p>
        <div class="workspace-steps">
        <div class="workspace-step"><span class="step-number">01</span><div class="step-title">Add your documents</div><div class="step-description">Upload PDF or Word files to your local workspace.</div></div>
        <div class="workspace-step"><span class="step-number">02</span><div class="step-title">Choose your sources</div><div class="step-description">Search your library together, or narrow the selection.</div></div>
        <div class="workspace-step"><span class="step-number">03</span><div class="step-title">Ask and verify</div><div class="step-description">Review the answer and open its supporting page citations.</div></div>
        </div></section>""", unsafe_allow_html=True)


def show_result(result, key, document_names=None):
    from backend.presentation import clean_text, clean_answer
    if document_names is None:
        st.caption('Earlier answer: its document selection was not recorded. Changing the selection does not update old answers.')
    else:
        st.caption('Documents searched for this answer: ' + ', '.join(document_names))
    st.text(clean_answer(result["answer"]))
    for index, citation in enumerate(result.get("citations", [])):
        is_word = citation["filename"].lower().endswith((".doc", ".docx"))
        page_label = "converted PDF page" if is_word else "physical page"
        with st.expander(f"[{citation['source_id']}] {citation['filename']} · {page_label} {citation['page_number']}"):
            st.text(clean_text(citation["quote"]))
            st.caption("Supporting quotation")
            st.link_button("Open cited PDF" if is_word else "Open original PDF", BASE + citation["file_url"])
            if st.button("Show extracted page text", key=f"page-{key}-{index}"):
                page = request("GET", citation["page_text_url"])
                if page is not None:
                    st.text(page["text"] or "No extractable text on this page.")
    if result.get("timings"):
        st.caption(f"Completed in {result['timings'].get('total_seconds', 0):.1f}s")


def render_message(message, i):
    with st.chat_message(message["role"], avatar=":material/person:" if message["role"] == "user" else ":material/description:"):
        if message["role"] == "user":
            st.text(message["text"])
        else:
            recorded = message.get('document_ids')
            cited = {c['document_id'] for c in message['result'].get('citations', [])}
            if recorded is not None and not cited.issubset(set(recorded)):
                st.warning('An earlier response cited a document outside its recorded selection and has been hidden. Ask the question again with the documents you want selected.')
            else:
                show_result(message["result"], i, message.get('document_names'))


current_scope = set(selected)
earlier = []
for i, message in enumerate(st.session_state.messages):
    if message.get('document_ids') is not None and set(message['document_ids']) == current_scope:
        render_message(message, i)
    else:
        earlier.append((i, message))
if earlier:
    with st.expander('Earlier questions with other or unrecorded document selections'):
        for i, message in earlier:
            render_message(message, i)

st.caption("Research prototype · Not validated for clinical decisions · Chat history is display-only")
question = st.chat_input("Ask a standalone question about the selected documents", disabled=not selected, max_chars=2000)
if question:
    empty_welcome.empty()
    scope = {'document_ids': list(selected), 'document_names': list(selected_names)}
    st.session_state.messages.append({"role": "user", "text": question, **scope})
    with st.chat_message("user", avatar=":material/person:"):
        st.text(question)
    with st.chat_message("assistant", avatar=":material/description:"):
        with st.spinner("Finding evidence and checking citations…"):
            result = request("POST", f"/sessions/{sid}/chat", json={"question": question, "document_ids": selected})
        if result is not None:
            confirmed = set(result.get('searched_document_ids', []))
            cited = {c['document_id'] for c in result.get('citations', [])}
            if confirmed != set(selected) or not cited.issubset(confirmed):
                st.error('The response did not match the selected documents and was not displayed. Please retry after checking the API connection.')
            else:
                st.session_state.messages.append({"role": "assistant", "result": result, **scope})
                show_result(result, len(st.session_state.messages) - 1, selected_names)
