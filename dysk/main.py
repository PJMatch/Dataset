from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from typing import Optional
from dotenv import load_dotenv
import os
import shutil
import json
import re
from datetime import datetime

load_dotenv()

TARGET_DIR = os.getenv("SCIEZKA_ZAPISU", "./default_dataset")
os.makedirs(TARGET_DIR, exist_ok=True)

CSV_PATH = os.path.join(os.path.dirname(__file__), "Sentences.csv")

sentences_dict = {}

if os.path.exists(CSV_PATH):
    try:
        with open(CSV_PATH, mode='r', encoding='utf-8-sig') as file:
            line_counter = 1
            for line in file:
                line = line.strip()
                if not line:
                    continue
                
                match = re.match(r'^(\d+)[;,]\s*(.*)', line)
                if match:
                    sentences_dict[match.group(1)] = match.group(2)
                else:
                    sentences_dict[str(line_counter)] = line
                
                line_counter += 1
    except Exception:
        pass

app = FastAPI()

def remove_polish_chars(text: str) -> str:
    """
    Removes Polish characters and replaces non-alphanumeric characters with underscores.
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

@app.get("/", response_class=HTMLResponse)
def render_form(person_id: Optional[str] = "", next_sentence_id: Optional[str] = "") -> HTMLResponse:
    """
    Renders the main HTML form for video and sentences upload.
    Prefills person_id and sentence_id if provided via URL parameters.
    """
    sentences_json = json.dumps(sentences_dict, ensure_ascii=False)
    
    return f"""
    <!DOCTYPE html>
    <html>
        <head>
            <title>Dodaj nagranie</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial; padding: 20px; max-width: 600px; margin: 0 auto; }}
                input[type="text"], input[type="number"], textarea {{ font-size: 16px; padding: 8px; width: 100%; box-sizing: border-box; }}
                .radio-group {{ margin-bottom: 15px; }}
                
                /* Nowy, duży styl dla pola wyboru wideo */
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
                /* Stylizacja samego przycisku "Wybierz plik" wewnątrz pola */
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
                    <label><input type="radio" name="mode" value="csv" checked onchange="toggleMode()"> Wybierz ID z pliku CSV</label><br>
                    <label><input type="radio" name="mode" value="custom" onchange="toggleMode()"> Wpisz własne zdanie</label>
                </div>
                
                <div id="csv_input_group">
                    <p>ID zdania (1-500):</p>
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
                    
                    if (sentencesDict[idValue]) {{
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

@app.post("/upload", response_class=HTMLResponse)
def upload_video(
    person_id: str = Form(...), 
    sentence_id: str = Form(""), 
    sentence: str = Form(...), 
    video: UploadFile = File(...)
) -> HTMLResponse:
    """
    Handles the uploaded video file, generates metadata, and saves both to the target directory.
    """
    now = datetime.now()
    date_str = now.strftime("%Y%m%d_%H%M%S")
    
    next_id = ""
    if sentence_id and sentence_id.strip():
        try:
            numeric_id = int(sentence_id)
            safe_sentence_id = f"{numeric_id:02d}"
            next_id = str(numeric_id + 1)
        except ValueError:
            safe_sentence_id = sentence_id.strip()
    else:
        safe_sentence_id = remove_polish_chars(sentence)
    
    base_filename = f"{person_id}_{safe_sentence_id}_{date_str}"
    
    extension = video.filename.split(".")[-1] if "." in video.filename else "mp4"
    video_filename = f"{base_filename}.{extension}"
    
    with open(os.path.join(TARGET_DIR, video_filename), "wb") as buffer:
        shutil.copyfileobj(video.file, buffer)
        
    json_data = {
        "person_id": person_id,
        "sentence_id": safe_sentence_id,
        "recording_date": now.isoformat(),
        "sentence": sentence.strip()
    }
    
    with open(os.path.join(TARGET_DIR, f"{base_filename}.json"), "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4, ensure_ascii=False)

    redirect_url = f"/?person_id={person_id}&next_sentence_id={next_id}"

    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta charset="UTF-8">
            <meta http-equiv="refresh" content="3;url={redirect_url}">
        </head>
        <body style="font-family: Arial; padding: 20px; text-align: center;">
            <h2 style="color: green;">Zapisano pomyślnie!</h2>
            <p><strong>Zapisano jako:</strong><br>{video_filename}</p>
            <br>
            <p style="color: gray; font-size: 14px;">Za 3 sekundy nastąpi automatyczny powrót do formularza...</p>
            <br>
            <a href="{redirect_url}" style="font-size: 18px; padding: 10px 20px; background-color: #2196F3; color: white; text-decoration: none; border-radius: 5px;">Wróć ręcznie</a>
        </body>
    </html>
    """)
