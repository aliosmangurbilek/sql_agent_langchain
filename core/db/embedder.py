"""core.db.embedder
~~~~~~~~~~~~~~~~~~
Veritabanı şemasını vektör uzayına gömer ve ScaNN ile arar.
"""

from __future__ import annotations
import json, logging
from pathlib import Path
from typing import List, Dict, Any

import sqlalchemy as sa
from langchain_community.vectorstores import ScaNN
# Correct import for HuggingFaceEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings

from .introspector import get_metadata

logger = logging.getLogger(__name__)


class DBEmbedder:
    """Veritabanı şeması için embedding + ScaNN arama katmanı."""

    def __init__(
        self,
        engine: sa.Engine,
        *,
        db_name: str | None = None,
        store_dir: str | Path = "storage/vectors",
        embedding_model: str = "sentence-transformers/all-mpnet-base-v2",
        force_rebuild: bool = False
    ) -> None:
        self.engine = engine
        self.db_name = db_name or (engine.url.database or "default")
        self.store_path = Path(store_dir) / f"{self.db_name}_scann"
        self._embeddings = HuggingFaceEmbeddings(model_name=embedding_model)
        
        # Vektörleri zorla yeniden oluşturma seçeneği
        if force_rebuild:
            self.rebuild()

    # ------------------------------------------------------------------ #

    def ensure_store(self, force: bool = False) -> ScaNN:
        logger.debug(f"ensure_store called for db: {self.db_name}, force={force}")
        # Eğer vektör deposu varsa ve zorla yeniden oluşturma istenmemişse yüklemeyi dene
        if self.store_path.exists() and not force:
            logger.debug(f"Vector store path exists: {self.store_path}")
            try:
                logger.debug("Loading existing ScaNN index for %s", self.db_name)
                store = ScaNN.load_local(str(self.store_path), self._embeddings, allow_dangerous_deserialization=True)
                logger.info(f"Loaded ScaNN index successfully for {self.db_name}")
                return store
            except Exception as e:
                logger.warning(f"Error loading ScaNN index, rebuilding: {e}")
                # Yükleme başarısız olursa temizle ve yeniden oluştur
                self.rebuild()
                logger.debug(f"Rebuilt vector store after load failure for {self.db_name}")
                return self._build_store()
        else:
            logger.debug(f"Vector store does not exist or force rebuild requested for {self.db_name}")
        # Vektör deposu yoksa veya zorla yeniden oluşturma istenmişse
        return self._build_store()

    def _build_store(self) -> ScaNN:
        """Veritabanı şeması için yeni bir ScaNN indeksi oluştur."""
        logger.info("Building ScaNN index for %s …", self.db_name)
        metadata = get_metadata(self.engine)
        logger.debug(f"Fetched metadata for {self.db_name}: {metadata}")

        tables: Dict[str, List[str]] = {}
        for row in metadata:
            tables.setdefault(row["table"], []).append(f"{row['column']} ({row['type']})")
        logger.debug(f"Tables dict for {self.db_name}: {tables}")

        doc_texts = [f"Table {t}: {', '.join(cols)}" for t, cols in tables.items()]
        doc_meta  = [{"table": t} for t in tables]
        logger.debug(f"doc_texts: {doc_texts}")
        logger.debug(f"doc_meta: {doc_meta}")

        store = ScaNN.from_texts(
            texts=doc_texts,
            embedding=self._embeddings,
            metadatas=doc_meta
        )
        logger.info(f"ScaNN index built for {self.db_name}, saving to {self.store_path}")
        store.save_local(str(self.store_path))
        logger.info(f"ScaNN index saved for {self.db_name}")
        return store

    def similarity_search(self, query: str, k: int = 6) -> List[Dict[str, Any]]:
        logger.debug(f"similarity_search called for db: {self.db_name}, query: {query}, k: {k}")
        try:
            store = self.ensure_store()
            logger.debug(f"Store loaded for similarity search on {self.db_name}")
            if hasattr(store, "similarity_search_with_score"):
                hits = store.similarity_search_with_score(query, k=k)
            else:
                hits = [(doc, 0.0) for doc in store.similarity_search(query, k=k)]
            logger.debug(f"Similarity search hits: {hits}")
            return [
                {
                    "table": doc.metadata["table"],
                    "score": score,
                    "text": doc.page_content,
                }
                for doc, score in hits
            ]
        except Exception as e:
            logger.error(f"Error during similarity search: {e}")
            # Hata durumunda yeniden indeks oluşturmayı dene
            logger.info("Rebuilding index and trying again...")
            self.rebuild()
            logger.debug(f"Rebuilt vector store after similarity search error for {self.db_name}")
            store = self.ensure_store(force=True)
            if hasattr(store, "similarity_search_with_score"):
                hits = store.similarity_search_with_score(query, k=k)
            else:
                hits = [(doc, 0.0) for doc in store.similarity_search(query, k=k)]
            logger.debug(f"Similarity search hits after rebuild: {hits}")
            return [
                {
                    "table": doc.metadata["table"],
                    "score": score,
                    "text": doc.page_content,
                }
                for doc, score in hits
            ]

    # ------------------------------------------------------------------ #

    def rebuild(self) -> None:
        """Vektör deposunu zorla yeniden oluştur."""
        import shutil
        logger.debug(f"rebuild called for db: {self.db_name}")
        # Önce eski vektör deposunu temizle
        if self.store_path.exists():
            logger.info(f"Removing existing vector store at {self.store_path}")
            shutil.rmtree(self.store_path, ignore_errors=True)
        else:
            logger.debug(f"No existing vector store to remove for {self.db_name}")
        # İlgili dizinin var olduğundan emin ol
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Vector store directory ensured for {self.db_name}")
        # Yeni vektör deposu oluştur
        self._build_store()  # ensure_store yerine doğrudan _build_store çağır
        logger.info(f"Vector store rebuilt successfully for {self.db_name}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m core.db.embedder <DB_URI>")
    uri = sys.argv[1]
    eng = sa.create_engine(uri)
    emb = DBEmbedder(eng, force_rebuild=True)
    emb.rebuild()
    print(json.dumps(emb.similarity_search("customer rentals 2005", k=3), indent=2))
