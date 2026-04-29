# ===========================================================
# SpeakSecure — Server Launcher
# Convenience script to start the API locally.
# Run with:    python run.py
# or:          uvicorn main:app --reload
# ===========================================================

import uvicorn
from config import HOST, PORT

if __name__ == "__main__":
    # Print useful links before handing over to uvicorn
    local_url = f"http://localhost:{PORT}"
    print("=" * 60)
    print(" SpeakSecure API")
    print("=" * 60)
    print(f"  Demo UI:       {local_url}")
    print(f"  API docs:      {local_url}/docs")
    print(f"  Health check:  {local_url}/api/v1/health")
    print("=" * 60)
    print(" Press CTRL+C to stop")
    print()

    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=True,           # Auto-restart on code changes (dev only)
        reload_dirs=["."],     # Watch the whole project, not just main.py
        log_level="info",
    )