from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import os
import shutil
import json
from datetime import datetime

load_dotenv()
KATALOG_DOCELOWY = os.getenv("SCIEZKA_ZAPISU", "./dataset_domyslny")
os.makedirs(KATALOG_DOCELOWY, exist_ok=True)

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def strona_glowna():
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
                <input type="text" name="id_osoby" required style="font-size: 16px; padding: 5px;"><br><br>
                
                <p>Zdanie (tylko glosy, rozdzielone spacją):</p>
                <input type="text" name="zdanie" required style="font-size: 16px; padding: 5px; width: 100%; max-width: 400px;"><br><br>
                
                <p>Nagraj wideo:</p>
                <input type="file" name="video" accept="video/*" capture="camcorder" required><br><br>
                
                <button type="submit" style="font-size: 18px; padding: 10px 20px; background-color: #4CAF50; color: white; border: none; border-radius: 5px;">Zapisz</button>
            </form>
        </body>
    </html>
    """

@app.post("/upload")
def wgraj_plik(id_osoby: str = Form(...), zdanie: str = Form(...), video: UploadFile = File(...)):
    teraz = datetime.now()
    znacznik_czasu = teraz.strftime("%Y%m%d_%H%M%S")
    bazowa_nazwa = f"osoba_{id_osoby}_{znacznik_czasu}"
    
    # zapis wideo
    rozszerzenie = video.filename.split(".")[-1] if "." in video.filename else "mp4"
    nazwa_pliku_wideo = f"{bazowa_nazwa}.{rozszerzenie}"
    
    with open(os.path.join(KATALOG_DOCELOWY, nazwa_pliku_wideo), "wb") as buffer:
        shutil.copyfileobj(video.file, buffer)
        
    # zapis json
    lista_glosow = zdanie.lower().split()
    dane_json = {
        "id_osoby": id_osoby,
        "data_nagrania": teraz.isoformat(),
        "glosy": lista_glosow,
    }
    
    with open(os.path.join(KATALOG_DOCELOWY, f"{bazowa_nazwa}.json"), "w", encoding="utf-8") as f:
        json.dump(dane_json, f, indent=4, ensure_ascii=False)

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