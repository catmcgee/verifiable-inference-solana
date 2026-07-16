"""bitnet.cpp runtime adapter.

bitnet.cpp is Microsoft's llama.cpp fork with i2_s ternary kernels; its
llama-server speaks the same HTTP protocol, so the adapter only differs in
which binary infra scripts launch. Kept as its own class so runtime-specific
divergence (tokenizer quirks, kernel warmup) has a home.
"""

from server.runtimes.llamacpp import LlamaCppRuntime


class BitnetCppRuntime(LlamaCppRuntime):
    pass
