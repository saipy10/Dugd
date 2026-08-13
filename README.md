# Dugd GPT

An OpenAI-compatible REST API built with **FastAPI** that uses **Playwright** to communicate with the ChatGPT web interface through your existing Chrome profile.

This project allows applications such as VS Code, Continue, Cline, Roo Code, Cursor, and other OpenAI-compatible clients to use ChatGPT through a local API endpoint without using the OpenAI API.

---

# Features

- OpenAI-compatible `/v1/chat/completions` endpoint
- Streaming (`stream=true`) support via Server-Sent Events (SSE)
- `/v1/models` endpoint
- `/health` endpoint
- Interactive API documentation (Swagger UI at `/docs` & ReDoc at `/redoc`)
- Pydantic schema validation & custom error handling
- Uses your existing Chrome login
- Headless Playwright automation
- FastAPI server with Uvicorn ASGI server
- Uses `uv` for dependency management
- No browser extensions required

---

# Project Structure

```
.
├── main.py
├── chat_service.py
├── .env
├── pyproject.toml
├── uv.lock
├── README.md
```

---

# Requirements

- Python 3.11+
- Google Chrome
- Windows
- An active ChatGPT account already logged into Chrome
- uv

Install uv if you don't already have it:

### Windows

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

or

```bash
pip install uv
```

---

# Installation

Clone the repository.

```bash
git clone https://github.com/saipy10/Dugd-GPT

cd Dugd-GPT
```

Install dependencies.

```bash
uv sync
```

Install Playwright browser support.

```bash
uv run playwright install
```

---

# Configuration

Create a `.env` file.

Example:

```env
WINDOWS_USERNAME=YourWindowsUsername
PROFILE_NAME=Default

MODEL_ID=dugd-gpt-v1

PORT=5000
```

## Environment Variables

### WINDOWS_USERNAME

Your Windows username.

Example

```env
WINDOWS_USERNAME=John
```

The project will read your Chrome profile from

```
C:\Users\John\AppData\Local\Google\Chrome\User Data
```

---

### PROFILE_NAME

Chrome profile name.

Examples

```env
PROFILE_NAME=Default
```

or

```env
PROFILE_NAME=Profile 1
```

---

### MODEL_ID

Model name returned by `/v1/models`.

Example

```env
MODEL_ID=dugd-gpt-v1
```

---

### PORT

FastAPI server port.

Default

```
5000
```

---

# Chrome Setup

Before running the server:

1. Open Google Chrome.
2. Log into your ChatGPT account.
3. Verify you can access

```
https://chatgpt.com
```

4. Close Chrome.

The application clones your Chrome profile into a separate Playwright profile so your original browser profile remains untouched.

---

# Running

Start the server using `uv`:

```bash
uv run python main.py
```

or directly using `uvicorn`:

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 5000
```

Server starts on

```
http://localhost:5000
```

You can access interactive API docs at:
- Swagger UI: `http://localhost:5000/docs`
- ReDoc: `http://localhost:5000/redoc`

---

# API Endpoints

## Health

```
GET /health
```

Example

```bash
curl http://localhost:5000/health
```

Response

```json
{
  "status": "healthy"
}
```

---

## Models

```
GET /v1/models
```

Example

```bash
curl http://localhost:5000/v1/models
```

Response

```json
{
  "object": "list",
  "data": [
    {
      "id": "dugd-gpt-v1",
      "object": "model",
      "owned_by": "local"
    }
  ]
}
```

---

## Chat Completion

```
POST /v1/chat/completions
```

Example

```json
{
  "model": "dugd-gpt-v1",
  "messages": [
    {
      "role": "user",
      "content": "Explain transformers in simple terms."
    }
  ]
}
```

Example curl

```bash
curl http://localhost:5000/v1/chat/completions ^
-H "Content-Type: application/json" ^
-d "{\"model\":\"dugd-gpt-v1\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}"
```

Response

```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "Hello!"
      }
    }
  ]
}
```

---

# Streaming

Streaming is supported.

Example request

```json
{
  "model": "dugd-gpt-v1",
  "stream": true,
  "messages": [
    {
      "role": "user",
      "content": "Write a poem."
    }
  ]
}
```

The endpoint returns Server-Sent Events (SSE) compatible with the OpenAI Chat Completions API.

---

# Using with VS Code / Continue / Roo Code

Configure a custom OpenAI-compatible endpoint.

Base URL

```
http://localhost:5000/v1
```

Model

```
dugd-gpt-v1
```

API Key

```
Anything
```

The server does not validate API keys, but many clients require one to be present.

---

# How It Works

1. Clones your Chrome profile.
2. Launches Playwright using the cloned profile.
3. Opens ChatGPT.
4. Sends the prompt.
5. Waits for the response.
6. Returns an OpenAI-compatible response.

---

# Notes

- Requires an active ChatGPT login.
- Uses the ChatGPT web interface rather than the official OpenAI API.
- Only text conversations are currently supported.
- The first request may take longer while the browser profile is prepared.
- The cloned browser profile is reused on subsequent runs.

---

# Troubleshooting

## Chrome profile not found

Verify:

```env
WINDOWS_USERNAME
```

and

```env
PROFILE_NAME
```

are correct.

---

## Playwright cannot launch Chrome

Install Playwright browsers again.

```bash
uv run playwright install
```

---

## ChatGPT asks you to log in

Delete the cloned profile directory:

```
C:\Users\<username>\playwright_chrome_profile
```

Restart the application so the profile is cloned again.

---

## Request times out

Possible reasons:

- Slow internet
- ChatGPT is generating a long response
- ChatGPT website is temporarily unavailable

---

# Limitations

- Windows only
- Depends on the ChatGPT website structure
- UI changes on ChatGPT may require selector updates
- No image or vision support
- No tool calling
- No function calling
- One request launches a browser session
- Intended for personal/local use

---

# License

This project is intended for educational and personal use.
```
