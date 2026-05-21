"""
Dashboard de monitoring JuriChat.
- Logs en direct (WebSocket)
- Stats Qdrant (collections, points)
- Crons programmes
- Lancement de pipelines

Mode local (VPS) : utilise subprocess directement.
Mode distant (Mac) : utilise asyncssh.
Detecte automatiquement via DASHBOARD_LOCAL=1 ou la presence du dossier /home/ubuntu/jurichat.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

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
LOCAL_MODE = (
    os.getenv("DASHBOARD_LOCAL", "").strip() == "1"
    or Path("/home/ubuntu/jurichat").exists()
)

VPS_HOST = os.getenv("VPS_HOST", "141.227.133.247")
VPS_USER = os.getenv("VPS_USER", "ubuntu")
VPS_KEY_PATH = os.getenv("VPS_KEY_PATH", str(Path.home() / ".ssh" / "id_ed25519_ovh"))
LOGS_DIR = "/home/ubuntu/jurichat/logs"
JURICHAT_DIR = "/home/ubuntu/jurichat"

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

COLLECTIONS = [
    "articles_blog",
    "decisions_cour_cassation",
    "potential_questions",
    "unique_questions_decisions_cd",
    "unique_questions_decisions_ca",
]

logger.info(f"Dashboard mode: {'LOCAL (VPS)' if LOCAL_MODE else 'DISTANT (SSH)'}")


# --- Helpers : execution locale ou distante ---
async def run_command(cmd: str) -> str:
    """Execute une commande en local ou via SSH selon le mode."""
    if LOCAL_MODE:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        stdout, _ = await proc.communicate()
        return stdout.decode()
    else:
        import asyncssh
        async with asyncssh.connect(
            VPS_HOST, username=VPS_USER,
            client_keys=[VPS_KEY_PATH], known_hosts=None,
        ) as conn:
            result = await conn.run(cmd, check=False)
            return result.stdout


async def stream_command(cmd: str, websocket: WebSocket):
    """Stream la sortie d'une commande ligne par ligne vers un WebSocket."""
    if LOCAL_MODE:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        try:
            async for line in proc.stdout:
                await websocket.send_json({"line": line.decode().rstrip("\n")})
        except WebSocketDisconnect:
            pass
        finally:
            proc.kill()
    else:
        import asyncssh
        async with asyncssh.connect(
            VPS_HOST, username=VPS_USER,
            client_keys=[VPS_KEY_PATH], known_hosts=None,
        ) as conn:
            process = await conn.create_process(cmd)
            try:
                async for line in process.stdout:
                    await websocket.send_json({"line": line.rstrip("\n")})
            except (WebSocketDisconnect, asyncssh.Error):
                pass
            finally:
                process.kill()


def get_qdrant_client():
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=15)


# --- Qdrant Stats ---
@app.get("/api/qdrant/stats")
async def qdrant_stats():
    client = get_qdrant_client()
    results = []

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
    try:
        output = await run_command("crontab -l")
        lines = output.strip().split("\n")

        crons = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
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

        return {"crons": crons, "raw": output.strip()}

    except Exception as e:
        logger.error(f"Erreur crons: {e}")
        return {"error": str(e), "crons": []}


# --- Logs disponibles ---
@app.get("/api/logs/files")
async def list_log_files():
    try:
        output = await run_command(f"ls -lt {LOGS_DIR}/*.log 2>/dev/null | head -20")
        files = []
        for line in output.strip().split("\n"):
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


# --- WebSocket Logs ---
@app.websocket("/ws/logs/{filename}")
async def stream_logs(websocket: WebSocket, filename: str):
    await websocket.accept()

    if "/" in filename or ".." in filename:
        await websocket.send_json({"error": "Nom de fichier invalide"})
        await websocket.close()
        return

    try:
        await stream_command(f"tail -n 100 -f {LOGS_DIR}/{filename}", websocket)
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/logs")
async def stream_all_logs(websocket: WebSocket):
    await websocket.accept()

    try:
        await stream_command(f"tail -n 50 -f {LOGS_DIR}/*.log 2>/dev/null", websocket)
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
            await websocket.close()
        except Exception:
            pass


# --- Lancement de pipelines ---
PIPELINES = {
    "update_urls": (
        f"cd {JURICHAT_DIR} && source venv/bin/activate && "
        "python update_urls_from_sitemaps.py && python update_urls_from_website.py"
    ),
    "ingest_blogs": (
        f"cd {JURICHAT_DIR} && source venv/bin/activate && "
        "python scrape_and_update_qdrant_collection.py"
    ),
    "ingest_cc": (
        f"cd {JURICHAT_DIR} && source venv/bin/activate && "
        "python -m pipeline_ingestion_cour_cassation.main --year {year}"
    ),
}

running_pipelines: dict = {}


@app.post("/api/pipelines/{pipeline_id}/start")
async def start_pipeline(pipeline_id: str, year: int = 2025):
    if pipeline_id not in PIPELINES:
        return {"error": f"Pipeline inconnue: {pipeline_id}"}

    if pipeline_id in running_pipelines and running_pipelines[pipeline_id]["status"] == "running":
        return {"error": "Cette pipeline est deja en cours d'execution"}

    cmd_template = PIPELINES[pipeline_id]
    cmd = cmd_template.format(year=year) if "{year}" in cmd_template else cmd_template

    session_name = f"pipeline_{pipeline_id}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"manual_{pipeline_id}_{timestamp}.log"
    log_file = f"{LOGS_DIR}/{log_filename}"

    tmux_cmd = (
        f"tmux kill-session -t {session_name} 2>/dev/null; "
        f"tmux new-session -d -s {session_name} "
        f"'{cmd} 2>&1 | tee {log_file}; "
        f"echo PIPELINE_DONE >> {log_file}'"
    )

    try:
        await run_command(tmux_cmd)

        running_pipelines[pipeline_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "log_file": log_filename,
            "session": session_name,
        }

        return {
            "status": "started",
            "pipeline": pipeline_id,
            "log_file": log_filename,
            "session": session_name,
        }

    except Exception as e:
        logger.error(f"Erreur lancement pipeline {pipeline_id}: {e}")
        return {"error": str(e)}


@app.get("/api/pipelines/status")
async def pipelines_status():
    try:
        output = await run_command("tmux list-sessions -F '#{session_name}' 2>/dev/null")
        active_sessions = set(output.strip().split("\n")) if output.strip() else set()

        for pid, info in running_pipelines.items():
            if info["status"] == "running" and info["session"] not in active_sessions:
                info["status"] = "finished"

    except Exception as e:
        logger.error(f"Erreur verification statut: {e}")

    return {"pipelines": running_pipelines}


@app.post("/api/pipelines/{pipeline_id}/stop")
async def stop_pipeline(pipeline_id: str):
    session_name = f"pipeline_{pipeline_id}"
    try:
        await run_command(f"tmux kill-session -t {session_name} 2>/dev/null")

        if pipeline_id in running_pipelines:
            running_pipelines[pipeline_id]["status"] = "stopped"

        return {"status": "stopped", "pipeline": pipeline_id}

    except Exception as e:
        return {"error": str(e)}


# --- Servir le frontend ---
DASHBOARD_DIR = Path(__file__).parent

@app.get("/")
async def serve_frontend():
    return FileResponse(DASHBOARD_DIR / "frontend" / "index.html")


app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR / "frontend")), name="static")


if __name__ == "__main__":
    import uvicorn
    host = "0.0.0.0" if LOCAL_MODE else "127.0.0.1"
    uvicorn.run("dashboard.backend:app", host=host, port=8080, reload=True)
