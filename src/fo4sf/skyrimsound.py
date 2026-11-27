"""Skyrim's placed ambient sounds (SOUN sound markers) as Starfield's own sound markers (make_skyrim_objects.py stage).

2026-11-26, owner (Whiterun): "waterfalls came out really good, but they do need sound". Skyrim does not give the
waterfall meshes a sound: the cities place sound markers beside them (verified, Whiterun's export: AMBWaterfallSmallLP
x2, AMBWaterfallSplatterSmall x5, AMBWaterfallRapidsSmall x8, AMBWaterfallRapidsMedium2D x1, the streams'
AMBWaterStream01 / 02 / SmallWhiterunLP x18, AMBWaterDrain01LP x3, AMBSewerGrateLP x1). Skyrim's sounds are not
Starfield sounds (Wwise events, not .wav / .xwm descriptors), so each one is placed as the vanilla Starfield sound
marker closest in kind (SOUND_MAP; the FormIDs verified in Starfield.esm with SfInspect `list SoundMarker`; what each
sounds like is unverified until heard in game). Sounds not in the map stay skipped (the tavern's crowd and the rest).

2026-11-27, owner: "its wayyy too loud". Skyrim places its small, short-range loops every 5-10 m (8 round the
Gildergreen's ring, 15 down the Plains District stream); Starfield's city water loops are made to be placed sparsely
and carry further, so 38 of them stacked. Starfield has no per-reference volume for a sound marker (the SoundMarker
record holds only its Wwise event, SfInspect `form`), so the markers are thinned instead: within SPACING_M of a kept
marker the others are dropped, the larger sound kept first (SOUND_MAP's order): 38 -> 9 for Whiterun.
"""
from typing import Dict, List, Optional, Tuple

from . import terrain_grid as tg

UNITS_PER_M = 70.0

# Skyrim SOUN EditorID -> (Starfield.esm SoundMarker FormID hex, its EditorID); the order is the keep order when thinning
# (larger sounds first).
SOUND_MAP: Dict[str, Tuple[str, str]] = {
    "AMBWaterfallSmallLP": ("234F7D", "AMB_TheWell_Waterfall_01"),
    "AMBWaterfallRapidsMedium2D": ("07BADA", "AMB_Ext_City_New_Atlantis_Water_B"),
    "AMBWaterfallSplatterSmall": ("234F7F", "AMB_TheWell_Waterfall_02"),
    "AMBWaterfallRapidsSmall": ("07BAD7", "AMB_Ext_City_New_Atlantis_Water_A"),
    "AMBWaterStream01WhiterunLP": ("07BADA", "AMB_Ext_City_New_Atlantis_Water_B"),
    "AMBWaterStream02WhiterunLP": ("07BB27", "AMB_Ext_City_New_Atlantis_Water_C"),
    "AMBWaterStreamSmallWhiterunLP": ("07BB2A", "AMB_Ext_City_New_Atlantis_Water_D"),
    "AMBWaterDrain01LP": ("1E2870", "AMBExtCityAkilaWaterSewerGrate_marker"),
    "AMBSewerGrateLP": ("1E2870", "AMBExtCityAkilaWaterSewerGrate_marker"),
}
EDID_SUFFIX = "_Sound"
SPACING_M = 20.0


def place(objects: dict, refs: List[dict], cell_min: int, cell_max: int, edid_prefix: str,
          sound_map: Optional[Dict[str, Tuple[str, str]]] = None, disabled: Optional[set] = None,
          spacing: float = SPACING_M) -> dict:
    """Append to objects one "vanilla" base per Starfield sound marker used and one reference per Skyrim sound marker
    whose SOUN is in sound_map (refs: exported references in the overlay's frame, game units; disabled: formkeys
    Skyrim starts disabled), skipping any within spacing metres of one already kept (sound_map's order first; 0 keeps
    all). Returns {"placed": {skyrim EditorID: n}, "outside": n, "disabled": n, "thinned": n, "placed_src": set}."""
    sound_map = SOUND_MAP if sound_map is None else sound_map
    disabled = disabled or set()
    rep = {"placed": {}, "outside": 0, "disabled": 0, "thinned": 0, "placed_src": set()}
    base_of = {}
    kept = []
    order = {k: i for i, k in enumerate(sound_map)}
    cand = sorted((r for r in refs if r.get("type") == "SoundMarker" and r.get("base_editor_id") in sound_map),
                  key=lambda r: order[r["base_editor_id"]])
    for r in cand:
        if r.get("type") != "SoundMarker" or r.get("base_editor_id") not in sound_map:
            continue
        if r.get("disabled") or r.get("formkey") in disabled:
            rep["disabled"] += 1
            continue
        form, sf_edid = sound_map[r["base_editor_id"]]
        pos = tuple(float(v) / UNITS_PER_M for v in r["pos"])
        cell = tg.sf_cell_of(pos[0], pos[1])
        if not (cell_min <= cell[0] <= cell_max and cell_min <= cell[1] <= cell_max):
            rep["outside"] += 1
            continue
        if spacing > 0 and any(sum((a - b) ** 2 for a, b in zip(pos, k)) <= spacing * spacing for k in kept):
            rep["thinned"] += 1
            continue
        kept.append(pos)
        if form not in base_of:
            base_of[form] = len(objects["bases"])
            objects["bases"].append({"edid": f"{edid_prefix}{sf_edid}{EDID_SUFFIX}", "vanilla": form, "model": "",
                                     "source": f"generated: vanilla sound marker {sf_edid}", "collision": "none"})
        objects["refs"].append({"src": r["formkey"], "base": base_of[form], "cell": list(cell),
                                "pos": [round(v, 5) for v in pos], "rot": [float(v) for v in r.get("rot") or (0, 0, 0)],
                                "scale": 1.0, "disabled": False})
        rep["placed"][r["base_editor_id"]] = rep["placed"].get(r["base_editor_id"], 0) + 1
        rep["placed_src"].add(r["formkey"])
    return rep
