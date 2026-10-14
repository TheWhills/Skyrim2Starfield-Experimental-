"""Load the team's model in LM Studio with memory-lean settings (LM Studio Python SDK, `pip install --user lmstudio`).

  python load_model.py [--model qwen3-14b] [--context 16384]

`lms load` has no switch for memory mapping; with it on, LM Studio kept ~10.5 GB of system RAM for a model that sits
fully in VRAM (measured 2026-10-09), which pushed RAM to 88-90% and made the guardian hold every request. This loads
with tryMmap=False and keepModelInMemory=False, everything on the GPU, flash attention on. Run it only when no request
is running (`guardian.py status`): unloading cuts an active generation.
"""
import argparse
import json

import lmstudio as lms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3-14b")
    ap.add_argument("--context", type=int, default=32768)
    ap.add_argument("--kv", default="q8_0", help="K/V cache quantization (q8_0 halves the cache; 'f16' for none)")
    a = ap.parse_args()
    cfg = {"contextLength": a.context, "gpu": {"ratio": 1.0}, "tryMmap": False, "keepModelInMemory": False,
           "flashAttention": True}
    if a.kv != "f16":                    # V-cache quantization needs flash attention (on above)
        cfg["llamaKCacheQuantizationType"] = a.kv
        cfg["llamaVCacheQuantizationType"] = a.kv
    client = lms.get_default_client()
    for m in client.llm.list_loaded():
        if m.identifier == a.model:
            m.unload()
    model = client.llm.load_new_instance(a.model, a.model, config=cfg)
    print(json.dumps({"loaded": model.identifier, "config": cfg}))


if __name__ == "__main__":
    main()
