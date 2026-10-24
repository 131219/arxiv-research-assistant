import os

import jwt


class AuthenticationError(Exception):
    """Raised when an access token cannot be authenticated."""


def verify_cognito_access_token(token: str) -> dict:
    region = os.getenv("AWS_REGION", "us-east-1")
    user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
    app_client_id = os.getenv("COGNITO_APP_CLIENT_ID")

    if not user_pool_id or not app_client_id:
        raise RuntimeError("Cognito authentication is not configured.")

    issuer = (
        f"https://cognito-idp.{region}.amazonaws.com/"
        f"{user_pool_id}"
    )

    jwks_url = f"{issuer}/.well-known/jwks.json"

    jwks_client = jwt.PyJWKClient(jwks_url)

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={
                "verify_aud": False,
            },
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid access token.") from exc

    if claims.get("token_use") != "access":
        raise AuthenticationError("Invalid access token.")

    if claims.get("client_id") != app_client_id:
        raise AuthenticationError("Invalid access token.")

    return claims
