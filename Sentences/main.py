"""
Script to generate excel report about number of lemma occurrences in the dataset
"""

import pandas as pd
from collections import defaultdict, Counter
import stanza

print("Loading Polish language model (Stanza)...")
nlp = stanza.Pipeline('pl', processors='tokenize,pos,lemma', use_gpu=False)

FILTER_OUT = {
    "i", "a", "oraz", "ale", "lecz", "bo", "że", "żeby", "aby", "więc", "czyli", "to",
    "w", "we", "z", "ze", "na", "do", "dla", "o", "od", "po", "przy", "nad", "pod", "przed", "za", "u", "bez",
    "się", "czy", "no", "niech", "by", "być", "zostać", "em", "eś", "śmy", "ście", "m", "ś"
}

SIGN_CORRECTIONS = {
    "dużo": "duży",
    "dobrze": "dobry",
    "szybko": "szybki",
    "zmęczyć": "zmęczony",
    "chora": "chory"
}


def generate_excel_report(input_file_path, output_file_name):
    """
    Generates an Excel report of top used lemmas in the dataset. Function filter out words which aren't used in PJM
    and make lemma correction

    Args:
        input_file_path (str): Path to input file with sentences in dataset
        output_file_name (str): Path to the output file where the results will be saved

    Return:
        none
    """
    overall_counter = Counter()
    predecessors = defaultdict(Counter)
    
    try:
        df = pd.read_csv(input_file_path, sep=';', header=None, encoding='utf-8')
        texts = df[0].dropna()
        
        for text in texts:
            doc = nlp(str(text).lower())
            for sentence in doc.sentences:
                previous_word = None
                for word in sentence.words:
                    lemma = word.lemma
                    if lemma and lemma.isalpha() and lemma not in FILTER_OUT and word.text not in FILTER_OUT:
                        if lemma in SIGN_CORRECTIONS:
                            lemma = SIGN_CORRECTIONS[lemma]

                        overall_counter[lemma] += 1

                        if previous_word:
                            predecessors[lemma][previous_word] += 1
                            
                        previous_word = lemma

        excel_rows = []

        for main_word, total_count in overall_counter.most_common():
            context_counter = predecessors[main_word]
            unique_predecessors_count = len(context_counter)

            if unique_predecessors_count > 0:
                context_text = ", ".join([f"{pred} ({count})" for pred, count in context_counter.most_common()])
            else:
                context_text = "None"

            excel_rows.append({
                "Word (Lemma)": main_word.upper(),
                "Total Occurrences": total_count,
                "Unique Predecessors": unique_predecessors_count,
                "Detailed Context (word and frequency)": context_text
            })

        output_df = pd.DataFrame(excel_rows)
        output_df.to_excel(output_file_name, index=False)
        
        print(f"Done! The report has been successfully saved to: {output_file_name}")
        
    except FileNotFoundError:
        print(f"Error: File '{input_file_path}' not found.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


input_csv = "Sentences.csv"
output_xlsx = "report.xlsx"

generate_excel_report(input_csv, output_xlsx)