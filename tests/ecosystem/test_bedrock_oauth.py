"""Regression tests for B2 (OAuth2 authorize URL) and B3 (Bedrock body format)."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# B3: Bedrock model-family body formatting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_id, expected_keys",
    [
        ("anthropic.claude-3-sonnet-20240229-v1:0", {"anthropic_version", "max_tokens", "messages"}),
        ("anthropic.claude-3-5-sonnet-20240620-v1:0", {"anthropic_version", "max_tokens", "messages"}),
        ("amazon.titan-text-express-v1", {"inputText", "textGenerationConfig"}),
        ("meta.llama3-70b-instruct-v1:0", {"prompt", "max_gen_len", "temperature", "top_p"}),
        ("ai21.j2-ultra-v1", {"prompt", "maxTokens", "temperature"}),
        ("cohere.command-r-v1:0", {"prompt", "max_tokens", "temperature"}),
        ("mistral.mistral-large-2402-v1:0", {"prompt", "max_tokens", "temperature"}),
    ],
)
def test_bedrock_body_shape_matches_model_family(model_id: str, expected_keys: set[str]) -> None:
    from yagura_tools.aws import _bedrock_body_for

    body = _bedrock_body_for(model_id, "hello world", {})
    assert expected_keys.issubset(set(body.keys())), (
        f"Bedrock body for {model_id!r} missing keys {expected_keys - set(body.keys())}"
    )


def test_bedrock_claude_body_uses_messages() -> None:
    from yagura_tools.aws import _bedrock_body_for

    body = _bedrock_body_for("anthropic.claude-3-sonnet", "summarize this", {})
    assert body["messages"] == [{"role": "user", "content": "summarize this"}]
    assert body["anthropic_version"] == "bedrock-2023-05-31"


def test_bedrock_body_override_via_params() -> None:
    from yagura_tools.aws import _bedrock_body_for

    # Caller can override max_tokens for any family.
    body = _bedrock_body_for("anthropic.claude-3-sonnet", "hi", {"max_tokens": 50})
    assert body["max_tokens"] == 50

    body = _bedrock_body_for("amazon.titan-text-express-v1", "hi", {"max_tokens": 50})
    assert body["textGenerationConfig"]["maxTokenCount"] == 50


def test_bedrock_unknown_family_falls_back_to_generic() -> None:
    from yagura_tools.aws import _bedrock_body_for

    body = _bedrock_body_for("some-custom-model", "hello", {"custom": "value"})
    assert body == {"prompt": "hello", "custom": "value"}


@pytest.mark.parametrize(
    "model_id, response, expected",
    [
        # Claude on Bedrock returns {"content": [{"type": "text", "text": "..."}]}
        (
            "anthropic.claude-3-sonnet",
            {"content": [{"type": "text", "text": "hello from claude"}]},
            "hello from claude",
        ),
        # Titan: {"results": [{"outputText": "..."}]}
        (
            "amazon.titan-text-express-v1",
            {"results": [{"outputText": "hello from titan"}]},
            "hello from titan",
        ),
        # Llama: {"generation": "..."}
        (
            "meta.llama3-70b",
            {"generation": "hello from llama"},
            "hello from llama",
        ),
        # AI21: {"completions": [{"data": {"text": "..."}}]}
        (
            "ai21.j2-ultra-v1",
            {"completions": [{"data": {"text": "hello from ai21"}}]},
            "hello from ai21",
        ),
        # Cohere: {"generations": [{"text": "..."}]}
        (
            "cohere.command-r",
            {"generations": [{"text": "hello from cohere"}]},
            "hello from cohere",
        ),
        # Mistral: {"outputs": [{"text": "..."}]}
        (
            "mistral.mistral-large",
            {"outputs": [{"text": "hello from mistral"}]},
            "hello from mistral",
        ),
    ],
)
def test_bedrock_extract_text_per_family(model_id: str, response: dict, expected: str) -> None:
    from yagura_tools.aws import _bedrock_extract_text

    assert _bedrock_extract_text(model_id, response) == expected


# ---------------------------------------------------------------------------
# B2: OAuth2 authorize_url uses discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth2_authorize_url_uses_authorization_endpoint_from_discovery() -> None:
    from yagura_auth.oauth2 import OAuth2Provider

    provider = OAuth2Provider(
        issuer="https://accounts.google.com",
        client_id="client-abc",
    )
    # Inject discovery metadata so the test doesn't hit the network.
    provider._metadata = {
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    }

    result = await provider.build_authorize_url(
        redirect_uri="https://app.example.com/cb",
        state="fixed-state",
        use_pkce=True,
    )
    assert result["url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=client-abc" in result["url"]
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fcb" in result["url"]
    assert "response_type=code" in result["url"]
    assert "code_challenge=" in result["url"]
    assert "code_challenge_method=S256" in result["url"]
    assert result["state"] == "fixed-state"
    assert "code_verifier" in result


@pytest.mark.asyncio
async def test_oauth2_authorize_url_azure_ad() -> None:
    """Verify Azure AD's non-standard path is honored when returned by discovery."""
    from yagura_auth.oauth2 import OAuth2Provider

    provider = OAuth2Provider(
        issuer="https://login.microsoftonline.com/tenant-id/v2.0",
        client_id="azure-client",
    )
    provider._metadata = {
        "authorization_endpoint": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize",
        "token_endpoint": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token",
        "jwks_uri": "https://login.microsoftonline.com/tenant-id/discovery/v2.0/keys",
    }

    result = await provider.build_authorize_url(
        redirect_uri="https://app.example.com/cb",
        state="s1",
        use_pkce=False,
    )
    # The authorize URL must be built from the discovered endpoint, not the issuer.
    assert result["url"].startswith("https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize?")
    assert "code_challenge" not in result["url"]  # use_pkce=False


@pytest.mark.asyncio
async def test_oauth2_authorize_url_raises_when_discovery_missing_endpoint() -> None:
    from yagura_auth.oauth2 import OAuth2Provider

    provider = OAuth2Provider(issuer="https://example.com", client_id="c")
    provider._metadata = {"jwks_uri": "..."}  # authorization_endpoint missing

    with pytest.raises(RuntimeError):
        await provider.build_authorize_url(redirect_uri="https://app/cb")
