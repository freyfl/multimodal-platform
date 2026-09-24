"""API modules are loaded explicitly by main, never by package import."""

__all__ = [
    "import_router", "search_router", "tags_router", "system_router", "tos_router",
    "auth_router", "user_router", "settings_router",
]
