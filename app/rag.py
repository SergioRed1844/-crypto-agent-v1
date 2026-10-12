"""RAG sobre la metodología. Reusa los artefactos TF-IDF del v3 (rag/*.pkl, rag/chunks_metadata.json)."""
import json
import logging
import pickle

log = logging.getLogger("rag")


class RAG:
    def __init__(self, base="rag"):
        self.loaded = False
        try:
            from sklearn.metrics.pairwise import cosine_similarity
            self._cos = cosine_similarity
            with open(f"{base}/tfidf_vectorizer.pkl", "rb") as f:
                self.vec = pickle.load(f)
            with open(f"{base}/tfidf_matrix.pkl", "rb") as f:
                self.mat = pickle.load(f)
            with open(f"{base}/chunks_metadata.json") as f:
                self.meta = json.load(f)
            self.loaded = True
            log.info(f"RAG: {len(self.meta)} chunks")
        except Exception as e:
            log.warning(f"RAG no cargado ({e}); los agentes usarán solo las reglas fijas")

    def context(self, query: str, k: int = 4, max_words: int = 900) -> str:
        if not self.loaded:
            return ""
        s = self._cos(self.vec.transform([query]), self.mat).flatten()
        parts, n = [], 0
        for i in s.argsort()[-k:][::-1]:
            if s[i] < 0.03:
                continue
            t = self.meta[i]["text"]
            w = len(t.split())
            if n + w > max_words:
                break
            parts.append(f"[{self.meta[i].get('section', '')}] {t}")
            n += w
        return "\n---\n".join(parts)


rag = RAG()
