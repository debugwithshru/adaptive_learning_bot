from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
import json
import os
import shutil
import threading
import time
import pandas as pd
import uuid

# Internal modules
from latex_utils import generate_paper_package

app = FastAPI(title="Test Paper Generator API")

# Google Sheets public CSV export link
SHEET_ID = "1N7SkRKDmHJO2uhHDCSFVGFOytHIIdcM6RGwrjxFMmFw"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"

# ---------------------------------------------------------------------------
# Download token registry
# Maps token (str) -> {"zip_path": str, "temp_dir": str, "created_at": float}
# Tokens auto-expire after EXPIRY_SECONDS so stale temp dirs are cleaned up
# even if /download is never called (e.g. n8n timeout or client drop).
# ---------------------------------------------------------------------------
TOKEN_REGISTRY: dict[str, dict] = {}
TOKEN_REGISTRY_LOCK = threading.Lock()
EXPIRY_SECONDS = 600  # 10 minutes


def _expire_old_tokens():
    """Remove tokens older than EXPIRY_SECONDS and delete their temp dirs."""
    now = time.time()
    with TOKEN_REGISTRY_LOCK:
        expired = [t for t, v in TOKEN_REGISTRY.items()
                   if now - v["created_at"] > EXPIRY_SECONDS]
        for token in expired:
            entry = TOKEN_REGISTRY.pop(token)
            _safe_rmtree(entry["temp_dir"])


def _safe_rmtree(dir_path: str):
    try:
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
            print(f"Cleaned up temp dir: {dir_path}")
    except Exception as e:
        print(f"Error cleaning up {dir_path}: {e}")


def _cleanup_token(token: str):
    """Background task: remove token from registry and delete its temp dir."""
    _expire_old_tokens()  # opportunistically clean up old tokens too
    with TOKEN_REGISTRY_LOCK:
        entry = TOKEN_REGISTRY.pop(token, None)
    if entry:
        _safe_rmtree(entry["temp_dir"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def read_root():
    return {"status": "Test Paper Generator API is running!"}


@app.post("/generate_paper")
async def generate_paper(request: Request):
    """
    Accepts the n8n payload, selects questions by Nano Concept, generates
    PDF + DOCX, stores the ZIP temporarily, and returns:
      - question_ids   : list of selected Question_ID strings
      - total_questions: int
      - download_token : opaque string – pass to GET /download/{token}
      - download_url   : convenience full URL (uses request base URL)
    """
    _expire_old_tokens()  # lightweight cleanup on every request

    data = await request.json()
    print("\n" + "=" * 50)
    print("Received payload:")
    print(json.dumps(data, indent=2))
    print("=" * 50 + "\n")

    # --- Parse payload ---
    nanoconcept_id_list = data.get("Nanoconcept_ID", [])
    grade_filter = [str(g).strip() for g in data.get("Grade", [])]

    if not nanoconcept_id_list:
        raise HTTPException(status_code=400, detail="Missing or empty Nanoconcept_ID")

    # --- Fetch sheet ---
    print("Fetching CSV from Google Sheets...")
    try:
        df = pd.read_csv(CSV_URL)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch Google Sheet: {e}")

    df.columns = df.columns.str.strip()

    required_cols = {"Nano_Concept_Code", "Question_ID"}
    missing = required_cols - set(df.columns)
    if missing:
        raise HTTPException(status_code=500, detail=f"Missing columns in sheet: {missing}")

    df["Nano_Concept_Code"] = df["Nano_Concept_Code"].astype(str).str.strip()
    df["Grade"] = df["Grade"].astype(str).str.strip()

    # --- Optional grade filter ---
    if grade_filter:
        df = df[df["Grade"].isin(grade_filter)]
        if df.empty:
            raise HTTPException(status_code=404,
                                detail=f"No questions found for Grade(s): {grade_filter}")

    # --- Select questions: per nano concept with cycling ---
    selected_rows = []
    for nano_entry in nanoconcept_id_list:
        if not isinstance(nano_entry, dict):
            continue
        for nano_id, count in nano_entry.items():
            nano_id = str(nano_id).strip()
            count = int(count)
            pool = df[df["Nano_Concept_Code"] == nano_id].to_dict("records")
            if not pool:
                print(f"Warning: No questions for Nano_Concept_Code='{nano_id}', skipping.")
                continue
            for i in range(count):
                selected_rows.append(pool[i % len(pool)])

    if not selected_rows:
        raise HTTPException(status_code=404,
                            detail="No questions could be selected for the provided Nanoconcept_IDs.")

    selected_df = pd.DataFrame(selected_rows)
    print(f"Selected {len(selected_df)} questions for the paper.")

    question_ids = selected_df["Question_ID"].astype(str).tolist()

    # --- Generate ZIP (PDF + DOCX) ---
    zip_file_path, temp_dir_path = generate_paper_package(selected_df)

    # --- Register download token ---
    token = uuid.uuid4().hex
    with TOKEN_REGISTRY_LOCK:
        TOKEN_REGISTRY[token] = {
            "zip_path": zip_file_path,
            "temp_dir": temp_dir_path,
            "created_at": time.time(),
        }

    base_url = str(request.base_url).rstrip("/")
    return JSONResponse(content={
        "question_ids": question_ids,
        "total_questions": len(question_ids),
        "download_token": token,
        "download_url": f"{base_url}/download/{token}",
    })


@app.get("/download/{token}")
async def download_paper(token: str, background_tasks: BackgroundTasks):
    """
    Streams the pre-generated ZIP for the given token.
    The file and its temp directory are deleted after the response is sent.
    """
    with TOKEN_REGISTRY_LOCK:
        entry = TOKEN_REGISTRY.get(token)

    if not entry:
        raise HTTPException(status_code=404,
                            detail="Download token not found or already used / expired.")

    zip_path = entry["zip_path"]
    if not os.path.exists(zip_path):
        raise HTTPException(status_code=410, detail="ZIP file no longer available.")

    background_tasks.add_task(_cleanup_token, token)

    return FileResponse(
        path=zip_path,
        filename="Test_Paper_Package.zip",
        media_type="application/zip",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
