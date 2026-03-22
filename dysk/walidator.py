import os
import glob
import json
import sys
import subprocess
import pandas as pd
from typing import Dict, List, Any

try:
    import imageio_ffmpeg
except ImportError:
    print("BŁĄD: Brakuje biblioteki 'imageio-ffmpeg'.")
    print("Zainstaluj ją wpisując w terminalu: pip install imageio-ffmpeg")
    sys.exit(1)

VIDEO_FOLDER = "baza_wideo"
EXCEL_FILE = "prepared_sentences.xlsx"

def ask_yes_no(question: str) -> bool:
    """
    Prompts the user with a yes/no question and returns a boolean.

    Args:
        question (str): The question to present to the user.

    Returns:
        bool: True if the user answers 'y', False if 'n'.
    """
    while True:
        ans = input(f"{question} (y/n): ").strip().lower()
        if ans == 'y':
            return True
        elif ans == 'n':
            return False

def remove_audio_from_videos(folder_path: str) -> None:
    """
    Losslessly removes the audio track from all video files in the specified directory.

    Args:
        folder_path (str): Path to the folder containing video files.
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    videos = glob.glob(os.path.join(folder_path, "*.mp4")) + glob.glob(os.path.join(folder_path, "*.mov"))
    
    if not videos:
        return
        
    print(f"Znaleziono {len(videos)} plików wideo. Trwa usuwanie dźwięku")
    
    counter = 0
    for video in videos:
        temp_file = video + ".temp.mp4"
        
        command = [
            ffmpeg_exe, "-y", "-i", video, 
            "-c", "copy", "-an", temp_file
        ]
        
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if result.returncode == 0 and os.path.exists(temp_file):
            os.replace(temp_file, video)
            counter += 1
        else:
            print(f"Nie udało się usunąć dźwięku z '{os.path.basename(video)}'")
            if os.path.exists(temp_file):
                os.remove(temp_file)
                
    print(f"Pomyślnie usunięto dźwięk z {counter} nagrań.")

def main() -> None:
    """
    Main execution function: strips audio, validates datasets, corrects IDs based 
    on Excel data, and appends glosses to JSON metadata.
    """
    if not os.path.exists(VIDEO_FOLDER):
        print(f"BŁĄD: Nie znaleziono folderu z nagraniami: '{VIDEO_FOLDER}'.")
        sys.exit(1)
    
    if not os.path.exists(EXCEL_FILE):
        print(f"BŁĄD: Nie znaleziono pliku: '{EXCEL_FILE}'.")
        sys.exit(1)

    print("\n--- Oczyszczanie nagrań z dźwięku ---")
    remove_audio_from_videos(VIDEO_FOLDER)

    try:
        df = pd.read_excel(EXCEL_FILE)
        if len(df.columns) < 3:
            print("BŁĄD: Plik Excel musi mieć co najmniej 3 kolumny (ID, Zdanie, Kolejność znaków)!")
            sys.exit(1)
                
        sentences_db: Dict[str, Dict[str, Any]] = {}
        
        for idx in range(len(df)):
            row = df.iloc[idx]
            
            if pd.isna(row.iloc[1]):
                continue
                
            sentence = str(row.iloc[1]).strip().lower()
            
            try:
                row_id = f"{int(row.iloc[0]):02d}"
            except ValueError:
                row_id = str(row.iloc[0]).strip()
                
            glosses = row.iloc[2] if pd.notna(row.iloc[2]) else None
            sentences_db[sentence] = {'id': row_id, 'glosses': glosses}
            
    except Exception as e:
        print(f"BŁĄD podczas czytania pliku Excel: {e}")
        sys.exit(1)

    print("\n--- Sprawdzanie obecności plików .json ---")
    videos = glob.glob(os.path.join(VIDEO_FOLDER, "*.mp4")) + glob.glob(os.path.join(VIDEO_FOLDER, "*.mov"))
    
    for video in videos:
        base_name = os.path.splitext(video)[0]
        json_file = f"{base_name}.json"
        if not os.path.exists(json_file):
            print(f"BŁĄD: Brak pliku .json dla nagrania: '{os.path.basename(video)}'")
            sys.exit(1)
    
    print("Każde nagranie ma swój plik .json.")

    print("\n--- Walidacja ID zdań ---")
    json_files = glob.glob(os.path.join(VIDEO_FOLDER, "*.json"))
    to_correct: List[Dict[str, Any]] = []

    for json_path in json_files:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        json_sentence = data.get("sentence", "").strip().lower()
        json_id = data.get("sentence_id", "").strip()
        
        if json_sentence not in sentences_db:
            print(f"BŁĄD: Zdanie z pliku '{os.path.basename(json_path)}' nie występuje w pliku {EXCEL_FILE}!")
            print(f"Treść nieznanego zdania: '{json_sentence}'")
            sys.exit(1)
            
        excel_id = sentences_db[json_sentence]['id']
        if json_id != excel_id:
            to_correct.append({
                'json_path': json_path,
                'data': data,
                'wrong_id': json_id,
                'correct_id': excel_id
            })

    if to_correct:
        for correction in to_correct:
            old_json_path = correction['json_path']
            base_name = os.path.splitext(old_json_path)[0]
            old_video_path = f"{base_name}.mp4"
            if not os.path.exists(old_video_path):
                old_video_path = f"{base_name}.mov"
            
            print(f"\nNiezgodność ID w pliku: '{os.path.basename(old_json_path)}'")
            print(f"W pliku .json jest ID: '{correction['wrong_id']}', a w Excelu to zdanie ma ID: '{correction['correct_id']}'.")
            
            if ask_yes_no("Czy poprawić to na ID zgodne z Excelem?"):
                correction['data']['sentence_id'] = correction['correct_id']
                
                parts = os.path.basename(base_name).split('_')
                if len(parts) >= 4:
                    new_base_name = f"{parts[0]}_{correction['correct_id']}_{parts[2]}_{parts[3]}"
                else:
                    new_base_name = f"{correction['data']['person_id']}_{correction['correct_id']}"
                
                new_json_path = os.path.join(VIDEO_FOLDER, f"{new_base_name}.json")
                ext = os.path.splitext(old_video_path)[1]
                new_video_path = os.path.join(VIDEO_FOLDER, f"{new_base_name}{ext}")
                
                with open(new_json_path, 'w', encoding='utf-8') as f:
                    json.dump(correction['data'], f, indent=4, ensure_ascii=False)
                
                if os.path.exists(old_video_path):
                    os.rename(old_video_path, new_video_path)
                
                os.remove(old_json_path)
                print("-> Poprawiono pomyślnie.")
            else:
                sys.exit(1)
    else:
        print("Wszystkie ID zgadzają się z Excelem.")

    print("\n--- Aktualizacja glosów ---")
    json_files = glob.glob(os.path.join(VIDEO_FOLDER, "*.json"))
    missing_glosses: List[str] = []
    
    for json_path in json_files:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        json_sentence = data.get("sentence", "").strip().lower()
        glosses = sentences_db[json_sentence]['glosses']
        
        if not glosses:
            missing_glosses.append(os.path.basename(json_path))
            
    if missing_glosses:
        print(f"UWAGA: W pliku Excel brakuje wpisów w kolumnie 'kolejność znaków' dla następujących nagrań:")
        for b in missing_glosses:
            print(f" - {b}")
            
        if not ask_yes_no("Czy pominąć brakujące i dopisać glosy tylko do pozostałych plików?"):
            sys.exit(1)
            
    counter = 0
    for json_path in json_files:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        json_sentence = data.get("sentence", "").strip().lower()
        raw_glosses = sentences_db[json_sentence]['glosses']
        
        if raw_glosses:
            separator = ',' if ',' in str(raw_glosses) else ' '
            gloss_list = [g.strip() for g in str(raw_glosses).split(separator) if g.strip()]
            
            data['glosy'] = gloss_list
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            counter += 1

    print(f"\nDopisywanie glosów zakończone.")

if __name__ == "__main__":
    main()