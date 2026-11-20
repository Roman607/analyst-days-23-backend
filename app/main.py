import os
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.models import (
    ErrorCode,
    Health,
    InvalidRequestError,
    Preview,
    PreviewRequest,
    Program,
    ProgramUnavailableError,
    StaleProgramError,
)
from app.program import DEFAULT_DB, ProgramStore, SnapshotUnavailable
from app.trajectory import ERRORS, ApiError, preview

UNAVAILABLE_DOC = {
    "model": ProgramUnavailableError,
    "description": "Нет доступного проверенного снимка программы",
}
PREVIEW_PATH = "/api/trajectory/preview"
PREVIEW_EXAMPLES = {
    "initial": {"value": {"revision": "ad23-demo-1", "topic_ids": [], "actions": []}},
    "byTopic": {"value": {"revision": "ad23-demo-1", "topic_ids": ["ai"], "actions": []}},
    "manual": {"value": {
        "revision": "ad23-demo-1", "topic_ids": ["ai"],
        "actions": [{"op": "choose", "entry_id": "talk-151071"}],
    }},
}


def error_response(code: ErrorCode) -> JSONResponse:
    status, message = ERRORS[code]
    return JSONResponse({"code": code, "message": message}, status_code=status)


def create_app(database: Path) -> FastAPI:
    store = ProgramStore(database)
    service = FastAPI(
        title="Analyst Days 23 — программа и очная траектория",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
    )

    @service.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return error_response("invalid_request")

    @service.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> Response:
        if error.status_code == 400 and request.method == "POST" and request.url.path == PREVIEW_PATH:
            return error_response("invalid_request")
        return await http_exception_handler(request, error)

    @service.exception_handler(ApiError)
    async def expected_error(_request: Request, error: ApiError) -> JSONResponse:
        return error_response(error.code)

    @service.exception_handler(SnapshotUnavailable)
    async def unavailable(_request: Request, _error: SnapshotUnavailable) -> JSONResponse:
        return error_response("program_unavailable")

    @service.get(
        "/api/health", operation_id="checkHealth",
        summary="Проверить готовность API и доступность опубликованной программы",
        response_description="Программу можно прочитать", responses={503: UNAVAILABLE_DOC},
    )
    def health() -> Health:
        store.read()
        return Health(status="ok")

    @service.get(
        "/api/program", operation_id="getProgram",
        summary="Получить одну согласованную версию программы на оба дня",
        response_description="Полная сетка, включая перерывы и хакатон",
        responses={503: UNAVAILABLE_DOC},
    )
    def program() -> Program:
        return store.read()

    @service.post(
        PREVIEW_PATH, operation_id="previewTrajectory",
        summary="Рассчитать выделение карточек и состав изображения",
        response_description="Результат для переданных тем и действий",
        responses={
            200: {"headers": {"Cache-Control": {
                "schema": {"type": "string", "const": "no-store"},
                "description": "Ответ содержит текущий выбор.",
            }}},
            409: {"model": StaleProgramError, "description": "Версия программы в запросе устарела"},
            422: {"model": InvalidRequestError, "description": "Ошибка JSON, структуры запроса, идентификатора или действия"},
            503: UNAVAILABLE_DOC,
        },
    )
    def preview_trajectory(
        request: Annotated[PreviewRequest, Body(openapi_examples=PREVIEW_EXAMPLES)],
        response: Response,
    ) -> Preview:
        result = preview(store.read(), request)
        response.headers["Cache-Control"] = "no-store"
        return result

    return service


app = create_app(Path(os.environ.get("PROGRAM_DB", DEFAULT_DB)))
