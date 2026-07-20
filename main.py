import os
import json
import time
import traceback

from dotenv import load_dotenv
from flask import Flask, jsonify, request, Response, stream_with_context

from chat_service import ask_chatgpt

load_dotenv()

app = Flask(__name__)

MODEL_ID = os.getenv("MODEL_ID", "chatgpt-browser")


def openai_error(message, status, type="invalid_request_error"):
    return (
        jsonify(
            {
                "error": {
                    "message": message,
                    "type": type,
                    "param": None,
                    "code": None,
                }
            }
        ),
        status,
    )


@app.get("/health")
def health():
    return jsonify({"status": "healthy"})


@app.get("/v1/models")
def models():
    return jsonify(
        {
            "object": "list",
            "data": [
                {
                    "id": MODEL_ID,
                    "object": "model",
                    "owned_by": "local",
                }
            ],
        }
    )


def build_prompt(messages):
    prompt_parts = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, list):
            text = ""
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text += part.get("text", "")
            content = text

        if content:
            prompt_parts.append(f"{role}: {content}")

    return "\n".join(prompt_parts)


def stream_response(answer, model, completion_id, created, stream_options=None):
    """
    Sends OpenAI-compatible streaming events.
    """

    include_usage = (
        isinstance(stream_options, dict)
        and stream_options.get("include_usage") is True
    )

    words = answer.split(" ")

    for word in words:
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": word + " "
                    },
                    "finish_reason": None,
                }
            ],
        }

        yield f"data: {json.dumps(chunk)}\n\n"

    final = {
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
        final["usage"] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    yield f"data: {json.dumps(final)}\n\n"

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


@app.post("/v1/chat/completions")
def chat_completions():

    try:
        data = request.get_json(silent=True)

        if not data or not isinstance(data, dict):
            return openai_error("Missing JSON body", 400)

        messages = data.get("messages")

        if not messages or not isinstance(messages, list):
            return openai_error("messages field is required", 400)

        stream = data.get("stream", False)
        model = data.get("model") or MODEL_ID
        stream_options = data.get("stream_options")

        prompt = build_prompt(messages)

        answer = ask_chatgpt(prompt)

        completion_id = f"chatcmpl-{int(time.time())}"
        created = int(time.time())

        if stream:
            return Response(
                stream_with_context(
                    stream_response(
                        answer, model, completion_id, created, stream_options
                    )
                ),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        return jsonify(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": answer,
                            "refusal": None,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "system_fingerprint": "fp_local",
            }
        )

    except Exception as e:
        traceback.print_exc()
        return openai_error(str(e), 500, "server_error")


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
        threaded=True,
    )