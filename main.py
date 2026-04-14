import sqlite3
from typing import Dict, Any
from logger_setup import logger
from vanna.servers.fastapi import VannaFastAPIServer
from vanna_setup import agent, DB_PATH
from seed_memory import count_seeded_memories, seed_agent_memory
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    logger.info("Triggering FastApi lifespan startup block")
    await seed_agent_memory(agent.agent_memory)
    logger.info("Seeded agent memory successfully")
    yield


server = VannaFastAPIServer(agent)
app = server.create_app()
app.router.lifespan_context = lifespan
new_routes = [route for route in app.routes if getattr(route, "path", None) != "/health"]
app.router.routes.clear()
app.router.routes.extend(new_routes)

@app.get("/health")
def health() -> Dict[str, Any]:
    logger.info("Health route hit.")
    try:
        with sqlite3.connect(DB_PATH) as connection:
            connection.execute("SELECT 1")
        database_status = "connected"
    except sqlite3.Error:
        logger.error("Database connection failed during health check", exc_info=True)
        database_status = "disconnected"

    memory_items = count_seeded_memories(agent.agent_memory)

    return {
        "status": "ok",
        "database": database_status,
        "agent_memory_items": memory_items
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
