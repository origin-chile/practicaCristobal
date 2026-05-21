import os
import json
import uuid
import httpx
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
USAGE_FILE = "usage.json"
PLAN_LIMITS = {"prueba": 30, "semanal": 30, "mensual": 30, "free": 30}

# ─── USAGE ───────────────────────────────────────────────
def load_usage():
    if os.path.exists(USAGE_FILE):
        with open(USAGE_FILE) as f:
            return json.load(f)
    return {}

def save_usage(u):
    with open(USAGE_FILE, "w") as f:
        json.dump(u, f)

def get_today():
    return datetime.now().strftime("%Y-%m-%d")

def check_and_increment(uid: str, plan: str = "free"):
    limit = PLAN_LIMITS.get(plan, 30)
    key = f"{uid}_{get_today()}"
    usage = load_usage()
    used = usage.get(key, 0)
    if used >= limit:
        return False, 0
    usage[key] = used + 1
    save_usage(usage)
    return True, limit - (used + 1)

# ─── CHAT ────────────────────────────────────────────────
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[Message]
    system: Optional[str] = None
    max_tokens: Optional[int] = 1800
    uid: Optional[str] = "free"
    plan: Optional[str] = "free"

@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="API key no configurada")

    uid = req.uid or "free"
    allowed, remaining = check_and_increment(uid, req.plan or "free")
    if not allowed:
        raise HTTPException(status_code=429, detail="LIMIT_REACHED")

    payload = {
        "model": "claude-sonnet-4-5",
        "max_tokens": req.max_tokens,
        "messages": [m.dict() for m in req.messages],
    }
    if req.system:
        payload["system"] = req.system

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(ANTHROPIC_URL, json=payload, headers=headers)

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    result = resp.json()
    result["remaining_msgs"] = remaining
    return result

# ─── UPLOAD ──────────────────────────────────────────────
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    content = await file.read()
    text = ""
    fname = file.filename.lower()
    if fname.endswith(".pdf"):
        try:
            import pypdf, io
            reader = pypdf.PdfReader(io.BytesIO(content))
            for page in reader.pages:
                text += page.extract_text() + "\n"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error PDF: {str(e)}")
    elif fname.endswith(".txt") or fname.endswith(".md"):
        try:
            text = content.decode("utf-8")
        except:
            text = content.decode("latin-1")
    else:
        raise HTTPException(status_code=400, detail="Solo PDF o TXT")
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No se pudo extraer texto")
    if len(text) > 8000:
        text = text[:8000] + "\n[Recortado]"
    return {"text": text, "chars": len(text), "filename": file.filename}

# ─── PAGES ───────────────────────────────────────────────
@app.get("/tutor")
def tutor():
    return FileResponse("tutor.html")

@app.get("/")
def root():
    return FileResponse("tutor.html")
