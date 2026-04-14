# Sign Language Dataset Collection Server

A lightweight FastAPI-based server designed to streamline the collection of a sign language video dataset. This tool acts as a bridge, receiving video files and metadata from a dedicated Android application and saving them directly to your local disk.

## General Workflow

The computer running this server acts as a central hub:

1. **The Client (Android App):** Users record videos using a custom Android application. The app connects to the server securely via a Cloudflare Tunnel URL, meaning users do not need to be on the same local Wi-Fi network.
2. **The Server (Local Machine):** Receives the uploaded video, processes it instantly (crops the video to a 1:1 square aspect ratio using FFmpeg), and generates an initial `.json` metadata file.
3. **The Storage (Target Drive):** Files are saved directly to the configured directory on the local machine running the server, completely abstracting the setup complexity away from the mobile users.

## How to Run the Server

Follow these steps to configure and start the server on your local machine.

### 1. Environment Configuration

Create a `.env` file in the root directory of the project (the same folder as `main.py`). This file defines where the server should save the incoming dataset files. 

Add the following content, uncommenting the path and adjusting it to your needs:

```ini
# Set the local path where the dataset will be saved:
# SCIEZKA_ZAPISU=./baza_wideo
```

### 2. Install Dependencies

Ensure you have Python installed, then install the required libraries. You will also need to have `ffmpeg` installed on your system for video processing.

```bash
pip install fastapi uvicorn pandas python-dotenv python-multipart openpyxl imageio-ffmpeg
```

### 3. Start the Server

Run the FastAPI application using Uvicorn. Open your terminal in the project directory and execute:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Once running, you can expose the local `8000` port using your Cloudflare Tunnel and paste the generated URL into the Android application.

## Data Structure & Validation

For every recorded video, the server creates two corresponding files in the target directory sharing the same base name. 

**Naming Convention:** `{person_id}_{sentence_id}_{timestamp}.[extension]`
* **Video File:** `1_01_20260311_171803.mp4`
* **Metadata File:** `1_01_20260311_171803.json`

### Data Validation (`walidator.py`)

The API generates a basic JSON upon upload. However, the project includes a powerful validation script (`walidator.py`). Running this script performs essential dataset maintenance:
* Losslessly removes audio tracks from all video files.
* Verifies sentence IDs against the master `prepared_sentences.xlsx` database.
* Recreates any missing JSON files based on video filenames.
* Updates the JSON structure to include sign language glosses and checks against a known errors list (`Błędy.txt`).

### Final `.json` Structure

After running the validation script, the complete `.json` file for each recording looks exactly like this:

```json
{
    "recorded_correctly": true,
    "person_id": "13",
    "sentence_id": "193",
    "recording_date": "2026-04-10T15:02:10.283727",
    "sentence": "Uczymy się dzisiaj, a jutro idziemy spać.",
    "glosses": [
        "DZISIAJ",
        "MY",
        "UCZYĆ-SIĘ",
        "JUTRO",
        "SPAĆ",
        "IŚĆ"
    ]
}
```