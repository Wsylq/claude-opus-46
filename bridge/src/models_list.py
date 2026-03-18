"""Static model list for the /v1/models endpoint."""

STATIC_MODELS = [
    # Anthropic
    {"id": "claude-opus-4-6",            "owned_by": "anthropic"},
    {"id": "claude-opus-4-5-20251101",   "owned_by": "anthropic"},
    {"id": "claude-sonnet-4-5-20251101", "owned_by": "anthropic"},
    {"id": "claude-haiku-3-5-20241022",  "owned_by": "anthropic"},
    {"id": "claude-opus-4-20250514",     "owned_by": "anthropic"},
    {"id": "claude-sonnet-4-20250514",   "owned_by": "anthropic"},
    {"id": "claude-3-7-sonnet-20250219", "owned_by": "anthropic"},
    {"id": "claude-3-5-sonnet-20241022", "owned_by": "anthropic"},
    # OpenAI
    {"id": "gpt-5.3-codex",              "owned_by": "openai"},
    {"id": "gpt-4o",                     "owned_by": "openai"},
    {"id": "gpt-4o-mini",                "owned_by": "openai"},
    {"id": "gpt-4-turbo",                "owned_by": "openai"},
    {"id": "o3",                         "owned_by": "openai"},
    {"id": "o4-mini",                    "owned_by": "openai"},
    {"id": "o3-mini",                    "owned_by": "openai"},
    {"id": "o1",                         "owned_by": "openai"},
    # Google
    {"id": "gemini-2.5-pro-preview",     "owned_by": "google"},
    {"id": "gemini-2.5-flash-preview",   "owned_by": "google"},
    {"id": "gemini-2.0-flash",           "owned_by": "google"},
    {"id": "gemini-2.0-pro",             "owned_by": "google"},
    {"id": "gemini-1.5-pro",             "owned_by": "google"},
    {"id": "gemma-3-27b-it",             "owned_by": "google"},
    # Meta
    {"id": "llama-4-scout",              "owned_by": "meta"},
    {"id": "llama-4-maverick",           "owned_by": "meta"},
    {"id": "llama-3.3-70b-instruct",     "owned_by": "meta"},
    {"id": "llama-3.1-405b-instruct",    "owned_by": "meta"},
    # DeepSeek
    {"id": "deepseek-r1",                "owned_by": "deepseek"},
    {"id": "deepseek-v3",                "owned_by": "deepseek"},
    {"id": "deepseek-r2",                "owned_by": "deepseek"},
    # xAI
    {"id": "grok-3",                     "owned_by": "xai"},
    {"id": "grok-3-mini",                "owned_by": "xai"},
    # Mistral
    {"id": "mistral-large-2411",         "owned_by": "mistral"},
    {"id": "mistral-medium-3",           "owned_by": "mistral"},
    # Alibaba
    {"id": "qwen-2.5-72b-instruct",      "owned_by": "alibaba"},
    {"id": "qwen-3-235b",                "owned_by": "alibaba"},
    # Cohere
    {"id": "command-r-plus-08-2024",     "owned_by": "cohere"},
]


def get_models_response() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id":      m["id"],
                "object":  "model",
                "created": 1700000000,
                "owned_by": m["owned_by"],
            }
            for m in STATIC_MODELS
        ],
    }
