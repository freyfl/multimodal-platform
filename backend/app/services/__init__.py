"""Lazy service exports: importing contracts never creates cloud clients."""

from importlib import import_module


_MODULES = {
    "TOSService": "tos_service",
    "EmbeddingService": "embedding_service",
    "TagService": "tag_service",
    "MilvusService": "milvus_service",
    "SearchService": "search_service",
}
__all__ = list(_MODULES)


def __getattr__(name):
    if name in _MODULES:
        return getattr(import_module(f"app.services.{_MODULES[name]}"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
