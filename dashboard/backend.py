"""
Dashboard de monitoring JuriChat.
- Logs SSH en direct (WebSocket)
- Stats Qdrant (collections, points)
- Crons programmés
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import asyncssh
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from qdrant_client import QdrantClient

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="JuriChat Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Config ---
VPS_HOST = os.getenv("VPS_HOST", "141.227.133.247")
VPS_USER = os.getenv("VPS_USER", "ubuntu")
VPS_KEY_PATH = os.getenv("VPS_KEY_PATH", str(Path.home() / ".ssh" / "id_ed25519_ovh"))
LOGS_DIR = "/home/ubuntu/jurichat/logs"

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

COLLECTIONS = [
    "articles_blog",
    "decisions_cour_cassation",
    "potential_questions",
    "unique_questions_decisions_cd",
    "unique_questions_decisions_ca",
]


def get_qdrant_client():
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=15)


# --- Qdrant Stats ---
@app.get("/api/qdrant/stats")
async def qdrant_stats():
    """Retourne les stats de chaque collection Qdrant."""
    client = get_qdrant_client()
    results = []

    # Lister toutes les collections existantes
    try:
        existing = {c.name for c in client.get_collections().collections}
    except Exception as e:
        return {"error": str(e), "collections": []}

    for name in COLLECTIONS:
        if name not in existing:
            results.append({"name": name, "status": "not_found", "points_count": 0})
            continue
        try:
            info = client.get_collection(name)
            results.append({
                "name": name,
                "status": str(info.status),
                "points_count": info.points_count,
                "segments_count": info.segments_count,
            })
        except Exception as e:
            results.append({"name": name, "status": "error", "error": str(e)})

    return {"collections": results}


# --- Crons ---
@app.get("/api/crons")
async def get_crons():
    """Recupere la crontab du VPS."""
    try:
        async with asyncssh.connect(
            VPS_HOST,
            username=VPS_USER,
            client_keys=[VPS_KEY_PATH],
            known_hosts=None,
        ) as conn:
            result = await conn.run("crontab -l", check=True)
            lines = result.stdout.strip().split("\n")

            crons = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    if line.startswith("#") and not line.startswith("# "):
                        continue
                    if line.startswith("# "):
                        crons.append({"type": "comment", "text": line[2:]})
                    continue

                parts = line.split(None, 5)
                if len(parts) >= 6:
                    crons.append({
                        "type": "job",
                        "schedule": " ".join(parts[:5]),
                        "command": parts[5],
                        "raw": line,
                    })

            return {"crons": crons, "raw": result.stdout.strip()}

    except Exception as e:
        logger.error(f"Erreur SSH crons: {e}")
        return {"error": str(e), "crons": []}


# --- Logs disponibles ---
@app.get("/api/logs/files")
async def list_log_files():
    """Liste les fichiers de log disponibles sur le VPS."""
    try:
        async with asyncssh.connect(
            VPS_HOST,
            username=VPS_USER,
            client_keys=[VPS_KEY_PATH],
            known_hosts=None,
        ) as conn:
            result = await conn.run(
                f"ls -lt {LOGS_DIR}/*.log 2>/dev/null | head -20",
                check=False,
            )
            files = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 9:
                    filename = parts[-1].split("/")[-1]
                    size = parts[4]
                    date = " ".join(parts[5:8])
                    files.append({"name": filename, "size": size, "date": date})

            return {"files": files}

    except Exception as e:
        return {"error": str(e), "files": []}


# --- WebSocket Logs en direct ---
@app.websocket("/ws/logs/{filename}")
async def stream_logs(websocket: WebSocket, filename: str):
    """Stream les logs en direct via WebSocket (tail -f)."""
    await websocket.accept()

    # Securite: empecher path traversal
    if "/" in filename or ".." in filename:
        await websocket.send_json({"error": "Nom de fichier invalide"})
        await websocket.close()
        return

    filepath = f"{LOGS_DIR}/{filename}"

    try:
        async with asyncssh.connect(
            VPS_HOST,
            username=VPS_USER,
            client_keys=[VPS_KEY_PATH],
            known_hosts=None,
        ) as conn:
            # Envoyer les 100 dernieres lignes puis suivre
            process = await conn.create_process(f"tail -n 100 -f {filepath}")

            try:
                async for line in process.stdout:
                    await websocket.send_json({"line": line.rstrip("\n")})
            except (WebSocketDisconnect, asyncssh.Error):
                pass
            finally:
                process.kill()

    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
            await websocket.close()
        except Exception:
            pass


# --- WebSocket Logs globaux (tous les logs recents) ---
@app.websocket("/ws/logs")
async def stream_all_logs(websocket: WebSocket):
    """Stream tous les logs recents en direct."""
    await websocket.accept()

    try:
        async with asyncssh.connect(
            VPS_HOST,
            username=VPS_USER,
            client_keys=[VPS_KEY_PATH],
            known_hosts=None,
        ) as conn:
            # Suivre tous les .log du repertoire
            process = await conn.create_process(
                f"tail -n 50 -f {LOGS_DIR}/*.log 2>/dev/null"
            )

            try:
                async for line in process.stdout:
                    await websocket.send_json({"line": line.rstrip("\n")})
            except (WebSocketDisconnect, asyncssh.Error):
                pass
            finally:
                process.kill()

    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
            await websocket.close()
        except Exception:
            pass


# --- Lancement de pipelines ---
PIPELINES = {
    "update_urls": (
        "cd /home/ubuntu/jurichat && source venv/bin/activate && "
        "python update_urls_from_sitemaps.py && python update_urls_from_website.py"
    ),
    "ingest_blogs": (
        "cd /home/ubuntu/jurichat && source venv/bin/activate && "
        "python scrape_and_update_qdrant_collection.py"
    ),
    "ingest_cc": (
        "cd /home/ubuntu/jurichat && source venv/bin/activate && "
        "python -m pipeline_ingestion_cour_cassation.main --year {year}"
    ),
}

# Suivi des pipelines en cours {pipeline_id: {"status": ..., "started_at": ...}}
running_pipelines: dict = {}


@app.post("/api/pipelines/{pipeline_id}/start")
async def start_pipeline(pipeline_id: str, year: int = 2025):
    """Lance une pipeline sur le VPS dans un tmux."""
    if pipeline_id not in PIPELINES:
        return {"error": f"Pipeline inconnue: {pipeline_id}"}

    if pipeline_id in running_pipelines and running_pipelines[pipeline_id]["status"] == "running":
        return {"error": "Cette pipeline est deja en cours d'execution"}

    cmd_template = PIPELINES[pipeline_id]
    cmd = cmd_template.format(year=year) if "{year}" in cmd_template else cmd_template

    session_name = f"pipeline_{pipeline_id}"
    log_file = f"{LOGS_DIR}/manual_{pipeline_id}_{asyncio.get_event_loop().time():.0f}.log"

    tmux_cmd = (
        f"tmux kill-session -t {session_name} 2>/dev/null; "
        f"tmux new-session -d -s {session_name} "
        f"'{cmd} 2>&1 | tee {log_file}; "
        f"echo PIPELINE_DONE >> {log_file}'"
    )

    try:
        async with asyncssh.connect(
            VPS_HOST,
            username=VPS_USER,
            client_keys=[VPS_KEY_PATH],
            known_hosts=None,
        ) as conn:
            await conn.run(tmux_cmd, check=False)

        from datetime import datetime
        running_pipelines[pipeline_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "log_file": log_file.split("/")[-1],
            "session": session_name,
        }

        return {
            "status": "started",
            "pipeline": pipeline_id,
            "log_file": log_file.split("/")[-1],
            "session": session_name,
        }

    except Exception as e:
        logger.error(f"Erreur lancement pipeline {pipeline_id}: {e}")
        return {"error": str(e)}


@app.get("/api/pipelines/status")
async def pipelines_status():
    """Verifie le statut des pipelines en cours."""
    try:
        async with asyncssh.connect(
            VPS_HOST,
            username=VPS_USER,
            client_keys=[VPS_KEY_PATH],
            known_hosts=None,
        ) as conn:
            result = await conn.run("tmux list-sessions -F '#{session_name}' 2>/dev/null", check=False)
            active_sessions = set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()

        for pid, info in running_pipelines.items():
            if info["status"] == "running" and info["session"] not in active_sessions:
                info["status"] = "finished"

    except Exception as e:
        logger.error(f"Erreur verification statut: {e}")

    return {"pipelines": running_pipelines}


@app.post("/api/pipelines/{pipeline_id}/stop")
async def stop_pipeline(pipeline_id: str):
    """Arrete une pipeline en cours."""
    session_name = f"pipeline_{pipeline_id}"
    try:
        async with asyncssh.connect(
            VPS_HOST,
            username=VPS_USER,
            client_keys=[VPS_KEY_PATH],
            known_hosts=None,
        ) as conn:
            await conn.run(f"tmux kill-session -t {session_name} 2>/dev/null", check=False)

        if pipeline_id in running_pipelines:
            running_pipelines[pipeline_id]["status"] = "stopped"

        return {"status": "stopped", "pipeline": pipeline_id}

    except Exception as e:
        return {"error": str(e)}


# --- Servir le frontend ---
@app.get("/")
async def serve_frontend():
    return FileResponse("dashboard/frontend/index.html")


app.mount("/static", StaticFiles(directory="dashboard/frontend"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard.backend:app", host="127.0.0.1", port=8080, reload=True)
