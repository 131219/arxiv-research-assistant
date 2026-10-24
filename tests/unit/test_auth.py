from unittest.mock import MagicMock, patch

import pytest

from arxiv_pipeline.api.auth import (
    AuthenticationError,
    verify_cognito_access_token,
)


def test_verify_cognito_access_token_accepts_valid_access_token(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv(
        "COGNITO_USER_POOL_ID",
        "us-east-1_testpool",
    )
    monkeypatch.setenv(
        "COGNITO_APP_CLIENT_ID",
        "website-client-123",
    )

    signing_key = MagicMock()
    signing_key.key = "public-key"

    jwks_client = MagicMock()
    jwks_client.get_signing_key_from_jwt.return_value = signing_key

    claims = {
        "sub": "user-123",
        "token_use": "access",
        "client_id": "website-client-123",
    }

    with patch(
        "arxiv_pipeline.api.auth.jwt.PyJWKClient",
        return_value=jwks_client,
    ), patch(
        "arxiv_pipeline.api.auth.jwt.decode",
        return_value=claims,
    ) as decode:
        result = verify_cognito_access_token("valid-token")

    assert result == claims

    jwks_client.get_signing_key_from_jwt.assert_called_once_with(
        "valid-token"
    )

    decode.assert_called_once()


def test_verify_cognito_access_token_rejects_id_token(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv(
        "COGNITO_USER_POOL_ID",
        "us-east-1_testpool",
    )
    monkeypatch.setenv(
        "COGNITO_APP_CLIENT_ID",
        "website-client-123",
    )

    signing_key = MagicMock()
    signing_key.key = "public-key"

    jwks_client = MagicMock()
    jwks_client.get_signing_key_from_jwt.return_value = signing_key

    claims = {
        "sub": "user-123",
        "token_use": "id",
        "client_id": "website-client-123",
    }

    with patch(
        "arxiv_pipeline.api.auth.jwt.PyJWKClient",
        return_value=jwks_client,
    ), patch(
        "arxiv_pipeline.api.auth.jwt.decode",
        return_value=claims,
    ):
        with pytest.raises(
            AuthenticationError,
            match="Invalid access token",
        ):
            verify_cognito_access_token("id-token")


def test_verify_cognito_access_token_rejects_wrong_app_client(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv(
        "COGNITO_USER_POOL_ID",
        "us-east-1_testpool",
    )
    monkeypatch.setenv(
        "COGNITO_APP_CLIENT_ID",
        "website-client-123",
    )

    signing_key = MagicMock()
    signing_key.key = "public-key"

    jwks_client = MagicMock()
    jwks_client.get_signing_key_from_jwt.return_value = signing_key

    claims = {
        "sub": "user-123",
        "token_use": "access",
        "client_id": "different-client-456",
    }

    with patch(
        "arxiv_pipeline.api.auth.jwt.PyJWKClient",
        return_value=jwks_client,
    ), patch(
        "arxiv_pipeline.api.auth.jwt.decode",
        return_value=claims,
    ):
        with pytest.raises(
            AuthenticationError,
            match="Invalid access token",
        ):
            verify_cognito_access_token("wrong-client-token")


def test_verify_cognito_access_token_rejects_invalid_or_expired_jwt(
    monkeypatch,
):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv(
        "COGNITO_USER_POOL_ID",
        "us-east-1_testpool",
    )
    monkeypatch.setenv(
        "COGNITO_APP_CLIENT_ID",
        "website-client-123",
    )

    signing_key = MagicMock()
    signing_key.key = "public-key"

    jwks_client = MagicMock()
    jwks_client.get_signing_key_from_jwt.return_value = signing_key

    with patch(
        "arxiv_pipeline.api.auth.jwt.PyJWKClient",
        return_value=jwks_client,
    ), patch(
        "arxiv_pipeline.api.auth.jwt.decode",
        side_effect=__import__("jwt").ExpiredSignatureError(
            "token expired"
        ),
    ):
        with pytest.raises(
            AuthenticationError,
            match="Invalid access token",
        ):
            verify_cognito_access_token("expired-token")
