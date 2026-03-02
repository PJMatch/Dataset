# Aplikacja do zapisu danych na dysku

Prosta i lekka aplikacja oparta na FastAPI, służąca do sprawnego zbierania datasetu. Narzędzie pozwala na szybkie zgrywanie plików z telefonów komórkowych (w postaci .mp4 + .json) prosto na dysk lokalny lub bezpośrednio na dysk Politechniki Gdańskiej.

## Jak to działa?

Komputer, na którym uruchomiony jest ten serwer, działa jako "most":

1. Urządzenia nagrywające (Telefony): Łączą się z serwerem przez zwykłą przeglądarkę (po lokalnym Wi-Fi lub przez wygenerowany link z narzędzia Ngrok). Użytkownicy widzą tylko prosty formularz HTML.
2. Serwer lokalny (Laptop): Odbiera plik wideo, błyskawicznie generuje plik .json i przekazuje dane dalej.
3. Dysk docelowy (PG): Dzięki temu, że laptop jest połączony z uczelnianą siecią przez VPN, aplikacja zapisuje pliki prosto na zmapowany dysk sieciowy. 

Dzięki temu osoby nagrywające nie muszą łączyć się z siecią VPN na swoich telefonach.

## Konfiguracja środowiska .env

Aby uruchomić aplikację, musisz ręcznie utworzyć plik o nazwie `.env` w głównym folderze projektu (w tym samym, w którym znajduje się plik main.py) i wkleić do niego poniższą zawartość (należy odkomentować odpowiednią opcję):
```ini
# Lokalnie:
# SCIEZKA_ZAPISU=./baza_wideo

# Dysk PG:
# SCIEZKA_ZAPISU=Z:\
```

## Struktura danych

Dla każdego dodanego nagrania, serwer tworzy w folderze docelowym dwa pliki z tą samą nazwą bazową (gwarantuje to łatwe łączenie wideo z etykietami podczas treningu sieci).

**1. Plik wideo:** `osoba_07_20260301_222053.mp4`
**2. Metadane:** `osoba_07_20260301_222053.json`

## Przykladowa struktura pliku .json:
```json
{
    "id_osoby": "07",
    "data_nagrania": "2026-03-01T22:20:53.922225",
    "glosy": [
        "kolejne",
        "nagranie"
    ]
}