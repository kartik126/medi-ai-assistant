from contextlib import asynccontextmanager
import logging
from pathlib import Path
from uuid import UUID
import psycopg
from psycopg_pool import PoolTimeout
from fastapi import FastAPI, File, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from backend.answering import chat
from backend.config import get_settings
from backend.db import Database
from backend.errors import AppError
from backend.model_client import OllamaModels
from backend.schemas import ChatRequest, ChatResponse, DocumentResponse, FileResult, SessionResponse
from backend.storage import Store
from backend.upload_limits import UploadLimitMiddleware
from backend.document_service import converter_path, MIME_TYPES

logger = logging.getLogger("medical_ai")


def create_app(settings=None, db=None, models=None):
    settings = settings or get_settings()
    db = db or Database(settings.database_url)
    models = models or OllamaModels(settings)
    store = Store(db, settings, models)

    @asynccontextmanager
    async def lifespan(app):
        db.open()
        try:
            try:
                await run_in_threadpool(store.cleanup)
            except (psycopg.Error, PoolTimeout, OSError):
                logger.warning("Startup cleanup unavailable; check database connectivity and migrations.")
            yield
        finally:
            models.close()
            db.close()

    api = FastAPI(title="Medical Document Assistant", lifespan=lifespan)
    api.state.store = store
    api.add_middleware(UploadLimitMiddleware, max_bytes=settings.max_total_mb * 1024**2 + 1024**2)

    @api.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})

    @api.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo question/document contents into errors or logs.
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "Invalid request fields, question length or resource ID."}})

    async def database_error(request, exc):
        return JSONResponse(status_code=503, content={"error": {"code": "database_unavailable", "message": "Database unavailable. Check Docker, credentials and migrations."}})

    api.add_exception_handler(psycopg.Error, database_error)
    api.add_exception_handler(PoolTimeout, database_error)

    @api.exception_handler(OSError)
    async def filesystem_error(request, exc):
        return JSONResponse(status_code=503, content={"error": {"code": "storage_unavailable", "message": "Local file storage unavailable. Check disk access and retry."}})

    @api.get("/health")
    def health():
        try:
            database = db.readiness()
        except (psycopg.Error, PoolTimeout):
            database = {"ready": False}
        try:
            model = models.readiness()
        except AppError:
            model = {"ready": False}
        return {"api": "alive", "ready": bool(database["ready"] and model["ready"]),
                "database": database, "models": model,
                "config": {"chat_model": settings.chat_model, "embedding_model": settings.embedding_model,
                           "max_files": settings.max_files, "max_file_mb": settings.max_file_mb,
                           "max_total_mb": settings.max_total_mb, "max_total_pages": settings.max_total_pages,
                           "upload_extensions": ["pdf", "doc", "docx"], "word_converter_ready": bool(converter_path(settings))}}

    @api.post("/sessions", response_model=SessionResponse, status_code=201)
    def create_session():
        return {"session_id": store.create()}

    @api.get("/sessions/{sid}/documents", response_model=list[DocumentResponse])
    def documents(sid: UUID):
        return store.documents(sid)

    @api.post("/sessions/{sid}/documents", response_model=list[FileResult])
    async def upload(sid: UUID, files: list[UploadFile] = File(...)):
        # Multipart parser spools files; application reads only bounded byte counts.
        try:
            await run_in_threadpool(store.documents, sid)
            if len(files) > settings.max_files:
                raise AppError("file_limit", f"Upload at most {settings.max_files} documents per request.", 413)
            results, request_bytes = [], 0
            for upload_file in files:
                name = (upload_file.filename or "upload.pdf").replace("\\", "/").split("/")[-1][:255]
                try:
                    content = bytearray()
                    while block := await upload_file.read(64 * 1024):
                        content.extend(block)
                        request_bytes += len(block)
                        if len(content) > settings.max_file_mb * 1024**2:
                            raise AppError("file_size_limit", "File exceeds the configured size limit.", 413)
                        if request_bytes > settings.max_total_mb * 1024**2:
                            raise AppError("request_size_limit", "Upload request exceeds the aggregate size limit.", 413)
                    document = await run_in_threadpool(store.ingest, sid, name, bytes(content))
                    results.append({"filename": name, "status": "ready", "document": document})
                except AppError as exc:
                    results.append({"filename": name, "status": "error", "error_code": exc.code, "message": exc.message})
            return results
        finally:
            for upload_file in files:
                await upload_file.close()

    @api.post("/sessions/{sid}/chat", response_model=ChatResponse)
    def ask(sid: UUID, request: ChatRequest):
        result = chat(store, sid, request)
        return {**result, 'searched_document_ids': list(dict.fromkeys(request.document_ids))}

    @api.get("/sessions/{sid}/documents/{did}/file")
    def original(sid: UUID, did: UUID):
        # Read while locked so clear-session cannot remove a file during serving.
        with db.session_lock(sid):
            store.document(sid, did)
            try:
                content = (store.directory(sid) / f"{did}.pdf").read_bytes()
            except FileNotFoundError as exc:
                raise AppError("file_unavailable", "Cited PDF unavailable. Re-ingest this document.", 404) from exc
        return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{did}.pdf"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @api.get("/sessions/{sid}/documents/{did}/original")
    def source_original(sid: UUID, did: UUID):
        with db.session_lock(sid):
            document = store.document(sid, did)
            extension = Path(document['filename']).suffix.lower()
            if extension not in MIME_TYPES:
                raise AppError('unsupported_file', 'Original file type is unsupported.', 404)
            try:
                content = (store.directory(sid) / f'{did}{extension}').read_bytes()
            except FileNotFoundError as exc:
                raise AppError('file_unavailable', 'Original document unavailable. Re-ingest this document.', 404) from exc
        return Response(content, media_type=MIME_TYPES[extension], headers={
            'Content-Disposition': f'attachment; filename="{did}{extension}"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @api.get("/sessions/{sid}/documents/{did}/pages/{number}")
    def page(sid: UUID, did: UUID, number: int):
        return store.page(sid, did, number)

    @api.delete("/sessions/{sid}", status_code=204)
    def clear(sid: UUID):
        store.delete(sid)
        return Response(status_code=204)

    return api


app = create_app()
