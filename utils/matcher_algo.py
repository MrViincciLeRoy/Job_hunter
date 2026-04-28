# utils/matcher_algo.py
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

_model = None

def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model

def build_cv_text(cv_data: dict) -> str:
    return " ".join(filter(None, [
        " ".join(cv_data.get("skills", [])),
        " ".join(cv_data.get("experience", [])),
        cv_data.get("summary", ""),
    ]))

def batch_match(cv_data: dict, jobs: list[dict], tfidf_weight=0.4, semantic_weight=0.6) -> list[int]:
    cv_text = build_cv_text(cv_data)
    job_texts = [f"{j.get('title','')} {j.get('description','')}" for j in jobs]

    # --- TF-IDF ---
    corpus = [cv_text] + job_texts
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
    tfidf_matrix = vectorizer.fit_transform(corpus)
    tfidf_scores = cosine_similarity(tfidf_matrix[0], tfidf_matrix[1:])[0]

    # --- Semantic ---
    model = _get_model()
    all_texts = [cv_text] + job_texts
    embeddings = model.encode(all_texts, batch_size=32, show_progress_bar=False)
    cv_emb = embeddings[0].reshape(1, -1)
    job_embs = embeddings[1:]
    semantic_scores = cosine_similarity(cv_emb, job_embs)[0]

    # --- Blend ---
    blended = (tfidf_weight * tfidf_scores) + (semantic_weight * semantic_scores)
    return [int(round(s * 100)) for s in blended]