import re

try:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False

_model = None


def _get_model():
    global _model
    if not ST_AVAILABLE:
        return None
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _flatten(items):
    parts = []
    for item in items:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            parts.append(" ".join(str(v) for v in item.values() if v))
    return " ".join(parts)


def build_cv_text(cv_data):
    return " ".join(filter(None, [
        _flatten(cv_data.get("skills", [])),
        _flatten(cv_data.get("experience", [])),
        cv_data.get("summary", "") or "",
    ]))


def batch_match(cv_data, jobs, tfidf_weight=0.4, semantic_weight=0.6):
    if not SKLEARN_AVAILABLE:
        return [0] * len(jobs)

    cv_text = build_cv_text(cv_data)
    job_texts = [f"{j.get('title', '')} {j.get('description', '')}" for j in jobs]

    corpus = [cv_text] + job_texts
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
    tfidf_matrix = vectorizer.fit_transform(corpus)
    tfidf_scores = cosine_similarity(tfidf_matrix[0], tfidf_matrix[1:])[0]

    model = _get_model()
    if model is None or not ST_AVAILABLE:
        return [int(round(s * 100)) for s in tfidf_scores]

    embeddings = model.encode([cv_text] + job_texts, batch_size=32, show_progress_bar=False)
    semantic_scores = cosine_similarity(embeddings[0].reshape(1, -1), embeddings[1:])[0]

    blended = (tfidf_weight * tfidf_scores) + (semantic_weight * semantic_scores)
    return [int(round(s * 100)) for s in blended]