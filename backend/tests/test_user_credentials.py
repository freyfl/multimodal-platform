"""User-created model services must not inherit deployment credentials."""

import pytest

from app.errors import MissingConfigurationError
from app.services.embedding_service import EmbeddingService
from app.services.tag_service import TagService


@pytest.mark.parametrize("service_class", [EmbeddingService, TagService])
@pytest.mark.parametrize("user_settings", [{}, {"ark_api_key": None}, {"ark_api_key": ""}])
async def test_user_model_factory_rejects_missing_key(empty_settings, service_class, user_settings):
    config = empty_settings.model_copy(update={"ARK_API_KEY": "deployment-secret"})
    service = service_class.from_settings(user_settings, config=config)
    try:
        with pytest.raises(MissingConfigurationError):
            await service.check_connection()
        assert service._client._client is None
    finally:
        await service.aclose()
