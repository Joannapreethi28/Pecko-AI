"""Brain tier ladder (docs/CONTRACT.md tier table). Spine sends a number; Brain maps it here."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BrainTier:
    name: str
    model: Optional[str]      # GGUF file in models/; None = no LLM (T3 survival)
    family: str               # prompt template family (brain/prompt.py TEMPLATES)
    ctx: int
    n_predict: int
    threads: int
    threads_batch: int
    prefill: str              # "early" (stable + tentative_final) | "stable" | "off"
    max_sentences: int = 2
    router_threshold: float = 90.0


# Qwen3-0.6B everywhere until the bake-off (plan Task 9) picks T0/T1.
TIERS = {
    0: BrainTier("T0", "Qwen3-0.6B-Q4_K_M.gguf", "qwen3", 2048, 60, 1, 2, "early"),
    1: BrainTier("T1", "Qwen3-0.6B-Q4_K_M.gguf", "qwen3", 1024, 40, 1, 2, "stable"),
    2: BrainTier("T2", "Qwen3-0.6B-Q4_K_M.gguf", "qwen3", 512, 25, 1, 1, "off", router_threshold=85.0),
    3: BrainTier("T3", None, "qwen3", 0, 0, 0, 0, "off", router_threshold=85.0),
}
