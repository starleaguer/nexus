from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

load_dotenv(dotenv_path='../.env')

import database
import youtube_extractor
import summarizer

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ProcessRequest(BaseModel):
    url: str
    model_provider: str = 'ollama'  # ollama or gemini
    model_name: str = 'gemma4'      # specific model name

@app.on_event("startup")
def startup_event():
    database.init_db()

@app.post("/api/process")
def process_video(req: ProcessRequest):
    try:
        # Extract YouTube Content (Includes robust metadata & Whisper fallback)
        extracted_data = youtube_extractor.extract_youtube_content(req.url)
        
        if not extracted_data.get('transcript'):
            raise HTTPException(status_code=400, detail="Could not extract transcript or audio.")
        
        # Summarize
        summary = summarizer.generate_summary(
            text=extracted_data['transcript'],
            model_provider=req.model_provider,
            model_name=req.model_name
        )
        
        # Save to DB and export to Markdown
        save_data = {
            "video_id": extracted_data['video_id'],
            "url": req.url,
            "metadata": extracted_data['metadata'],
            "transcript": extracted_data['transcript'],
            "summary": summary,
            "model_used": f"{req.model_provider}:{req.model_name}"
        }
        
        database.save_video(save_data)
        
        return {
            "status": "success",
            "video_id": extracted_data['video_id'],
            "message": "Processed successfully and saved to notebooklm_sources."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/videos")
def get_videos():
    try:
        videos = database.get_all_videos()
        return videos
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/videos/{video_id}")
def delete_video_endpoint(video_id: str):
    try:
        database.delete_video(video_id)
        return {"status": "success", "message": "Deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from fastapi.staticfiles import StaticFiles
import os

frontend_path = os.path.join(os.path.dirname(__file__), '../frontend')
app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8088)
