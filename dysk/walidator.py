"""
Dataset validation and maintenance script for the sign language translator.

This script performs a series of automated checks and corrections on the recorded dataset:
1. Losslessly removes audio tracks from all video files.
2. Cross-references recorded sentences with the master Excel file.
3. Recreates missing JSON metadata files based on video filenames.
4. Corrects sentence IDs in JSON files if they differ from the Excel database.
5. Updates the JSON structure to include 'glosses' (sign sequence) and a 
   'recorded_correctly' flag based on a provided errors list.
"""

import glob
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Set
import pandas as pd

try:
    import imageio_ffmpeg
except ImportError:
    print("BŁĄD: Brakuje biblioteki 'imageio-ffmpeg'.")
    print("Zainstaluj ją wpisując w terminalu: pip install imageio-ffmpeg")
    sys.exit(1)

VIDEO_FOLDER: str = "baza_wideo"
EXCEL_FILE: str = "prepared_sentences.xlsx"
ERRORS_FILE: str = "Błędy.txt"


def ask_yes_no(question: str) -> bool:
    """
    Prompts the user with a yes/no question via standard input.

    Args:
        question (str): The question to display to the user.

    Returns:
        bool: True if the user answers 'y', False if the user answers 'n'.
    """
    while True:
        ans = input(f"{question} (y/n): ").strip().lower()
        if ans == 'y':
            return True
        elif ans == 'n':
            return False


def remove_audio_from_videos(folder_path: str) -> None:
    """
    Losslessly removes the audio track from all .mp4 and .mov files in a directory.

    Utilizes the FFmpeg executable provided by imageio_ffmpeg.

    Args:
        folder_path (str): Path to the directory containing video files.
    """
    ffmpeg_exe: str = imageio_ffmpeg.get_ffmpeg_exe()
    videos: List[str] = glob.glob(os.path.join(folder_path, "*.mp4")) + \
                        glob.glob(os.path.join(folder_path, "*.mov"))
    
    if not videos:
        return
        
    print(f"Znaleziono {len(videos)} plików wideo. Trwa usuwanie dźwięku...")
    
    counter: int = 0
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
    Main execution pipeline for dataset validation and correction.
    """
    if not os.path.exists(VIDEO_FOLDER):
        print(f"BŁĄD: Nie znaleziono folderu z nagraniami: '{VIDEO_FOLDER}'.")
        sys.exit(1)
    
    if not os.path.exists(EXCEL_FILE):
        print(f"BŁĄD: Nie znaleziono pliku: '{EXCEL_FILE}'.")
        sys.exit(1)

    errors_set: Set[str] = set()
    if os.path.exists(ERRORS_FILE):
        with open(ERRORS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                clean_line = line.strip()
                if clean_line:
                    errors_set.add(clean_line)
    else:
        print(f"\nUWAGA: Nie znaleziono pliku '{ERRORS_FILE}'. Wszystkie nagrania zostaną oznaczone jako poprawne.")

    print("\n--- Oczyszczanie nagrań z dźwięku ---")
    remove_audio_from_videos(VIDEO_FOLDER)

    try:
        df: pd.DataFrame = pd.read_excel(EXCEL_FILE)
        if len(df.columns) < 3:
            print("BŁĄD: Plik Excel musi mieć co najmniej 3 kolumny (ID, Zdanie, Kolejność znaków)!")
            sys.exit(1)
                
        sentences_db: Dict[str, Dict[str, Any]] = {}
        id_to_sentence: Dict[str, str] = {}
        
        for idx in range(len(df)):
            row = df.iloc[idx]
            
            if pd.isna(row.iloc[1]):
                continue
                
            original_sentence = str(row.iloc[1]).strip()
            sentence_lower = original_sentence.lower()
            
            try:
                row_id = f"{int(row.iloc[0]):02d}"
            except ValueError:
                row_id = str(row.iloc[0]).strip()
                
            glosses = row.iloc[2] if pd.notna(row.iloc[2]) else None
            sentences_db[sentence_lower] = {'id': row_id, 'glosses': glosses}
            id_to_sentence[row_id] = original_sentence
            
            id_to_sentence[str(row.iloc[0]).strip()] = original_sentence
            
    except Exception as e:
        print(f"BŁĄD podczas czytania pliku Excel: {e}")
        sys.exit(1)

    print("\n--- Sprawdzanie i odtwarzanie plików .json ---")
    videos = glob.glob(os.path.join(VIDEO_FOLDER, "*.mp4")) + \
             glob.glob(os.path.join(VIDEO_FOLDER, "*.mov"))
    recreated_count: int = 0
    
    for video in videos:
        base_name = os.path.splitext(video)[0]
        json_file = f"{base_name}.json"
        
        if not os.path.exists(json_file):
            filename_only = os.path.basename(base_name)
            print(f"Brak pliku .json dla wideo '{filename_only}'. Próbuję odtworzyć...")
            
            file_parts = filename_only.split('_')
            
            if len(file_parts) >= 2:
                p_id = file_parts[0]
                s_id = file_parts[1]
                s_id_padded = f"{int(s_id):02d}" if s_id.isdigit() else s_id
                
                if s_id_padded in id_to_sentence:
                    sentence_text = id_to_sentence[s_id_padded]
                elif s_id in id_to_sentence:
                    sentence_text = id_to_sentence[s_id]
                else:
                    print(f" -> BŁĄD: W Excelu nie ma zdania o ID '{s_id}'. Nie mogę odtworzyć JSON-a. Przerwano!")
                    sys.exit(1)
                
                rec_date = ""
                if len(file_parts) >= 4:
                    d_str = file_parts[2]
                    t_str = file_parts[3]
                    if len(d_str) == 8 and len(t_str) >= 6:
                        rec_date = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}T{t_str[:2]}:{t_str[2:4]}:{t_str[4:6]}.000000"
                        
                temp_data = {
                    "person_id": p_id,
                    "sentence_id": s_id,
                    "recording_date": rec_date,
                    "sentence": sentence_text
                }
                
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(temp_data, f, indent=4, ensure_ascii=False)
                
                print(f" -> Pomyślnie odtworzono: {filename_only}.json")
                recreated_count += 1
            else:
                print(f" -> BŁĄD: Nazwa '{filename_only}' ma nietypowy format. Nie mogę wyciągnąć danych.")
                sys.exit(1)
                
    if recreated_count == 0:
        print("Wszystkie nagrania mają swoje pliki .json.")
    else:
        print(f"Odtworzono łącznie {recreated_count} zgubionych plików .json.")

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

    print("\n--- Aktualizacja struktury JSON (Glosses & Poprawność) ---")
    
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
        print("UWAGA: W pliku Excel brakuje wpisów w kolumnie 'kolejność znaków' dla następujących nagrań:")
        for b in missing_glosses[:5]:  
            print(f" - {b}")
        if len(missing_glosses) > 5:
            print(f" ...i {len(missing_glosses) - 5} innych.")
            
        if not ask_yes_no("Czy pominąć brakujące i kontynuować przebudowę plików?"):
            sys.exit(1)
            
    counter: int = 0
    for json_path in json_files:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        json_sentence = data.get("sentence", "").strip().lower()
        raw_glosses = sentences_db[json_sentence]['glosses']
        
        gloss_list = data.get("glosses", data.get("glosy", [])) 
        if raw_glosses:
            separator = ',' if ',' in str(raw_glosses) else ' '
            gloss_list = [g.strip() for g in str(raw_glosses).split(separator) if g.strip()]

        p_id_raw = data.get('person_id', '')
        s_id_raw = data.get('sentence_id', '')
        
        try:
            error_key_int = f"{int(p_id_raw)}_{int(s_id_raw)}"
        except ValueError:
            error_key_int = None
            
        error_key_raw = f"{p_id_raw}_{s_id_raw}"

        is_correct: bool = True
        if (error_key_int and error_key_int in errors_set) or (error_key_raw in errors_set):
            is_correct = False

        new_data = {
            "recorded_correctly": is_correct,
            "person_id": p_id_raw,
            "sentence_id": s_id_raw,
            "recording_date": data.get("recording_date", ""),
            "sentence": data.get("sentence", ""),
            "glosses": gloss_list
        }

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, indent=4, ensure_ascii=False)
        counter += 1

    print(f"\nGotowe! Zaktualizowano strukturę JSON dla {counter} plików.")


if __name__ == "__main__":
    main()