"""bitnet.cpp runtime adapter.

bitnet.cpp is Microsoft's llama.cpp fork with i2_s ternary kernels; its
llama-server speaks the same HTTP protocol, so the adapter only differs in
which binary infra scripts launch. Kept as its own class so runtime-specific
divergence (tokenizer quirks, kernel warmup) has a home.
"""

from server.runtimes.llamacpp import LlamaCppRuntime


# The public BitNet GGUF contains a malformed embedded template. This is the
# model publisher's tokenizer template, supplied per request so the model
# server process and measured weights remain unchanged.
BITNET_CHAT_TEMPLATE = """{% set loop_messages = messages %}
{% for message in loop_messages %}
{% set content = message['role'] | capitalize + ': ' + message['content'] | trim + '<|eot_id|>' %}
{{ content }}
{% endfor %}
{% if add_generation_prompt %}{{ 'Assistant: ' }}{% endif %}"""


class BitnetCppRuntime(LlamaCppRuntime):
    def _chat_payload(self, messages: list[dict], max_tokens: int) -> dict:
        payload = super()._chat_payload(messages, max_tokens)
        payload.update(
            {
                "chat_template": BITNET_CHAT_TEMPLATE,
                "temperature": 0.6,
                "top_p": 0.9,
                "repeat_penalty": 1.15,
                "stop": ["<|eot_id|>", "\nUser:", "\nHuman:"],
            }
        )
        return payload
