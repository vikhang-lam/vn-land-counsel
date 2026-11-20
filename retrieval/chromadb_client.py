import os
import chromadb

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_DB_PATH = os.path.join(
    PROJECT_ROOT,
    "data",
    "retrieval_store",
    "chroma_db",
)
DEFAULT_COLLECTION_NAME = "vn_land_counsel_v2"


def get_database_path() -> str:
    """Use the production database unless an isolated experiment overrides it."""
    return os.path.abspath(os.getenv("CHROMA_DB_PATH", DEFAULT_DB_PATH))


def get_collection_name() -> str:
    return os.getenv("CHROMA_COLLECTION", DEFAULT_COLLECTION_NAME).strip() or DEFAULT_COLLECTION_NAME

def get_chroma_client():
    return chromadb.PersistentClient(path=get_database_path())

def get_collection():
    from retrieval.embedder import get_embedding_function

    client_db = get_chroma_client()
    emb_fn = get_embedding_function()
    try:
        collection = client_db.get_collection(name=get_collection_name(), embedding_function=emb_fn)
        return collection
    except Exception as e:
        print(f"❌ Lỗi kết nối ChromaDB: {e}. Vui lòng build collection trước.")
        return None


def get_readonly_collection():
    """Open metadata/document collection without loading an embedding model."""

    client_db = get_chroma_client()
    try:
        return client_db.get_collection(name=get_collection_name())
    except Exception as e:
        print(f"❌ Lỗi kết nối ChromaDB: {e}. Vui lòng build collection trước.")
        return None
