"""
AI Provider Registry — model catalogs and pricing for 12 providers.
"""

PROVIDERS = {
    "anthropic": {
        "name": "Anthropic",
        "sdk_type": "anthropic",
        "default_base_url": "https://api.anthropic.com",
        "docs_url": "https://docs.anthropic.com/",
        "models": [
            {
                "id": "claude-opus-4-20250514",
                "name": "Claude Opus 4",
                "context_window": 200000,
                "max_output": 32000,
                "input_price_per_million": 15.00,
                "output_price_per_million": 75.00,
            },
            {
                "id": "claude-sonnet-4-20250514",
                "name": "Claude Sonnet 4",
                "context_window": 200000,
                "max_output": 16000,
                "input_price_per_million": 3.00,
                "output_price_per_million": 15.00,
            },
            {
                "id": "claude-haiku-4-20250514",
                "name": "Claude Haiku 4",
                "context_window": 200000,
                "max_output": 8192,
                "input_price_per_million": 1.00,
                "output_price_per_million": 5.00,
            },
        ],
    },
    "openai": {
        "name": "OpenAI",
        "sdk_type": "openai_compatible",
        "default_base_url": "https://api.openai.com/v1",
        "docs_url": "https://platform.openai.com/docs",
        "models": [
            {
                "id": "gpt-4o",
                "name": "GPT-4o",
                "context_window": 128000,
                "max_output": 16384,
                "input_price_per_million": 2.50,
                "output_price_per_million": 10.00,
            },
            {
                "id": "gpt-4o-mini",
                "name": "GPT-4o Mini",
                "context_window": 128000,
                "max_output": 16384,
                "input_price_per_million": 0.15,
                "output_price_per_million": 0.60,
            },
            {
                "id": "gpt-4.1",
                "name": "GPT-4.1",
                "context_window": 1047576,
                "max_output": 32768,
                "input_price_per_million": 2.00,
                "output_price_per_million": 8.00,
            },
            {
                "id": "gpt-4.1-mini",
                "name": "GPT-4.1 Mini",
                "context_window": 1047576,
                "max_output": 32768,
                "input_price_per_million": 0.40,
                "output_price_per_million": 1.60,
            },
            {
                "id": "gpt-4.1-nano",
                "name": "GPT-4.1 Nano",
                "context_window": 1047576,
                "max_output": 32768,
                "input_price_per_million": 0.10,
                "output_price_per_million": 0.40,
            },
            {
                "id": "o3-mini",
                "name": "o3-mini",
                "context_window": 200000,
                "max_output": 100000,
                "input_price_per_million": 1.10,
                "output_price_per_million": 4.40,
            },
            {
                "id": "o4-mini",
                "name": "o4-mini",
                "context_window": 200000,
                "max_output": 100000,
                "input_price_per_million": 1.10,
                "output_price_per_million": 4.40,
            },
        ],
    },
    "deepseek": {
        "name": "DeepSeek",
        "sdk_type": "openai_compatible",
        "default_base_url": "https://api.deepseek.com/v1",
        "docs_url": "https://api-docs.deepseek.com/",
        "models": [
            {
                "id": "deepseek-chat",
                "name": "DeepSeek V3",
                "context_window": 64000,
                "max_output": 8192,
                "input_price_per_million": 0.27,
                "output_price_per_million": 1.10,
            },
            {
                "id": "deepseek-reasoner",
                "name": "DeepSeek R1",
                "context_window": 64000,
                "max_output": 8192,
                "input_price_per_million": 0.55,
                "output_price_per_million": 2.19,
            },
        ],
    },
    "zhipu": {
        "name": "智谱 AI (GLM)",
        "sdk_type": "openai_compatible",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "docs_url": "https://open.bigmodel.cn/dev/api",
        "models": [
            {
                "id": "glm-4-plus",
                "name": "GLM-4 Plus",
                "context_window": 128000,
                "max_output": 4096,
                "input_price_per_million": 0.70,
                "output_price_per_million": 0.70,
            },
            {
                "id": "glm-4-flash",
                "name": "GLM-4 Flash",
                "context_window": 128000,
                "max_output": 4096,
                "input_price_per_million": 0.01,
                "output_price_per_million": 0.01,
            },
            {
                "id": "glm-4-air",
                "name": "GLM-4 Air",
                "context_window": 128000,
                "max_output": 4096,
                "input_price_per_million": 0.14,
                "output_price_per_million": 0.14,
            },
            {
                "id": "glm-4-long",
                "name": "GLM-4 Long",
                "context_window": 1000000,
                "max_output": 4096,
                "input_price_per_million": 0.14,
                "output_price_per_million": 0.14,
            },
        ],
    },
    "moonshot": {
        "name": "月之暗面 (Kimi)",
        "sdk_type": "openai_compatible",
        "default_base_url": "https://api.moonshot.cn/v1",
        "docs_url": "https://platform.moonshot.cn/docs",
        "models": [
            {
                "id": "moonshot-v1-8k",
                "name": "Moonshot 8K",
                "context_window": 8000,
                "max_output": 4096,
                "input_price_per_million": 0.17,
                "output_price_per_million": 0.17,
            },
            {
                "id": "moonshot-v1-32k",
                "name": "Moonshot 32K",
                "context_window": 32000,
                "max_output": 4096,
                "input_price_per_million": 0.34,
                "output_price_per_million": 0.34,
            },
            {
                "id": "moonshot-v1-128k",
                "name": "Moonshot 128K",
                "context_window": 128000,
                "max_output": 4096,
                "input_price_per_million": 0.85,
                "output_price_per_million": 0.85,
            },
        ],
    },
    "qwen": {
        "name": "通义千问 (Qwen)",
        "sdk_type": "openai_compatible",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "docs_url": "https://help.aliyun.com/zh/model-studio/",
        "models": [
            {
                "id": "qwen-max",
                "name": "Qwen Max",
                "context_window": 32000,
                "max_output": 8192,
                "input_price_per_million": 2.80,
                "output_price_per_million": 11.20,
            },
            {
                "id": "qwen-plus",
                "name": "Qwen Plus",
                "context_window": 131072,
                "max_output": 8192,
                "input_price_per_million": 0.56,
                "output_price_per_million": 1.12,
            },
            {
                "id": "qwen-turbo",
                "name": "Qwen Turbo",
                "context_window": 131072,
                "max_output": 8192,
                "input_price_per_million": 0.05,
                "output_price_per_million": 0.14,
            },
            {
                "id": "qwen-long",
                "name": "Qwen Long",
                "context_window": 10000000,
                "max_output": 6000,
                "input_price_per_million": 0.07,
                "output_price_per_million": 0.28,
            },
        ],
    },
    "google": {
        "name": "Google Gemini",
        "sdk_type": "google",
        "default_base_url": "",
        "docs_url": "https://ai.google.dev/docs",
        "models": [
            {
                "id": "gemini-2.5-flash",
                "name": "Gemini 2.5 Flash",
                "context_window": 1048576,
                "max_output": 65536,
                "input_price_per_million": 0.15,
                "output_price_per_million": 0.60,
            },
            {
                "id": "gemini-2.5-pro",
                "name": "Gemini 2.5 Pro",
                "context_window": 1048576,
                "max_output": 65536,
                "input_price_per_million": 1.25,
                "output_price_per_million": 10.00,
            },
            {
                "id": "gemini-2.0-flash",
                "name": "Gemini 2.0 Flash",
                "context_window": 1048576,
                "max_output": 8192,
                "input_price_per_million": 0.10,
                "output_price_per_million": 0.40,
            },
            {
                "id": "gemini-2.0-flash-lite",
                "name": "Gemini 2.0 Flash Lite",
                "context_window": 1048576,
                "max_output": 8192,
                "input_price_per_million": 0.025,
                "output_price_per_million": 0.10,
            },
        ],
    },
    "groq": {
        "name": "Groq",
        "sdk_type": "openai_compatible",
        "default_base_url": "https://api.groq.com/openai/v1",
        "docs_url": "https://console.groq.com/docs",
        "models": [
            {
                "id": "llama-3.3-70b-versatile",
                "name": "Llama 3.3 70B",
                "context_window": 128000,
                "max_output": 32768,
                "input_price_per_million": 0.59,
                "output_price_per_million": 0.79,
            },
            {
                "id": "llama-3.1-8b-instant",
                "name": "Llama 3.1 8B",
                "context_window": 128000,
                "max_output": 8192,
                "input_price_per_million": 0.05,
                "output_price_per_million": 0.08,
            },
            {
                "id": "deepseek-r1-distill-llama-70b",
                "name": "DeepSeek R1 Distill 70B",
                "context_window": 128000,
                "max_output": 16384,
                "input_price_per_million": 0.75,
                "output_price_per_million": 0.99,
            },
        ],
    },
    "mistral": {
        "name": "Mistral AI",
        "sdk_type": "openai_compatible",
        "default_base_url": "https://api.mistral.ai/v1",
        "docs_url": "https://docs.mistral.ai/",
        "models": [
            {
                "id": "mistral-large-latest",
                "name": "Mistral Large",
                "context_window": 128000,
                "max_output": 8192,
                "input_price_per_million": 2.00,
                "output_price_per_million": 6.00,
            },
            {
                "id": "mistral-small-latest",
                "name": "Mistral Small",
                "context_window": 128000,
                "max_output": 8192,
                "input_price_per_million": 0.10,
                "output_price_per_million": 0.30,
            },
            {
                "id": "pixtral-large-latest",
                "name": "Pixtral Large (Multimodal)",
                "context_window": 128000,
                "max_output": 8192,
                "input_price_per_million": 2.00,
                "output_price_per_million": 6.00,
            },
        ],
    },
    "openrouter": {
        "name": "OpenRouter",
        "sdk_type": "openai_compatible",
        "default_base_url": "https://openrouter.ai/api/v1",
        "docs_url": "https://openrouter.ai/docs",
        "models": [
            {
                "id": "anthropic/claude-sonnet-4",
                "name": "Claude Sonnet 4 via OR",
                "context_window": 200000,
                "max_output": 16000,
                "input_price_per_million": 3.00,
                "output_price_per_million": 15.00,
            },
            {
                "id": "openai/gpt-4o",
                "name": "GPT-4o via OR",
                "context_window": 128000,
                "max_output": 16384,
                "input_price_per_million": 2.50,
                "output_price_per_million": 10.00,
            },
            {
                "id": "google/gemini-2.5-flash",
                "name": "Gemini 2.5 Flash via OR",
                "context_window": 1048576,
                "max_output": 65536,
                "input_price_per_million": 0.15,
                "output_price_per_million": 0.60,
            },
            {
                "id": "deepseek/deepseek-chat",
                "name": "DeepSeek V3 via OR",
                "context_window": 64000,
                "max_output": 8192,
                "input_price_per_million": 0.27,
                "output_price_per_million": 1.10,
            },
        ],
    },
    "siliconflow": {
        "name": "硅基流动",
        "sdk_type": "openai_compatible",
        "default_base_url": "https://api.siliconflow.cn/v1",
        "docs_url": "https://docs.siliconflow.cn/",
        "models": [
            {
                "id": "deepseek-ai/DeepSeek-V3",
                "name": "DeepSeek V3",
                "context_window": 64000,
                "max_output": 8192,
                "input_price_per_million": 0.18,
                "output_price_per_million": 0.18,
            },
            {
                "id": "Qwen/Qwen2.5-72B-Instruct",
                "name": "Qwen 2.5 72B",
                "context_window": 131072,
                "max_output": 8192,
                "input_price_per_million": 0.56,
                "output_price_per_million": 0.56,
            },
            {
                "id": "THUDM/glm-4-9b-chat",
                "name": "GLM-4 9B",
                "context_window": 128000,
                "max_output": 4096,
                "input_price_per_million": 0.00,
                "output_price_per_million": 0.00,
            },
        ],
    },
    "yi": {
        "name": "零一万物 (Yi)",
        "sdk_type": "openai_compatible",
        "default_base_url": "https://api.lingyiwanwu.com/v1",
        "docs_url": "https://platform.lingyiwanwu.com/docs",
        "models": [
            {
                "id": "yi-lightning",
                "name": "Yi Lightning",
                "context_window": 16000,
                "max_output": 4096,
                "input_price_per_million": 0.14,
                "output_price_per_million": 0.14,
            },
            {
                "id": "yi-large",
                "name": "Yi Large",
                "context_window": 32000,
                "max_output": 4096,
                "input_price_per_million": 2.80,
                "output_price_per_million": 2.80,
            },
            {
                "id": "yi-medium",
                "name": "Yi Medium",
                "context_window": 16000,
                "max_output": 4096,
                "input_price_per_million": 0.36,
                "output_price_per_million": 0.36,
            },
        ],
    },
    "custom": {
        "name": "自定义 / 第三方中转",
        "sdk_type": "openai_compatible",
        "default_base_url": "",
        "docs_url": "",
        "models": [
            {
                "id": "gpt-4o",
                "name": "GPT-4o",
                "context_window": 128000,
                "max_output": 16384,
                "input_price_per_million": 2.50,
                "output_price_per_million": 10.00,
            },
            {
                "id": "gemini-2.5-flash",
                "name": "Gemini 2.5 Flash",
                "context_window": 1048576,
                "max_output": 65536,
                "input_price_per_million": 0.15,
                "output_price_per_million": 0.60,
            },
            {
                "id": "deepseek-chat",
                "name": "DeepSeek V3",
                "context_window": 64000,
                "max_output": 8192,
                "input_price_per_million": 0.27,
                "output_price_per_million": 1.10,
            },
            {
                "id": "claude-sonnet-4-20250514",
                "name": "Claude Sonnet 4",
                "context_window": 200000,
                "max_output": 16000,
                "input_price_per_million": 3.00,
                "output_price_per_million": 15.00,
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_all_providers() -> list:
    return [
        {
            "id": pid,
            "name": p["name"],
            "sdk_type": p["sdk_type"],
            "default_base_url": p["default_base_url"],
            "docs_url": p["docs_url"],
            "models": p["models"],
        }
        for pid, p in PROVIDERS.items()
    ]


def get_provider(provider_id: str) -> dict | None:
    p = PROVIDERS.get(provider_id)
    if p is None:
        return None
    return {
        "id": provider_id,
        "name": p["name"],
        "sdk_type": p["sdk_type"],
        "default_base_url": p["default_base_url"],
        "docs_url": p["docs_url"],
        "models": p["models"],
    }


def get_sdk_type(provider_id: str) -> str:
    p = PROVIDERS.get(provider_id)
    if p is None:
        return "openai_compatible"
    return p["sdk_type"]


def get_default_base_url(provider_id: str) -> str:
    p = PROVIDERS.get(provider_id)
    if p is None:
        return ""
    return p["default_base_url"]


def get_models_for_provider(provider_id: str) -> list:
    p = PROVIDERS.get(provider_id)
    if p is None:
        return []
    return p["models"]


def estimate_cost(provider_id: str, model_id: str, input_tokens: int, output_tokens: int) -> float:
    models = get_models_for_provider(provider_id)
    for m in models:
        if m["id"] == model_id:
            input_cost = input_tokens * m["input_price_per_million"] / 1_000_000
            output_cost = output_tokens * m["output_price_per_million"] / 1_000_000
            return input_cost + output_cost
    # Fallback: $0.000003 per token (input + output combined)
    return (input_tokens + output_tokens) * 0.000003
