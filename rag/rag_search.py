
import json, pickle, numpy as np
from sklearn.metrics.pairwise import cosine_similarity

class RAGSearch:
    def __init__(self, rag_dir="./rag"):
        with open(f"{rag_dir}/tfidf_vectorizer.pkl", "rb") as f:
            self.vectorizer = pickle.load(f)
        with open(f"{rag_dir}/tfidf_matrix.pkl", "rb") as f:
            self.tfidf_matrix = pickle.load(f)
        with open(f"{rag_dir}/chunks_metadata.json", "r") as f:
            self.metadata = json.load(f)
    
    def search(self, query, k=5, min_score=0.05):
        """Search knowledge base. Returns top-k relevant chunks."""
        q_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self.tfidf_matrix).flatten()
        
        # Get top-k indices
        top_indices = scores.argsort()[-k:][::-1]
        
        results = []
        for idx in top_indices:
            score = scores[idx]
            if score < min_score:
                continue
            chunk = self.metadata[idx]
            results.append({
                "score": float(score),
                "chunk_id": chunk["chunk_id"],
                "doc_source": chunk["doc_source"],
                "section": chunk["section"],
                "subsection": chunk["subsection"],
                "tags": chunk["topic_tags"],
                "text": chunk["text"]
            })
        return results
    
    def build_context(self, query, k=5, max_tokens=2000):
        """Build context string for LLM prompt from top-k results."""
        results = self.search(query, k=k)
        context_parts = []
        total_words = 0
        
        for r in results:
            words = len(r["text"].split())
            if total_words + words > max_tokens:
                break
            context_parts.append(
                f"[Source: {r['doc_source']} | {r['section']}]\n{r['text']}"
            )
            total_words += words
        
        return "\n\n---\n\n".join(context_parts)

if __name__ == "__main__":
    rag = RAGSearch()
    
    # Test queries
    tests = [
        "What is the pre-trade checklist?",
        "How to size positions for memecoins?",
        "What are the kill switches?",
        "How does regime detection work?",
        "What is the MVRV Z-Score?"
    ]
    
    for q in tests:
        print(f"\nQuery: {q}")
        results = rag.search(q, k=3)
        for r in results:
            print(f"  Score: {r['score']:.4f} | {r['doc_source']} | {r['section'][:50]}")
