"""
API for gathering a sign language dataset.

This module provides a FastAPI application with a web interface 
for recording videos directly from the browser, assigning person 
and sentence IDs, and saving them to disk along with JSON metadata.
Recordings are automatically cropped to a 1:1 aspect ratio using FFmpeg.
"""

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from typing import Dict, Optional
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

load_dotenv()

TARGET_DIR: str = os.getenv("SCIEZKA_ZAPISU", "./default_dataset")
os.makedirs(TARGET_DIR, exist_ok=True)

EXCEL_PATH: str = os.path.join(os.path.dirname(__file__), "prepared_sentences.xlsx")

sentences_dict: Dict[str, str] = {}

if os.path.exists(EXCEL_PATH):
    df = pd.read_excel(EXCEL_PATH)

    if len(df.columns) >= 2:
        for idx in range(len(df)):
            row = df.iloc[idx]
            if pd.isna(row.iloc[1]):
                continue
            sentence = str(row.iloc[1]).strip()
            row_id = f"{int(row.iloc[0]):02d}"
            sentences_dict[row_id] = sentence

app = FastAPI(
    title="Sign Language Dataset API",
    description="API for recording and cataloging sign language video samples.",
    version="1.0.0"
)


def remove_polish_chars(text: str) -> str:
    """
    Removes Polish diacritics and replaces non-alphanumeric characters with underscores.

    Args:
        text (str): The input text to be processed.

    Returns:
        str: A cleaned string containing only lowercase English letters, 
             numbers, and underscores (instead of spaces).
    """
    replacements = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z'
    }
    text = text.lower()
    for pl_char, asc_char in replacements.items():
        text = text.replace(pl_char, asc_char)
    text = re.sub(r'[^a-z0-9\s]', '', text)
    return re.sub(r'\s+', '_', text.strip())


@app.get("/sentences", response_class=JSONResponse)
def get_sentences() -> JSONResponse:
    """
    Returns a dictionary of available sentences loaded from the Excel file.

    Returns:
        JSONResponse: A JSON object mapping sentence IDs to their text content.
    """
    return JSONResponse(content=sentences_dict)


@app.get("/", response_class=HTMLResponse)
def render_form(
    person_id: Optional[str] = "", 
    next_sentence_id: Optional[str] = ""
) -> HTMLResponse:
    """
    Renders the main HTML form for video recording and sentence selection.

    Optionally pre-fills the person ID and sentence ID if passed as URL 
    parameters (useful for iterative recording).

    Args:
        person_id (Optional[str], optional): Identifier of the recorded person (e.g., "01"). Defaults to "".
        next_sentence_id (Optional[str], optional): Identifier of the next sentence. Defaults to "".

    Returns:
        HTMLResponse: The generated HTML form string.
    """
    sentences_json = json.dumps(sentences_dict, ensure_ascii=False)
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="pl">
        <head>
            <title>Dodaj nagranie</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial; padding: 20px; max-width: 600px; margin: 0 auto; }}
                input[type="text"], input[type="number"], textarea {{ font-size: 16px; padding: 8px; width: 100%; box-sizing: border-box; }}
                .radio-group {{ margin-bottom: 15px; }}
                input[type="file"] {{
                    display: block;
                    width: 100%;
                    padding: 15px;
                    margin-top: 5px;
                    background-color: #f8f9fa;
                    border: 2px dashed #ced4da;
                    border-radius: 8px;
                    box-sizing: border-box;
                    font-size: 16px;
                }}
                input[type="file"]::file-selector-button {{
                    background-color: #2196F3;
                    color: white;
                    padding: 15px 25px;
                    border: none;
                    border-radius: 6px;
                    font-size: 18px;
                    font-weight: bold;
                    cursor: pointer;
                    margin-right: 15px;
                }}
            </style>
        </head>
        <body>
            <h2>Dodaj nowe nagranie do datasetu</h2>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <p><strong>ID osoby (np. 01):</strong></p>
                <input type="text" name="person_id" value="{person_id}" required><br><br>
                <p><strong>Wybór zdania:</strong></p>
                <div class="radio-group">
                    <label><input type="radio" name="mode" value="csv" checked onchange="toggleMode()"> Wybierz ID z pliku Excel</label><br>
                    <label><input type="radio" name="mode" value="custom" onchange="toggleMode()"> Wpisz własne zdanie</label>
                </div>
                <div id="csv_input_group">
                    <p>ID zdania (np. 1-500):</p>
                    <input type="number" name="sentence_id" id="sentence_id" value="{next_sentence_id}" oninput="updateSentencePreview()">
                </div>
                <p><strong>Treść zdania:</strong></p>
                <textarea name="sentence" id="sentence_text" rows="3" required readonly></textarea>
                <p id="sentence_error" style="color: red; font-size: 14px; display: none;">Nie znaleziono zdania o podanym ID!</p>
                <br>
                <p><strong>Nagraj wideo:</strong></p>
                <input type="file" name="video" accept="video/*" capture="camcorder" required><br><br>
                <button type="submit" style="font-size: 18px; padding: 10px 20px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; width: 100%;">Zapisz Nagranie</button>
            </form>
            <script>
                const sentencesDict = {sentences_json};
                window.onload = function() {{
                    if (document.getElementById('sentence_id').value) {{
                        updateSentencePreview();
                    }}
                }};
                function toggleMode() {{
                    const isCustom = document.querySelector('input[name="mode"]:checked').value === 'custom';
                    const idGroup = document.getElementById('csv_input_group');
                    const textArea = document.getElementById('sentence_text');
                    const idInput = document.getElementById('sentence_id');
                    const errorMsg = document.getElementById('sentence_error');
                    if (isCustom) {{
                        idGroup.style.display = 'none';
                        textArea.readOnly = false;
                        textArea.value = '';
                        idInput.value = '';
                        errorMsg.style.display = 'none';
                        textArea.placeholder = "Wpisz swoje zdanie tutaj...";
                    }} else {{
                        idGroup.style.display = 'block';
                        textArea.readOnly = true;
                        textArea.placeholder = "";
                        updateSentencePreview();
                    }}
                }}
                function updateSentencePreview() {{
                    const idValue = document.getElementById('sentence_id').value;
                    const textArea = document.getElementById('sentence_text');
                    const errorMsg = document.getElementById('sentence_error');
                    if (!idValue) {{
                        textArea.value = '';
                        errorMsg.style.display = 'none';
                        return;
                    }}
                    // Format value (e.g., "5" to "05") to match dictionary keys
                    let formattedId = idValue;
                    if (!isNaN(idValue) && idValue.trim() !== '') {{
                        formattedId = String(Number(idValue)).padStart(2, '0');
                    }}
                    if (sentencesDict[formattedId]) {{
                        textArea.value = sentencesDict[formattedId];
                        errorMsg.style.display = 'none';
                    }} else if (sentencesDict[idValue]) {{
                        // Fallback to the original value
                        textArea.value = sentencesDict[idValue];
                        errorMsg.style.display = 'none';
                    }} else {{
                        textArea.value = '';
                        errorMsg.style.display = 'block';
                    }}
                }}
            </script>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.post("/upload", response_class=HTMLResponse)
def upload_video(
    person_id: str = Form(...),
    sentence_id: str = Form(""),
    sentence: str = Form(...),
    video: UploadFile = File(...)
) -> HTMLResponse:
    """
    Receives and processes the uploaded video recording.

    This function temporarily saves the video, uses FFmpeg to crop it to 
    a square (1:1 ratio), generates the final filename, and then saves 
    the video file along with its corresponding JSON metadata file.

    Args:
        person_id (str): The person's identifier from the form.
        sentence_id (str, optional): The sentence identifier from the form.
        sentence (str): The text of the spoken sentence from the form.
        video (UploadFile): The uploaded video file.

    Returns:
        HTMLResponse: A simple "OK" message indicating a successful operation.
    """
    now = datetime.now()
    date_str = now.strftime("%Y%m%d_%H%M%S")
    
    if sentence_id and sentence_id.strip():
        try:
            numeric_id = int(sentence_id)
            safe_sentence_id = f"{numeric_id:02d}"
        except ValueError:
            safe_sentence_id = sentence_id.strip()
    else:
        safe_sentence_id = remove_polish_chars(sentence)
        
    base_filename = f"{person_id}_{safe_sentence_id}_{date_str}"
    
    extension = video.filename.split(".")[-1] if video.filename and "." in video.filename else "mp4"
    
    final_filename = f"{base_filename}.{extension}"
    final_filepath = os.path.join(TARGET_DIR, final_filename)
    temp_filepath = os.path.join(TARGET_DIR, f"temp_{final_filename}")
    
    with open(temp_filepath, "wb") as buffer:
        shutil.copyfileobj(video.file, buffer)
        
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", temp_filepath,
                "-vf", "crop='min(iw,ih)':'min(iw,ih)'",
                "-c:a", "copy",
                final_filepath
            ], 
            check=True, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        os.remove(temp_filepath)
    except Exception as e:
        print(f"Błąd FFmpeg (zapisano oryginał): {e}")
        shutil.move(temp_filepath, final_filepath)
        
    json_data = {
        "person_id": person_id,
        "sentence_id": safe_sentence_id,
        "recording_date": now.isoformat(),
        "sentence": sentence.strip()
    }
    
    json_filepath = os.path.join(TARGET_DIR, f"{base_filename}.json")
    with open(json_filepath, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4, ensure_ascii=False)

    return HTMLResponse(content="OK")