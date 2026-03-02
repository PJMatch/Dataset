import pandas as pd
from collections import Counter
import stanza

print("Loading the Polish language model (Stanza)...")
stanza.download('pl', processors='tokenize,pos,lemma')
nlp = stanza.Pipeline('pl', processors='tokenize,pos,lemma', use_gpu=False)

JUNK_WORDS = {"em", "eś", "śmy", "ście", "m", "ś"}
STOP_WORDS = {"i", "w", "z", "na", "do", "o", "a", "że", "to", "czy", "jak", "co", "nie", "się"}


def count_words_with_stanza_from_csv(file_path):
    word_counter = Counter()

    try:
        df = pd.read_csv(file_path, sep=';', header=None, encoding='utf-8')

        texts = df[0].dropna()

        print(f"Starting analysis of {len(texts)} sentences. This will take a few seconds...")

        for text in texts:
            document = nlp(str(text).lower())

            lemmas = []

            for sentence in document.sentences:
                for word in sentence.words:
                    lemma = word.lemma

                    if lemma and lemma.isalpha():
                        if lemma not in JUNK_WORDS and word.text not in JUNK_WORDS:
                            lemmas.append(lemma)

            word_counter.update(lemmas)

        return word_counter

    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
        return None


input_file = "Sentences.csv" 
results = count_words_with_stanza_from_csv(input_file)

if results:
    print("\nDone! Here are the Top 100 most popular words:")
    print("-" * 50)
    for base_word, count in results.most_common(100):
        print(f"Word '{base_word:<15}' : {count} times")

    df_results = pd.DataFrame(results.most_common(), columns=["Word (Lemma)", "Count"])
    output_filename = "occurrence_results.xlsx"
    df_results.to_excel(output_filename, index=False)
    print(f"\nThe full summary has been saved to the file: {output_filename}")