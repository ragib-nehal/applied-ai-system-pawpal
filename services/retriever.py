from __future__ import annotations

from pathlib import Path

from schemas import Citation, RetrievalRecordInput
from services.db import load_all_records, upsert_retrieval_records


class Retriever:
    """Local retriever with Chroma-first strategy and lexical fallback."""

    def __init__(self, chroma_dir: Path | None = None):
        self._chroma_dir = chroma_dir or (Path(__file__).resolve().parent.parent / "data" / "chroma")
        self._collection_name = "pawpal_pet_context"

    def ingest(self, records: list[RetrievalRecordInput]) -> None:
        upsert_retrieval_records(records)
        self._try_chroma_upsert(records)

    def retrieve(self, pet_name: str, query: str, top_k: int = 4) -> list[Citation]:
        chroma_hits = self._try_chroma_query(pet_name=pet_name, query=query, top_k=top_k)
        if chroma_hits:
            return chroma_hits
        return self._lexical_query(pet_name=pet_name, query=query, top_k=top_k)

    def _lexical_query(self, pet_name: str, query: str, top_k: int) -> list[Citation]:
        terms = {t.strip().lower() for t in query.split() if t.strip()}
        rows = [r for r in load_all_records() if r["pet_name"] == pet_name]
        scored: list[tuple[int, dict]] = []
        for row in rows:
            haystack = f"{row['section']} {row['content']}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            Citation(
                record_id=row["record_id"],
                section=row["section"],
                snippet=row["content"][:220],
                score=float(score),
            )
            for score, row in scored[:top_k]
        ]

    def _try_chroma_upsert(self, records: list[RetrievalRecordInput]) -> None:
        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except Exception:
            return
        if not records:
            return
        try:
            self._chroma_dir.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(self._chroma_dir))
            collection = client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=embedding_functions.OllamaEmbeddingFunction(
                    model_name="nomic-embed-text"
                ),
            )
            collection.upsert(
                ids=[r.record_id for r in records],
                documents=[r.content for r in records],
                metadatas=[{"pet_name": r.pet_name, "section": r.section} for r in records],
            )
        except Exception:
            return

    def _try_chroma_query(self, pet_name: str, query: str, top_k: int) -> list[Citation]:
        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except Exception:
            return []
        if not self._chroma_dir.exists():
            return []
        try:
            client = chromadb.PersistentClient(path=str(self._chroma_dir))
            collection = client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=embedding_functions.OllamaEmbeddingFunction(
                    model_name="nomic-embed-text"
                ),
            )
            result = collection.query(
                query_texts=[query],
                n_results=top_k,
                where={"pet_name": pet_name},
            )
        except Exception:
            return []
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0] if result.get("distances") else [None] * len(ids)
        citations: list[Citation] = []
        for idx, rid in enumerate(ids):
            section = metas[idx].get("section", "unknown")
            snippet = docs[idx][:220] if idx < len(docs) else ""
            score = None
            if idx < len(distances) and distances[idx] is not None:
                score = float(1.0 / (1.0 + distances[idx]))
            citations.append(
                Citation(
                    record_id=rid,
                    section=section,
                    snippet=snippet,
                    score=score,
                )
            )
        return citations