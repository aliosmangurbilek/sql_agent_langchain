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
        # Eğer vektör deposu varsa ve zorla yeniden oluşturma istenmemişse yüklemeyi dene
        if self.store_path.exists() and not force:
            try:
                logger.debug("Loading existing ScaNN index for %s", self.db_name)
                return ScaNN.load_local(str(self.store_path), self._embeddings, allow_dangerous_deserialization=True)
            except Exception as e:
                logger.warning(f"Error loading ScaNN index, rebuilding: {e}")
                # Yükleme başarısız olursa temizle ve yeniden oluştur
                self.rebuild()
                return self._build_store()
        
        # Vektör deposu yoksa veya zorla yeniden oluşturma istenmişse
        return self._build_store()
        
    def _build_store(self) -> ScaNN:
        """Veritabanı şeması için yeni bir ScaNN indeksi oluştur."""
        logger.info("Building ScaNN index for %s …", self.db_name)
        metadata = get_metadata(self.engine)

        tables: Dict[str, List[str]] = {}
        for row in metadata:
            tables.setdefault(row["table"], []).append(f"{row['column']} ({row['type']})")

        doc_texts = [f"Table {t}: {', '.join(cols)}" for t, cols in tables.items()]
        doc_meta  = [{"table": t} for t in tables]

        store = ScaNN.from_texts(
            texts=doc_texts,
            embedding=self._embeddings,
            metadatas=doc_meta
        )
        store.save_local(str(self.store_path))
        return store

    def similarity_search(self, query: str, k: int = 6) -> List[Dict[str, Any]]:
        try:
            store = self.ensure_store()
            if hasattr(store, "similarity_search_with_score"):
                hits = store.similarity_search_with_score(query, k=k)
            else:
                hits = [(doc, 0.0) for doc in store.similarity_search(query, k=k)]

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
            store = self.ensure_store(force=True)
            if hasattr(store, "similarity_search_with_score"):
                hits = store.similarity_search_with_score(query, k=k)
            else:
                hits = [(doc, 0.0) for doc in store.similarity_search(query, k=k)]

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
        # Önce eski vektör deposunu temizle
        if self.store_path.exists():
            logger.info(f"Removing existing vector store at {self.store_path}")
            shutil.rmtree(self.store_path, ignore_errors=True)
        
        # İlgili dizinin var olduğundan emin ol
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Yeni vektör deposu oluştur
        self._build_store()  # ensure_store yerine doğrudan _build_store çağır
        logger.info(f"Vector store rebuilt successfully for {self.db_name}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m core.db.embedder <DB_URI>")
    uri = sys.argv[1]
    eng = sa.create_engine(uri)
    emb = DBEmbedder(eng)
    emb.rebuild()
    print(json.dumps(emb.similarity_search("customer rentals 2005", k=3), indent=2))
