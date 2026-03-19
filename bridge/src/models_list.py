"""Static model list for the /v1/models endpoint."""

STATIC_MODELS = [
    {"id": "claude-opus-4-6", "owned_by": "anthropic"},
    {"id": "claude-opus-4-5-20251101", "owned_by": "anthropic"},
    {"id": "claude-sonnet-4-6", "owned_by": "anthropic"},
    {"id": "gpt-5.3-codex", "owned_by": "openai"},
    {"id": "image generation", "owned_by": "arena"},
]


def get_models_response() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "created": 1700000000,
                "owned_by": m["owned_by"],
            }
            for m in STATIC_MODELS
        ],
    }
