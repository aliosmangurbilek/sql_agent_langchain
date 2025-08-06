# core/db/embedder.py
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import logging
import math
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal

import sqlalchemy as sa
from filelock import FileLock
from langchain_huggingface import HuggingFaceEmbeddings

from .introspector import get_metadata

logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# Desteklenen vektör depoları
# ------------------------------------------------------------
try:
    from langchain_community.vectorstores import ScaNN  # noqa: N818
except ImportError:  # pragma: no cover
    ScaNN = None  # tip denetimi için
from langchain_community.vectorstores import FAISS

BackendT = Literal["faiss", "scann"]

# ------------------------------------------------------------
# Yardımcılar
# ------------------------------------------------------------

def _safe_score(raw: float | int) -> float | None:
    """NaN / sonsuz skorları JSON-uyumlu hâle getir."""
    try:
        f = float(raw)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None

def _patch_scann_asset_paths(index_root: Path) -> None:
    """ScaNN .pbtxt içindeki göreli asset_path değerlerini tam yola çevir."""
    pbtxt = index_root / "scann_assets.pbtxt"
    if not pbtxt.exists():
        return
    txt = pbtxt.read_text()
    txt = re.sub(
        r'asset_path: "([^"]+)"',
        lambda m: f'asset_path: "{(index_root / Path(m.group(1)).name).as_posix()}"',
        txt,
    )
    pbtxt.write_text(txt)

# ------------------------------------------------------------
# Ana sınıf
# ------------------------------------------------------------

class DBEmbedder:
    """
    Veritabanı şemasını HuggingFace embedding'ine gömer ve
    FAISS (✚ CPU-dostu) veya ScaNN (✚ hızlı, bazı ortamlarda dosya nazlı)
    ile benzerlik araması sunar.
    """

    def __init__(
        self,
        engine: sa.Engine,
        *,
        backend: BackendT = "faiss",
        db_name: str | None = None,
        store_dir: str | Path = "storage/vectors",
        embedding_model: str = "intfloat/e5-large-v2",
        force_rebuild: bool = False,
    ) -> None:
        if backend == "scann" and ScaNN is None:
            raise RuntimeError(
                "backend='scann' seçildi fakat *scann* paketi kurulu değil.\n"
                "pip install scann"
            )
        self.backend = backend

        raw = db_name or (engine.url.database or "default")
        self.db_name = re.sub(r"[^0-9A-Za-z_.-]", "_", raw)
        
        # Include embedding model in path to avoid dimension conflicts
        model_suffix = re.sub(r"[^0-9A-Za-z_.-]", "_", embedding_model.split("/")[-1])
        self.store_path = Path(store_dir) / f"{self.db_name}_{backend}_{model_suffix}"
        self._embeddings = HuggingFaceEmbeddings(model_name=embedding_model, encode_kwargs={"normalize_embeddings": True})
        self.engine = engine

        if force_rebuild:
            self.rebuild()

    # --------------------------------------------------------
    # İç helper’lar
    # --------------------------------------------------------
    def _vector_cls(self):
        return FAISS if self.backend == "faiss" else ScaNN  # type: ignore[misc]

    def _lock_path(self) -> Path:
        return self.store_path.with_suffix(".lock")

    def _load_local_vector(self, path: Path):
        """Vektör deposunu yerelden yüklemek için sarmalayıcı."""
        Vector = self._vector_cls()
        return Vector.load_local(
            str(path),
            self._embeddings,
            allow_dangerous_deserialization=True,
        )

    # --------------------------------------------------------
    # Depo oluştur / yükle
    # --------------------------------------------------------
    def ensure_store(self, *, force: bool = False):
        with FileLock(str(self._lock_path())):
            if self.store_path.exists() and not force:
                try:
                    return self._load_local_vector(self.store_path)
                except Exception as exc:
                    logger.warning("Bozuk indeks tespit edildi (%s) – yeniden inşa", exc)

            tmp = Path(tempfile.mkdtemp(dir=self.store_path.parent, prefix=f"{self.db_name}__"))
            try:
                store = self._build_store(tmp)
                if self.store_path.exists():
                    shutil.rmtree(self.store_path, ignore_errors=True)
                tmp.rename(self.store_path)
                logger.info("Yeni %s indeksi kaydedildi: %s", self.backend, self.store_path)
                return store
            finally:
                if tmp.exists():
                    shutil.rmtree(tmp, ignore_errors=True)

    # --------------------------------------------------------
    def _build_store(self, path: Path):
        logger.info("Şema embedding’i oluşturuluyor → %s (%s)", self.db_name, self.backend)

        meta = get_metadata(self.engine)
        by_table: Dict[str, List[str]] = {}
        for row in meta:
            by_table.setdefault(row["table"], []).append(f"{row['column']} ({row['data_type']})")

        docs = [f"passage: Table {t}: {', '.join(cols)}" for t, cols in by_table.items()]
        metas = [{"table": t} for t in by_table]
        Vector = self._vector_cls()
        store = Vector.from_texts(texts=docs, embedding=self._embeddings, metadatas=metas)
        store.save_local(str(path))

        if self.backend == "scann":
            _patch_scann_asset_paths(path / "index.scann")

        # bütünlük testi
        self._load_local_vector(path)
        return store

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------
    def similarity_search(self, query: str, k: int = 6) -> List[Dict[str, Any]]:
        store = self.ensure_store()
        query_text = f"query: {query}"
        
        try:
            if hasattr(store, "similarity_search_with_score"):
                hits = store.similarity_search_with_score(query_text, k=k)
            else:
                hits = [(doc, 0.0) for doc in store.similarity_search(query, k=k)]
        except Exception as exc:
            logger.warning("Vector search failed (%s), rebuilding store", exc)
            # Rebuild and try again
            store = self.ensure_store(force=True)
            if hasattr(store, "similarity_search_with_score"):
                hits = store.similarity_search_with_score(query_text, k=k)
            else:
                hits = [(doc, 0.0) for doc in store.similarity_search(query, k=k)]

        return [
            {
                "table": doc.metadata.get("table"),
                "score": _safe_score(score),
                "text": doc.page_content,
            }
            for doc, score in hits
        ]

    def rebuild(self) -> None:
        with FileLock(str(self._lock_path())):
            if self.store_path.exists():
                shutil.rmtree(self.store_path, ignore_errors=True)
        self.ensure_store(force=True)

    # --------------------------------------------------------
    # CLI
    # --------------------------------------------------------
    @staticmethod
    def _cli() -> None:  # pragma: no cover
        import argparse

        p = argparse.ArgumentParser(prog="db-embedder", description="DB schema embedder")
        p.add_argument("db_uri")
        p.add_argument("--backend", choices=["faiss", "scann"], default="faiss")
        p.add_argument("-k", "--topk", type=int, default=3)
        args = p.parse_args()

        eng = sa.create_engine(args.db_uri)
        emb = DBEmbedder(eng, backend=args.backend, force_rebuild=True)
        print(json.dumps(emb.similarity_search("customer rentals 2005", k=args.topk), indent=2))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DBEmbedder {self.db_name} ({self.backend})>"
