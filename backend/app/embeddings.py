"""
Embedding + similarity search utilities.

THEORY (see chat for the fuller explanation) -- short version:
  text -> vector (a point in ~384-dimensional "meaning space")
  similarity(a, b) = cosine of the angle between their vectors
  FAISS = a fast index over many vectors so "find the closest match" is quick

We use `all-MiniLM-L6-v2`: a small, fast, well-tested sentence embedding
model that runs locally (no API cost, no network call per embedding) --
good enough quality for short resume/JD phrases, and free to run as often
as you want during development.
"""
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

_model = None


def get_model() -> SentenceTransformer:
    """Lazy-load the model once per process -- loading it is slow (~1-2s),
    embedding individual texts afterward is fast (~ms)."""
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True)
    # normalize_embeddings=True scales every vector to length 1. Once vectors
    # are unit-length, cosine similarity becomes a plain dot product -- which
    # is exactly what faiss.IndexFlatIP ("inner product") computes for us.
    return np.asarray(vectors, dtype="float32")


class BulletIndex:
    """A FAISS index over a resume's bullet texts, so we can query
    'what's the closest resume bullet to this JD requirement?' quickly."""

    def __init__(self, bullets: list[str]):
        self.bullets = bullets
        vectors = embed_texts(bullets)
        dim = vectors.shape[1]
        self.index = faiss.IndexFlatIP(dim)  # IP = inner product = cosine sim, given unit vectors
        self.index.add(vectors)

    def closest(self, query_text: str, k: int = 1) -> list[tuple[str, float]]:
        """Returns up to k (bullet_text, similarity_score) pairs, best first."""
        if not self.bullets:
            return []
        query_vec = embed_texts([query_text])
        scores, indices = self.index.search(query_vec, min(k, len(self.bullets)))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            results.append((self.bullets[idx], float(score)))
        return results
