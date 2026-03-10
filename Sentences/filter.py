import pandas as pd
from collections import Counter
import stanza

# 1. Load model
print("Loading Polish language model (Stanza)...")
# stanza.download('pl', processors='tokenize,pos,lemma')
nlp = stanza.Pipeline('pl', processors='tokenize,pos,lemma', use_gpu=False)

# 2. Dictionary of words omitted in PJM (Polish Sign Language)
# These words often don't have literal signs and result from spatial grammar
NON_SIGNED = {
    # Conjunctions
    "i", "a", "oraz", "ale", "lecz", "bo", "że", "żeby", "aby", "więc", "czyli", "to",
    # Prepositions
    "w", "we", "z", "ze", "na", "do", "dla", "o", "od", "po", "przy", "nad", "pod", "przed", "za", "u", "bez",
    # Particles, reflexive pronouns, and question markers often omitted/replaced by facial expression
    "się", "czy", "no", "niech", "by", 
    # Linking verbs (e.g., "I am hungry" -> in PJM: "I hungry")
    "być", "zostać",
    # Verb clitics (suffixes indicating person/tense in Polish)
    "em", "eś", "śmy", "ście", "m", "ś"
}

def filter_for_psl(input_path, output_path, top_n=100):
    try:
        df = pd.read_csv(input_path, sep=';', header=None, encoding='utf-8')
        texts = df[0].dropna().tolist()
        print(f"Successfully loaded {len(texts)} sentences.")
    except Exception as e:
        print(f"File read error: {e}")
        return
    
    word_counter = Counter()
    sentences_with_lemmas = [] 
    
    print("\nStage 1: Extracting signed words and building Top list...")
    for text in texts:
        doc = nlp(str(text).lower())
        lemmas_in_sentence = []
        
        for sentence in doc.sentences:
            for word in sentence.words:
                lemma = word.lemma
                
                # Consider only alphabetic words
                if lemma and lemma.isalpha():
                    # OMIT WORDS NOT USED IN PSL
                    if lemma in NON_SIGNED or word.text in NON_SIGNED:
                        continue # Skip to next word, this one is not relevant
                        
                    word_counter[lemma] += 1
                    lemmas_in_sentence.append(lemma)
        
        sentences_with_lemmas.append((text, lemmas_in_sentence))
        
    # Create a set of Top N most frequent SIGNED words
    top_words = set([word for word, count in word_counter.most_common(top_n)])
    top_words.discard("zimno") # Example of manual exclusion if needed
    
    print(f"Identified {len(word_counter)} unique PSL signs (after discarding prepositions and conjunctions).")
    
    print("\nStage 2: Verifying sentences...")
    kept_sentences = []
    rejected_sentences = []
    
    for original_text, lemmas_in_sentence in sentences_with_lemmas:
        # If the sentence is empty after removing "noise", reject it
        if not lemmas_in_sentence:
            continue
            
        # Check if all meaningful words in the sentence are within our Top N
        if all(lemma in top_words for lemma in lemmas_in_sentence):
            kept_sentences.append(original_text)
        else:
            rejected_sentences.append(original_text)
            
    # Save results
    output_df = pd.DataFrame({"PSL Learning Sentences (most frequent signs only)": kept_sentences})
    output_df.to_excel(output_path, index=False)
    
    print("\n--- PSL SUMMARY ---")
    print(f"Sentences analyzed : {len(texts)}")
    print(f"Sentences kept     : {len(kept_sentences)} (ideal for learning - based only on Top {top_n} signs)")
    print(f"Sentences rejected : {len(rejected_sentences)}")
    print(f"Output file        : {output_path}")
    
    # Print Top 20 for preview
    print("\nSample Top 20 most important signs in your file:")
    for word, count in word_counter.most_common(20):
        print(f" -> {word} ({count} occurrences)")

# --- EXECUTION ---
input_file = "Sentences.csv"
output_file = "psl_sentences_top100.xlsx"

# You can change top_n to e.g., 50 to filter out even more rare/difficult sentences
filter_for_psl(input_file, output_file, top_n=100)
