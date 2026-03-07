from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import os
import shutil
import json
from datetime import datetime

load_dotenv()

TARGET_DIR = os.getenv("SCIEZKA_ZAPISU", "./default_dataset")
os.makedirs(TARGET_DIR, exist_ok=True)

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def render_form() -> HTMLResponse:
    """
    Renders the main HTML form for video and glosses upload.
    
    Returns:
        HTMLResponse: The HTML content containing the submission form.
    """
    return """
    <!DOCTYPE html>
    <html>
        <head>
            <title>Dodaj nagranie</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta charset="UTF-8">
        </head>
        <body style="font-family: Arial; padding: 20px;">
            <h2>Dodaj nowe nagranie do datasetu</h2>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <p>ID osoby:</p>
                <input type="text" name="person_id" required style="font-size: 16px; padding: 5px;"><br><br>
                
                <p>Zdanie (tylko glosy, rozdzielone spacją):</p>
                <input type="text" name="sentence" required style="font-size: 16px; padding: 5px; width: 100%; max-width: 400px;"><br><br>
                
                <p>Nagraj wideo:</p>
                <input type="file" name="video" accept="video/*" capture="camcorder" required><br><br>
                
                <button type="submit" style="font-size: 18px; padding: 10px 20px; background-color: #4CAF50; color: white; border: none; border-radius: 5px;">Zapisz</button>
            </form>
        </body>
    </html>
    """

@app.post("/upload", response_class=HTMLResponse)
def upload_video(
    person_id: str = Form(...), 
    sentence: str = Form(...), 
    video: UploadFile = File(...)
) -> HTMLResponse:
    """
    Handles the uploaded video file, generates metadata, and saves both to the target directory.
    
    Args:
        person_id (str): The unique identifier of the person signing.
        sentence (str): The glosses representing the signed sentence, separated by spaces.
        video (UploadFile): The uploaded video file object.
        
    Returns:
        HTMLResponse: A success message with a link to submit another video.
    """
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    base_filename = f"person_{person_id}_{timestamp}"
    
    extension = video.filename.split(".")[-1] if "." in video.filename else "mp4"
    video_filename = f"{base_filename}.{extension}"
    
    with open(os.path.join(TARGET_DIR, video_filename), "wb") as buffer:
        shutil.copyfileobj(video.file, buffer)
        
    gloses_list = sentence.lower().split()
    json_data = {
        "person_id": person_id,
        "recording_date": now.isoformat(),
        "gloses": gloses_list,
    }
    
    with open(os.path.join(TARGET_DIR, f"{base_filename}.json"), "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4, ensure_ascii=False)

    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <body style="font-family: Arial; padding: 20px; text-align: center;">
            <h2 style="color: green;">Zapisano pomyślnie!</h2>
            <br>
            <a href="/" style="font-size: 18px; padding: 10px; background-color: #2196F3; color: white; text-decoration: none; border-radius: 5px;">Dodaj kolejne nagranie</a>
        </body>
    </html>
    """)