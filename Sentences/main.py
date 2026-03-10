import pandas as pd
from collections import defaultdict, Counter
import stanza

# 1. Load Model
print("Loading Polish language model (Stanza)...")
# stanza.download('pl', processors='tokenize,pos,lemma')
nlp = stanza.Pipeline('pl', processors='tokenize,pos,lemma', use_gpu=False)

# List of words to ignore (noise)
# These are typically omitted in Polish Sign Language (PJM) 
# or function as grammatical "glue" that doesn't have a direct sign.
FILTER_OUT = {
    # Conjunctions
    "i", "a", "oraz", "ale", "lecz", "bo", "że", "żeby", "aby", "więc", "czyli", "to",
    # Prepositions
    "w", "we", "z", "ze", "na", "do", "dla", "o", "od", "po", "przy", "nad", "pod", "przed", "za", "u", "bez",
    # Particles, reflexive pronouns, and question markers
    "się", "czy", "no", "niech", "by", 
    # Linking verbs (e.g., "to be", "to become")
    "być", "zostać",
    # Verb clitics (Polish specific person/tense markers)
    "em", "eś", "śmy", "ście", "m", "ś"
}

# Mapping words to merge them into a single parent concept (sign)
SIGN_CORRECTIONS = {
    "dużo": "duży",     # "much/many" maps to "big"
    "dobrze": "dobry",  # "well" maps to "good"
    "szybko": "szybki", # "fast (adv)" maps to "fast (adj)"
}

def generate_excel_report(input_file_path, output_file_name):
    overall_counter = Counter()
    predecessors = defaultdict(Counter)
    
    try:
        df = pd.read_csv(input_file_path, sep=';', header=None, encoding='utf-8')
        texts = df[0].dropna()
        
        print(f"Analyzing {len(texts)} sentences for occurrences and context...\n")
        
        for text in texts:
            doc = nlp(str(text).lower())
            
            for sentence in doc.sentences:
                previous_word = None
                
                for word in sentence.words:
                    lemma = word.lemma
                    
                    # Process only alphabetic words not in our ignore list
                    if lemma and lemma.isalpha() and lemma not in FILTER_OUT and word.text not in FILTER_OUT:
                        
                        # Apply sign corrections/merging
                        if lemma in SIGN_CORRECTIONS:
                            lemma = SIGN_CORRECTIONS[lemma]

                        # Global count
                        overall_counter[lemma] += 1
                        
                        # Context count (tracking what word came before)
                        if previous_word:
                            predecessors[lemma][previous_word] += 1
                            
                        previous_word = lemma
                        
        print("Preparing data for Excel file...")
        
        # --- EXPORT TO EXCEL ---
        excel_rows = []
        
        # Iterate through words, starting with the most frequent ones
        for main_word, total_count in overall_counter.most_common():
            context_counter = predecessors[main_word]
            unique_predecessors_count = len(context_counter)
            
            # Formatting context into a readable string for a single cell
            if unique_predecessors_count > 0:
                # Creates a list like: "old (5), new (3)"
                context_text = ", ".join([f"{pred} ({count})" for pred, count in context_counter.most_common()])
            else:
                context_text = "None (always at the start of a sentence)"
                
            # Add formatted row to the list
            excel_rows.append({
                "Word (Lemma)": main_word.upper(),
                "Total Occurrences": total_count,
                "Unique Predecessors": unique_predecessors_count,
                "Detailed Context (word and frequency)": context_text
            })
            
        # Create and save the .xlsx file
        output_df = pd.DataFrame(excel_rows)
        output_df.to_excel(output_file_name, index=False)
        
        print(f"Done! The report has been successfully saved to: {output_file_name}")
        
    except FileNotFoundError:
        print(f"Error: File '{input_file_path}' not found.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

# --- EXECUTION ---
input_csv = "Sentences.csv"
output_xlsx = "report.xlsx"

generate_excel_report(input_csv, output_xlsx)
