"""Deterministic admission policy for local inference. Pure functions over a resources.snapshot(); no model involved.

Levels (from the owner's starting thresholds, config.json):
  normal   < caution_pct          admit
  caution  caution_pct..restrict  admit (logged)
  restrict > restrict_pct          hold new local inference in the queue until it clears or times out
  block    VRAM > vram_block_pct or RAM > ram_block_pct, LM Studio unreachable, or the game is running
           (game_blocks_inference): reject / hold new local inference

VRAM adjustment (documented in docs/ai/decisions.md): a loaded model permanently holds most of the 12 GB, so with
a model resident, VRAM counts against the restrict level only above vram_restrict_with_model_pct. Requests reuse the
model's pre-allocated context; they don't load more weights.
"""

DEFAULTS = {
    "max_concurrent_local": 1,
    "caution_pct": 70, "restrict_pct": 85,
    "vram_block_pct": 95, "ram_block_pct": 90,
    "vram_restrict_with_model_pct": 92,
    "game_blocks_inference": True,
    "game_process_prefixes": ["starfield", "fallout4"],
    "queue_wait_s": 600, "request_timeout_s": 900,
}


def level(snap, cfg):
    """(level, [reasons]) for admitting new local inference."""
    reasons, lv = [], "normal"
    order = ["normal", "caution", "restrict", "block"]

    def bump(new, why):
        nonlocal lv
        reasons.append(why)
        if order.index(new) > order.index(lv):
            lv = new

    lm = snap.get("lmstudio", {})
    if not lm.get("reachable"):
        bump("block", "LM Studio server not reachable")
    model_loaded = bool(lm.get("loaded"))
    ram_pct = snap.get("ram", {}).get("used_pct", 0.0)
    g = snap.get("gpu", {})
    vram_pct = g.get("vram_pct") if g.get("available") else None

    if ram_pct > cfg["ram_block_pct"]:
        bump("block", f"RAM {ram_pct}% > {cfg['ram_block_pct']}%")
    elif ram_pct > cfg["restrict_pct"]:
        bump("restrict", f"RAM {ram_pct}% > {cfg['restrict_pct']}%")
    elif ram_pct >= cfg["caution_pct"]:
        bump("caution", f"RAM {ram_pct}% >= {cfg['caution_pct']}%")

    if vram_pct is not None:
        restrict_at = cfg["vram_restrict_with_model_pct"] if model_loaded else cfg["restrict_pct"]
        if vram_pct > cfg["vram_block_pct"]:
            bump("block", f"VRAM {vram_pct}% > {cfg['vram_block_pct']}%")
        elif vram_pct > restrict_at:
            bump("restrict", f"VRAM {vram_pct}% > {restrict_at}%" + (" (model resident)" if model_loaded else ""))
        elif vram_pct >= cfg["caution_pct"] and not model_loaded:
            bump("caution", f"VRAM {vram_pct}% >= {cfg['caution_pct']}%")
    else:
        reasons.append("GPU not measurable: VRAM not checked")

    if cfg.get("game_blocks_inference"):
        procs = snap.get("agents", {}).get("processes", {})
        running = [n for n in procs if any(n.lower().startswith(p) for p in cfg["game_process_prefixes"])]
        if running:
            bump("block", f"game running ({', '.join(running)}): GPU reserved for game tests")
    return lv, reasons


def admit(snap, cfg, running_jobs):
    """Decision for one new local inference request: ("admit" | "queue" | "reject", level, reasons)."""
    lv, reasons = level(snap, cfg)
    if running_jobs >= cfg["max_concurrent_local"]:
        return "queue", lv, reasons + [f"{running_jobs} running >= max {cfg['max_concurrent_local']}"]
    if lv in ("normal", "caution"):
        return "admit", lv, reasons
    return "queue", lv, reasons                        # restrict / block: wait for recovery (bounded by queue_wait_s)
