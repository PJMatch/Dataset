"""
Script to filter out every sentence which contain gloss not in the top N most used glosses in the dataset
"""

import pandas as pd
from collections import Counter
import stanza

print("Loading Polish language model (Stanza)...")
nlp = stanza.Pipeline('pl', processors='tokenize,pos,lemma', use_gpu=False)

NON_SIGNED = {
    "i", "a", "oraz", "ale", "lecz", "bo", "że", "żeby", "aby", "więc", "czyli", "to",
    "w", "we", "z", "ze", "na", "do", "dla", "o", "od", "po", "przy", "nad", "pod", "przed", "za", "u", "bez",
    "się", "czy", "no", "niech", "by", "być", "zostać","em", "eś", "śmy", "ście", "m", "ś"
}


def filter_for_pjm(input_path, output_path, top_n=100):
    """
    Generates an Excel report of sentences containing only the top N words in the dataset, filtering out words not used in PJM.

    Args:
        input_path (str): Path to input file with sentences in dataset
        output_path (str): Path to the output file where the results will be saved
        top_n (int): How many lemma we want in dataset

    Return:
        none
    """

    try:
        df = pd.read_csv(input_path, sep=';', header=None, encoding='utf-8')
        texts = df[0].dropna().tolist()
        print(f"Successfully loaded {len(texts)} sentences.")
    except Exception as e:
        print(f"File read error: {e}")
        return
    
    word_counter = Counter()
    sentences_with_lemmas = [] 
    
    print("\nExtracting signed words")
    for text in texts:
        doc = nlp(str(text).lower())
        lemmas_in_sentence = []
        
        for sentence in doc.sentences:
            for word in sentence.words:
                lemma = word.lemma

                if lemma and lemma.isalpha():
                    if lemma in NON_SIGNED or word.text in NON_SIGNED:
                        continue
                        
                    word_counter[lemma] += 1
                    lemmas_in_sentence.append(lemma)
        
        sentences_with_lemmas.append((text, lemmas_in_sentence))

    top_words = set([word for word, count in word_counter.most_common(top_n)])
    top_words.discard("zimno")
    
    print(f"Identified {len(word_counter)} unique PJM signs.")

    kept_sentences = []
    rejected_sentences = []
    
    for original_text, lemmas_in_sentence in sentences_with_lemmas:
        if not lemmas_in_sentence:
            continue

        if all(lemma in top_words for lemma in lemmas_in_sentence):
            kept_sentences.append(original_text)
        else:
            rejected_sentences.append(original_text)

    output_df = pd.DataFrame({"PJM Learning Sentences": kept_sentences})
    output_df.to_excel(output_path, index=False)
    
    print("\nPJM SUMMARY")
    print(f"Sentences analyzed : {len(texts)}")
    print(f"Sentences kept     : {len(kept_sentences)}")
    print(f"Sentences rejected : {len(rejected_sentences)}")
    print(f"Output file        : {output_path}")

    print("\nTop 20 most important signs:")
    for word, count in word_counter.most_common(20):
        print(f" {word} ({count} occurrences)")

input_file = "Sentences.csv"
output_file = "pjm_sentences_top100.xlsx"

filter_for_pjm(input_file, output_file, top_n=100)