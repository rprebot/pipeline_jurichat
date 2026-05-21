"""
Backend FastAPI pour JuriChat - RAG chatbot juridique.
"""

import asyncio
import json
import logging
from typing import List, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import WebAppConfig
from .rag import create_clients, embed_query, search_collections, build_context, stream_rag_response, get_sources_from_results

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Config & clients
config = WebAppConfig.from_env()
qdrant_client, embedding_client, llm_client = create_clients(config)

logger.info(f"Collections configurées: {config.collections}")
logger.info(f"Modèle LLM: {config.deepseek_model}")

app = FastAPI(title="JuriChat API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


@app.get("/api/health")
async def health():
    """Health check."""
    return {
        "status": "ok",
        "collections": config.collections,
        "model": config.deepseek_model,
    }


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Endpoint principal de chat RAG avec streaming SSE.
    """
    query = request.message.strip()
    if not query:
        return {"error": "Message vide"}

    history = [{"role": m.role, "content": m.content} for m in request.history]

    # D'abord, récupérer les sources pour les envoyer en premier
    query_vector = embed_query(query, embedding_client, config)
    results = search_collections(query_vector, qdrant_client, config)
    sources = get_sources_from_results(results)

    async def event_stream():
        # Envoyer les sources en premier
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

        # Streamer la réponse
        async for token in stream_rag_response(
            query, history, qdrant_client, embedding_client, llm_client, config
        ):
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

        # Signal de fin
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/collections")
async def list_collections():
    """Liste les collections disponibles avec leurs stats."""
    stats = []
    for name in config.collections:
        try:
            info = qdrant_client.get_collection(name)
            stats.append({
                "name": name,
                "points_count": info.points_count,
                "status": str(info.status),
            })
        except Exception as e:
            stats.append({
                "name": name,
                "error": str(e),
            })
    return {"collections": stats}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "webapp.backend.main:app",
        host=config.host,
        port=config.port,
        reload=True,
    )
