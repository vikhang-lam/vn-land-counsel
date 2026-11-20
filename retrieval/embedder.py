import os
import gc
from time import perf_counter

import torch
from chromadb.utils import embedding_functions
from core.telemetry import record_counter, record_duration


_EMBEDDING_PARKED = False


def _target_device() -> str:
    default_device = "cuda" if torch.cuda.is_available() else "cpu"
    requested = os.getenv("EMBEDDING_DEVICE", default_device).strip().lower()
    return "cpu" if requested == "cuda" and not torch.cuda.is_available() else requested


def activate_embedding_models() -> int:
    """Move cached embedding models back to their configured device when retrieval resumes."""
    global _EMBEDDING_PARKED
    if not _EMBEDDING_PARKED:
        return 0
    target_device = _target_device()
    models = embedding_functions.SentenceTransformerEmbeddingFunction.models
    started = perf_counter()
    for model in models.values():
        model.to(target_device)
    _EMBEDDING_PARKED = False
    if models:
        record_counter("embedding_cpu_to_gpu")
        record_counter("embedding_models_activated", len(models))
        record_duration("embedding_cpu_to_gpu", perf_counter() - started)
    return len(models)


def get_embedding_function():
    activate_embedding_models()
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
        device=_target_device(),
        local_files_only=True,
    )


def park_embedding_models() -> int:
    """Move cached embedding models from VRAM to CPU RAM after retrieval."""
    global _EMBEDDING_PARKED
    models = embedding_functions.SentenceTransformerEmbeddingFunction.models
    model_count = len(models)
    if _EMBEDDING_PARKED:
        record_counter("resource_park_noop_count")
        return 0
    if model_count and torch.cuda.is_available():
        started = perf_counter()
        for model in models.values():
            model.to("cpu")
        _EMBEDDING_PARKED = True
        record_counter("embedding_gpu_to_cpu")
        record_counter("embedding_models_parked", model_count)
        record_duration("embedding_gpu_to_cpu", perf_counter() - started)
    else:
        record_counter("resource_park_noop_count")
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return model_count
