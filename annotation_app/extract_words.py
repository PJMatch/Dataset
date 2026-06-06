import pandas as pd

data = pd.read_excel("../Sentences/word_pool.xlsx")
print(data)
all_words = data.stack()

print(all_words)

all_words.to_csv("word_pool.csv", index=False, header=False)
