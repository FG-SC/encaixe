"""Embedding backends: fastembed (default, local ONNX), tfidf (automatic fallback), fake (tests).

Every backend returns float32, L2-normalized rows, so a dot product is a cosine. fastembed 0.8.1 returns
float64 non-normalized vectors for this model; we fix both here. Texts are short by construction (see
``app.embeddings.texts``); the model truncates at 128 tokens anyway.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from pathlib import Path
from typing import Protocol

import numpy as np

from app.config import RULES, get_settings
from app.textnorm import fold

log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    if m.ndim == 1:
        m = m[None, :]
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class FakeEmbedder:
    """Deterministic hashed bag of words (tests only): similar wording → similar vectors."""

    name = "fake"
    dim = 64

    def __init__(self) -> None:
        self._cache: dict[str, np.ndarray] = {}

    def _token_vec(self, token: str) -> np.ndarray:
        v = self._cache.get(token)
        if v is None:
            seed = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16)
            v = np.random.default_rng(seed).standard_normal(self.dim).astype(np.float32)
            self._cache[token] = v
        return v

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in re.findall(r"[a-z0-9#+.]{2,}", fold(t)):
                out[i] += self._token_vec(tok.strip("."))
        return _normalize(out)


class TfidfEmbedder:
    """Character n-gram TF-IDF + truncated SVD, fitted once on the corpus and persisted."""

    name = "tfidf"
    dim = 256

    def __init__(self, model_path: Path) -> None:
        self.model_path = model_path
        self._model: tuple | None = None

    def _load(self) -> tuple | None:
        if self._model is None and self.model_path.is_file():
            import joblib

            self._model = joblib.load(self.model_path)
        return self._model

    def fit(self, corpus: list[str]) -> None:
        import joblib
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        docs = [fold(t) for t in corpus if t.strip()] or ["vaga"]
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, max_features=60000)
        x = vec.fit_transform(docs)
        k = max(1, min(self.dim, x.shape[0] - 1, x.shape[1] - 1))
        svd = TruncatedSVD(n_components=k, random_state=RULES.projection.random_state)
        svd.fit(x)
        self._model = (vec, svd)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, self.model_path)

    def embed(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        if model is None:
            self.fit(texts)
            model = self._model
        assert model is not None
        vec, svd = model
        reduced = svd.transform(vec.transform([fold(t) for t in texts]))
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        out[:, : reduced.shape[1]] = reduced
        return _normalize(out)


class FastEmbedder:
    """fastembed (ONNX Runtime, no torch) with the multilingual MiniLM model, loaded lazily."""

    name = "fastembed"
    dim = RULES.embeddings.dim

    def __init__(self, cache_dir: Path, threads: int) -> None:
        self.cache_dir = cache_dir
        self.threads = threads
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from fastembed import TextEmbedding

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            marker = self.cache_dir / ".fastembed_ready"
            # The ONNX Runtime CPU arena keeps batch buffers forever: measured 815 MB peak with it,
            # 613 MB without it (load + 256 texts in batches of 32), so it is off (docs/DECISIONS.md).
            kwargs = {"cache_dir": str(self.cache_dir), "threads": self.threads, "enable_cpu_mem_arena": False}
            try:
                # After the first download, never call the Hugging Face API again.
                self._model = TextEmbedding(RULES.embeddings.model, local_files_only=marker.exists(), **kwargs)
            except Exception:
                if not marker.exists():
                    raise
                self._model = TextEmbedding(RULES.embeddings.model, **kwargs)
            marker.write_text("ok", encoding="utf-8")

    def embed(self, texts: list[str]) -> np.ndarray:
        self.load()
        assert self._model is not None
        rows = list(self._model.embed(texts, batch_size=RULES.embeddings.batch_size, parallel=None))
        return _normalize(np.vstack(rows)) if rows else np.zeros((0, self.dim), dtype=np.float32)


_embedder: Embedder | None = None
_status: dict[str, str | None] = {"requested": None, "active": None, "fallback_reason": None}
_lock = threading.Lock()


def get_embedder() -> Embedder:
    """The process-wide embedder. fastembed failures fall back to tfidf, logged and shown in the dev panel."""
    global _embedder
    if _embedder is not None:
        return _embedder
    with _lock:
        if _embedder is not None:
            return _embedder
        settings = get_settings()
        requested = settings.embeddings
        _status.update(requested=requested, fallback_reason=None)
        tfidf_path = settings.models_dir / "tfidf.joblib"
        if requested == "fake":
            emb: Embedder = FakeEmbedder()
        elif requested == "tfidf":
            emb = TfidfEmbedder(tfidf_path)
        else:
            fe = FastEmbedder(settings.models_dir, settings.embed_threads)
            try:
                fe.load()
                emb = fe
            except Exception as exc:  # no model, no network, ONNX error…
                reason = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("embeddings fallback to tfidf: %s", reason)
                _status["fallback_reason"] = reason
                emb = TfidfEmbedder(tfidf_path)
        _status["active"] = emb.name
        _embedder = emb
        return emb


def embedding_status() -> dict[str, str | None]:
    return dict(_status)


def space_id(embedder: Embedder | None = None) -> str:
    """Identifies the vector space; stored vectors from another space are recomputed."""
    e = embedder or get_embedder()
    return f"{e.name}:{e.dim}"


def embed_texts(texts: list[str], embedder: Embedder | None = None) -> np.ndarray:
    """Embed in batches of RULES.embeddings.batch_size (bounded peak RAM)."""
    e = embedder or get_embedder()
    if not texts:
        return np.zeros((0, e.dim), dtype=np.float32)
    bs = RULES.embeddings.batch_size
    return np.vstack([e.embed(texts[i : i + bs]) for i in range(0, len(texts), bs)])


def reset_caches() -> None:
    global _embedder
    with _lock:
        _embedder = None
        _status.update(requested=None, active=None, fallback_reason=None)
