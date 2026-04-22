from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np


def normalize_embedding(vector: np.ndarray) -> np.ndarray:
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if norm == 0:
        raise ValueError("embedding 向量范数为 0，无法归一化")
    return arr / norm


@dataclass
class SearchHit:
    face_id: int
    similarity: float


class VectorSearchIndex:
    """
    向量索引封装：
    - backend=faiss / annoy / bruteforce
    - 不可用时自动回退到 bruteforce
    """

    def __init__(
        self,
        *,
        dim: int = 512,
        backend: str = "auto",
        annoy_trees: int = 20,
        candidate_multiplier: int = 8,
    ) -> None:
        self.dim = dim
        self.requested_backend = (backend or "auto").strip().lower()
        self.annoy_trees = max(2, int(annoy_trees))
        self.candidate_multiplier = max(1, int(candidate_multiplier))

        self.backend = "bruteforce"
        self._faiss = None
        self._annoy_cls = None
        self._choose_backend()

        self._embeddings: Dict[int, np.ndarray] = {}
        self._dirty = True

        self._ids = np.empty((0,), dtype=np.int64)
        self._matrix = np.empty((0, self.dim), dtype=np.float32)

        self._faiss_index = None
        self._annoy_index = None
        self._annoy_dense_to_face: List[int] = []

    def _choose_backend(self) -> None:
        if self.requested_backend in {"auto", "faiss"}:
            try:
                import faiss  # type: ignore

                self._faiss = faiss
                self.backend = "faiss"
                return
            except Exception:
                pass

        if self.requested_backend in {"auto", "annoy"}:
            try:
                from annoy import AnnoyIndex  # type: ignore

                self._annoy_cls = AnnoyIndex
                self.backend = "annoy"
                return
            except Exception:
                pass

        self.backend = "bruteforce"

    def clear(self) -> None:
        self._embeddings.clear()
        self._dirty = True
        self._ids = np.empty((0,), dtype=np.int64)
        self._matrix = np.empty((0, self.dim), dtype=np.float32)
        self._faiss_index = None
        self._annoy_index = None
        self._annoy_dense_to_face = []

    def rebuild(self, items: Iterable[Tuple[int, np.ndarray]]) -> None:
        self._embeddings = {
            int(face_id): normalize_embedding(embedding)
            for face_id, embedding in items
        }
        self._dirty = True
        self._faiss_index = None
        self._annoy_index = None
        self._annoy_dense_to_face = []

    def upsert(self, face_id: int, embedding: np.ndarray) -> None:
        self._embeddings[int(face_id)] = normalize_embedding(embedding)
        self._dirty = True
        self._faiss_index = None
        self._annoy_index = None
        self._annoy_dense_to_face = []

    def delete(self, face_id: int) -> None:
        self._embeddings.pop(int(face_id), None)
        self._dirty = True
        self._faiss_index = None
        self._annoy_index = None
        self._annoy_dense_to_face = []

    def __len__(self) -> int:
        return len(self._embeddings)

    def _ensure_bruteforce_matrix(self) -> None:
        if not self._dirty and self._ids.size == len(self._embeddings):
            return
        if not self._embeddings:
            self._ids = np.empty((0,), dtype=np.int64)
            self._matrix = np.empty((0, self.dim), dtype=np.float32)
            self._dirty = False
            return

        ordered = sorted(self._embeddings.items(), key=lambda item: item[0])
        self._ids = np.asarray([item[0] for item in ordered], dtype=np.int64)
        self._matrix = np.vstack([item[1] for item in ordered]).astype(np.float32)
        self._dirty = False

    def _ensure_faiss_index(self) -> None:
        self._ensure_bruteforce_matrix()
        if self._faiss is None:
            self.backend = "bruteforce"
            return

        if self._faiss_index is not None:
            return

        index = self._faiss.IndexFlatIP(self.dim)
        id_map = self._faiss.IndexIDMap2(index)
        if self._ids.size > 0:
            id_map.add_with_ids(self._matrix, self._ids)
        self._faiss_index = id_map

    def _ensure_annoy_index(self) -> None:
        self._ensure_bruteforce_matrix()
        if self._annoy_cls is None:
            self.backend = "bruteforce"
            return

        if self._annoy_index is not None:
            return

        index = self._annoy_cls(self.dim, "angular")
        self._annoy_dense_to_face = []
        for dense_id, (face_id, embedding) in enumerate(
            sorted(self._embeddings.items(), key=lambda item: item[0])
        ):
            index.add_item(dense_id, embedding.tolist())
            self._annoy_dense_to_face.append(face_id)
        if self._annoy_dense_to_face:
            index.build(self.annoy_trees)
        self._annoy_index = index

    def search(self, query_embedding: np.ndarray, top_k: int, threshold: float) -> List[SearchHit]:
        if top_k <= 0:
            return []
        if not self._embeddings:
            return []

        query = normalize_embedding(query_embedding)
        limit = min(top_k * self.candidate_multiplier, len(self._embeddings))
        limit = max(top_k, limit)

        if self.backend == "faiss":
            self._ensure_faiss_index()
            if self._faiss_index is not None and len(self._embeddings) > 0:
                scores, ids = self._faiss_index.search(query.reshape(1, -1), limit)
                hits: List[SearchHit] = []
                for score, face_id in zip(scores[0], ids[0]):
                    if face_id < 0:
                        continue
                    similarity = float(score)
                    if similarity >= threshold:
                        hits.append(SearchHit(face_id=int(face_id), similarity=similarity))
                hits.sort(key=lambda item: item.similarity, reverse=True)
                return hits[:top_k]

        if self.backend == "annoy":
            self._ensure_annoy_index()
            if self._annoy_index is not None and self._annoy_dense_to_face:
                dense_ids, distances = self._annoy_index.get_nns_by_vector(
                    query.tolist(),
                    limit,
                    include_distances=True,
                )
                hits = []
                for dense_id, distance in zip(dense_ids, distances):
                    if dense_id < 0 or dense_id >= len(self._annoy_dense_to_face):
                        continue
                    # Annoy angular distance for unit vectors:
                    # d^2 = 2 - 2*cos -> cos = 1 - d^2/2
                    similarity = float(1.0 - (distance * distance) / 2.0)
                    if similarity >= threshold:
                        hits.append(
                            SearchHit(
                                face_id=int(self._annoy_dense_to_face[dense_id]),
                                similarity=similarity,
                            )
                        )
                hits.sort(key=lambda item: item.similarity, reverse=True)
                return hits[:top_k]

        # bruteforce fallback
        self._ensure_bruteforce_matrix()
        if self._matrix.shape[0] == 0:
            return []
        sims = np.dot(self._matrix, query).astype(np.float32)
        order = np.argsort(-sims)
        hits = []
        for idx in order[:limit]:
            similarity = float(sims[idx])
            if similarity < threshold:
                continue
            hits.append(SearchHit(face_id=int(self._ids[idx]), similarity=similarity))
            if len(hits) >= top_k:
                break
        return hits

    def stats(self) -> Dict[str, int | str]:
        return {
            "backend": self.backend,
            "requested_backend": self.requested_backend,
            "size": len(self._embeddings),
            "dim": self.dim,
        }
