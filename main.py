import os
import json
import time
import atexit
import traceback
from typing import Any, List, Optional, Union

from logger import logger

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from chat_service import ask_chatgpt, worker

load_dotenv()

MODEL_ID = os.getenv("MODEL_ID", "dugd-gpt-v1")


# Graceful shutdown via atexit (no async needed)
def shutdown_worker():
    logger.info("Shutting down browser worker thread...")
    worker.task_queue.put((None, None))
    worker.join(timeout=5.0)


atexit.register(shutdown_worker)


app = FastAPI(
    title="Dugd GPT API",
    description="OpenAI-compatible REST API powered by Playwright and ChatGPT",
    version="1.0.0",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic Schemas for OpenAI Compatibility
class ChatMessage(BaseModel):
    role: str = Field(..., json_schema_extra={"example": "user"})
    content: Union[str, List[Any]] = Field(..., json_schema_extra={"example": "Hello!"})


class StreamOptions(BaseModel):
    include_usage: Optional[bool] = False


class ChatCompletionRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
    stream: Optional[bool] = False
    stream_options: Optional[StreamOptions] = None
    temperature: Optional[float] = None


class ModelObject(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = "local"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: List[ModelObject]


class ChoiceMessage(BaseModel):
    role: str = "assistant"
    content: str
    refusal: Optional[str] = None


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str = "stop"


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: UsageInfo
    system_fingerprint: str = "fp_local"


class HealthResponse(BaseModel):
    status: str = "healthy"


# Custom OpenAI Error Responder
def openai_error_response(message: str, status_code: int = 400, error_type: str = "invalid_request_error"):
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": None,
                "code": None,
            }
        },
    )


@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError):
    error_details = "; ".join([f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()])
    return openai_error_response(f"Invalid request parameters: {error_details}", status_code=400)


@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    return openai_error_response(str(exc.detail), status_code=exc.status_code)


@app.exception_handler(Exception)
def global_exception_handler(request: Request, exc: Exception):
    logger.exception("An unhandled exception occurred")
    return openai_error_response(str(exc), status_code=500, error_type="server_error")


def build_prompt(messages: List[ChatMessage]) -> str:
    prompt_parts = []
    for msg in messages:
        role = msg.role
        content = msg.content

        if isinstance(content, list):
            text = ""
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text += part.get("text", "")
            content = text

        if content:
            prompt_parts.append(f"{role}: {content}")

    return "\n".join(prompt_parts)


def sse_stream_generator(generator, model: str, completion_id: str, created: int, stream_options: Optional[StreamOptions] = None):
    """
    Synchronous generator that yields OpenAI-compatible SSE chunks.
    FastAPI's StreamingResponse handles sync generators by running them in a threadpool.
    """
    include_usage = stream_options is not None and stream_options.include_usage

    try:
        for chunk_text in generator:
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": chunk_text},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk)}\n\n"

        final_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        if include_usage:
            final_chunk["usage"] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        yield f"data: {json.dumps(final_chunk)}\n\n"

        if include_usage:
            usage_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
            yield f"data: {json.dumps(usage_chunk)}\n\n"

        yield "data: [DONE]\n\n"
    except Exception as e:
        logger.exception("An error occurred during SSE streaming")
        err_event = {
            "error": {
                "message": str(e),
                "type": "server_error",
                "param": None,
                "code": None,
            }
        }
        yield f"data: {json.dumps(err_event)}\n\n"
        yield "data: [DONE]\n\n"


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="healthy")


@app.get("/v1/models", response_model=ModelListResponse)
def list_models():
    return ModelListResponse(
        data=[
            ModelObject(
                id=MODEL_ID,
                object="model",
                owned_by="local",
            )
        ]
    )


@app.post(
    "/v1/chat/completions",
    response_model=Union[ChatCompletionResponse, None],
    responses={
        200: {
            "description": "Chat completion response or streaming event stream",
            "content": {"text/event-stream": {}, "application/json": {}},
        }
    },
)
def chat_completions(body: ChatCompletionRequest):
    if not body.messages:
        return openai_error_response("messages field cannot be empty", status_code=400)

    model = body.model or MODEL_ID
    prompt = build_prompt(body.messages)

    chunks_generator = ask_chatgpt(prompt)
    completion_id = f"chatcmpl-{int(time.time())}"
    created = int(time.time())

    if body.stream:
        return StreamingResponse(
            sse_stream_generator(
                chunks_generator, model, completion_id, created, body.stream_options
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Consume the sync generator for non-streaming response
    answer = "".join(chunks_generator)

    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=model,
        choices=[
            Choice(
                index=0,
                message=ChoiceMessage(
                    role="assistant",
                    content=answer,
                ),
                finish_reason="stop",
            )
        ],
        usage=UsageInfo(),
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "5000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)