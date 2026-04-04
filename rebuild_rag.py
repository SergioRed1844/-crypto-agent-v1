import json
import pickle
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer

rag_dir = Path("rag")
chunks_file = rag_dir / "chunks_metadata.json"
vectorizer_file = rag_dir / "tfidf_vectorizer.pkl"
matrix_file = rag_dir / "tfidf_matrix.pkl"

with open(chunks_file, "r", encoding="utf-8") as f:
    chunks = json.load(f)

texts = []
for ch in chunks:
    if isinstance(ch, dict):
        text = ch.get("text", "")
    else:
        text = str(ch)
    texts.append(text)

vectorizer = TfidfVectorizer(
    max_features=5000,
    stop_words=None,
    ngram_range=(1, 2)
)

tfidf_matrix = vectorizer.fit_transform(texts)

with open(vectorizer_file, "wb") as f:
    pickle.dump(vectorizer, f)

with open(matrix_file, "wb") as f:
    pickle.dump(tfidf_matrix, f)

print("OK: TF-IDF reconstruido")
print("Chunks:", len(texts))
print("Vocab size:", len(vectorizer.vocabulary_))
