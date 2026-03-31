import paramiko
import os
import threading
import re
import tkinter as tk
from tkinter import messagebox
from collections import defaultdict
from dotenv import load_dotenv

# Wczytanie zmiennych środowiskowych z pliku .env
load_dotenv()

hostname = os.getenv('SSH_HOST')
username = os.getenv('SSH_USER')
password = os.getenv('SSH_PASS')
pjm_directory = os.getenv('SSH_PATH')

class SSHFileApp:
    def __init__(self, root):
        self.root = root
        self.root.title("SSH PJM - Statystyki Zdań i Osób")
        self.root.geometry("750x550") # Nieco szersze okno
        
        # PAMIĘĆ PODRĘCZNA: (id_osoby, nazwa_pliku, id_zdania)
        self.all_files_data = []

        self.setup_ui()

    def setup_ui(self):
        """Tworzy interfejs użytkownika."""
        main_padding = {'padx': 20, 'pady': 10}

        # --- PRZYCISK POBIERANIA ---
        self.fetch_button = tk.Button(self.root, text="1. Pobierz pliki z serwera", 
                                      bg="#4CAF50", fg="white", font=("Arial", 11, "bold"),
                                      command=self.start_fetching)
        self.fetch_button.pack(fill=tk.X, padx=20, pady=(15, 5))

        self.status_label = tk.Label(self.root, text="Gotowy do pracy.", font=("Arial", 10), fg="gray")
        self.status_label.pack(fill=tk.X, padx=20)

        # --- SEKCJA WYSZUKIWANIA I STATYSTYK ---
        search_frame = tk.LabelFrame(self.root, text=" Wyszukiwanie (Opcjonalnie) ", padx=10, pady=10)
        search_frame.pack(fill=tk.X, **main_padding)
        
        tk.Label(search_frame, text="Szukaj po ID osoby:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var, font=("Arial", 10))
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        self.search_entry.bind('<Return>', lambda event: self.filter_results())

        self.search_button = tk.Button(search_frame, text="Filtruj", bg="#2196F3", fg="white", 
                                       command=self.filter_results)
        self.search_button.pack(side=tk.LEFT)

        # Etykieta głównych statystyk
        self.stats_label = tk.Label(self.root, text="Brak danych", 
                                    font=("Arial", 12, "bold"), fg="#D32F2F")
        self.stats_label.pack(pady=5)

        # --- LISTA WYNIKÓW Z PASKAMI PRZEWIJANIA ---
        list_frame = tk.Frame(self.root)
        list_frame.pack(fill=tk.BOTH, expand=True, **main_padding)

        self.v_scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.h_scrollbar = tk.Scrollbar(list_frame, orient=tk.HORIZONTAL)
        self.h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        self.file_listbox = tk.Listbox(list_frame, 
                                       yscrollcommand=self.v_scrollbar.set, 
                                       xscrollcommand=self.h_scrollbar.set,
                                       font=("Consolas", 11))
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.v_scrollbar.config(command=self.file_listbox.yview)
        self.h_scrollbar.config(command=self.file_listbox.xview)

    def extract_ids(self, filename):
        """Wyciąga ID osoby (pierwsza liczba) i ID zdania (druga liczba)."""
        match = re.search(r'^(\d+)_(\d+)', filename)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None, None

    def start_fetching(self):
        """Inicjuje połączenie SSH w osobnym wątku."""
        self.fetch_button.config(state=tk.DISABLED, text="Łączenie...")
        self.status_label.config(text="Komunikacja z serwerem SSH...")
        self.file_listbox.delete(0, tk.END)
        
        thread = threading.Thread(target=self.fetch_ssh_data)
        thread.daemon = True
        thread.start()

    def fetch_ssh_data(self):
        """Pobiera pliki i zapisuje do pamięci."""
        if not all([hostname, username, password, pjm_directory]):
            self.root.after(0, self.show_error, "Błąd: Sprawdź plik .env")
            return

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname, username=username, password=password)
            
            stdin, stdout, stderr = client.exec_command(f'ls -1 {pjm_directory}')
            result = stdout.read().decode('utf-8')
            
            raw_files = result.splitlines()
            parsed_data = []

            for f in raw_files:
                if f.lower().endswith('.mp4'):
                    person_id, sentence_id = self.extract_ids(f)
                    if person_id is not None and sentence_id is not None:
                        parsed_data.append((person_id, f, sentence_id))
            
            self.all_files_data = parsed_data
            self.root.after(0, self.refresh_display)
            
        except Exception as e:
            self.root.after(0, self.show_error, str(e))
        finally:
            client.close()

    def refresh_display(self, filtered_list=None):
        """Grupuje zdania i osoby, a następnie odświeża listę."""
        self.file_listbox.delete(0, tk.END)
        
        data_to_show = filtered_list if filtered_list is not None else self.all_files_data
        
        # --- GRUPOWANIE DANYCH ---
        # Używamy defaultdict, aby automatycznie tworzyć listy dla nowych ID zdań
        sentence_records = defaultdict(list)
        
        for item in data_to_show:
            person_id, full_name, sentence_id = item
            sentence_records[sentence_id].append(person_id)
        
        # Sortujemy wyniki po ID zdania rosnąco i układamy tekst do wyświetlenia
        for sentence_id in sorted(sentence_records.keys()):
            persons_list = sentence_records[sentence_id]
            count = len(persons_list)
            
            # Sortujemy ID osób, żeby ładnie wyglądały (np. 10, 12, 15)
            # Zmieniamy liczby na tekst (str), żeby móc połączyć je przecinkami
            persons_str = ", ".join(map(str, sorted(persons_list)))
            
            # Formatuje wiersz na liście
            row_text = f"Zdanie ID: {sentence_id:<6} | Nagrań: {count:<3} | ID Osób: [{persons_str}]"
            self.file_listbox.insert(tk.END, row_text)
        
        # --- AKTUALIZACJA STATYSTYK ---
        total_files = len(data_to_show)
        unique_sentences = len(sentence_records)
        
        self.stats_label.config(text=f"Łącznie nagrań: {total_files} | Różnych zdań: {unique_sentences}")
        self.status_label.config(text=f"Wszystkich plików MP4 na serwerze: {len(self.all_files_data)}")
        self.fetch_button.config(state=tk.NORMAL, text="Odśwież dane z serwera")

    def filter_results(self):
        """Filtruje dane wg ID osoby i przelicza na nowo."""
        query = self.search_var.get().strip()
        
        if not query:
            self.refresh_display()
            return

        filtered = [item for item in self.all_files_data if str(item[0]).startswith(query)]
        self.refresh_display(filtered)

    def show_error(self, msg):
        messagebox.showerror("Błąd SSH", msg)
        self.fetch_button.config(state=tk.NORMAL, text="Spróbuj ponownie")

if __name__ == "__main__":
    root = tk.Tk()
    app = SSHFileApp(root)
    root.mainloop()
