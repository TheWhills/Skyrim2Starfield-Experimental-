// S2SGrass core (game-independent, header-only): which ground cover each terrain texture of an overlay world grows.
// docs/re/ground-cover-density.md, route B (2026-11-24). Starfield.exe 1.16.244 builds an overlay's palette entries
// in FUN_1409a9570 (Address Library 58316): {u32 LTEX FormID +0x00, u32 GCVR FormID +0x04, ...}, stride 0x38; only
// entries whose LTEX is one of the planet's LDefault slot placeholders get a GCVR, every other one keeps 0, so a
// converted Skyrim texture grows nothing. FUN_1409a84d0 later looks up each entry's +0x04 by FormID and keeps it when
// the form is a GCVR. The SFSE side (sfse/grass) fills +0x04 for our textures right after FUN_1409a9570 returns.
#pragma once

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <istream>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace s2s::grass {

// "Plugin.esm:0A1B2C": a record named by its plugin and its FormID inside it (the low 24 bits; the load order adds
// the rest at run time).
struct FormRef {
    std::string plugin;
    std::uint32_t local = 0;
    bool operator==(const FormRef&) const = default;
};

struct Cover {
    FormRef ltex;      // the ground texture (LTEX) as the overlay's terrain names it
    FormRef gcvr;      // the ground cover it grows
    std::string note;  // the comment after ';' (the Skyrim texture's EditorID)
};

struct Settings {
    bool enabled = true;
    bool only_empty = true;    // write only entries that have no ground cover yet (keeps the vanilla slot covers)
    int log_level = 1;         // 0 errors, 1 one line per overlay, 2 every entry
    std::vector<Cover> covers;
    std::vector<std::string> errors;
};

inline std::string trim(const std::string& s) {
    const auto b = s.find_first_not_of(" \t\r\n");
    if (b == std::string::npos) return {};
    const auto e = s.find_last_not_of(" \t\r\n");
    return s.substr(b, e - b + 1);
}

inline std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
}

inline std::optional<FormRef> parse_ref(const std::string& text) {
    const auto t = trim(text);
    const auto colon = t.rfind(':');
    if (colon == std::string::npos || colon == 0 || colon + 1 >= t.size()) return std::nullopt;
    const auto hex = t.substr(colon + 1);
    if (hex.size() > 8 || hex.find_first_not_of("0123456789abcdefABCDEF") != std::string::npos) return std::nullopt;
    FormRef r;
    r.plugin = trim(t.substr(0, colon));
    r.local = static_cast<std::uint32_t>(std::stoul(hex, nullptr, 16)) & 0xFFFFFFu;
    if (r.plugin.empty()) return std::nullopt;
    return r;
}

// INI: [Settings] bEnabled, bOnlyEmpty, iLogLevel; [Covers] "<LTEX ref> = <GCVR ref> ; note". Unknown keys and bad
// lines go to errors (logged), the rest still loads.
inline Settings parse_settings(std::istream& in) {
    Settings s;
    std::string line, section;
    int n = 0;
    while (std::getline(in, line)) {
        ++n;
        std::string note;
        const auto sc = line.find(';');
        if (sc != std::string::npos) {
            note = trim(line.substr(sc + 1));
            line = line.substr(0, sc);
        }
        line = trim(line);
        if (line.empty()) continue;
        if (line.front() == '[' && line.back() == ']') {
            section = lower(trim(line.substr(1, line.size() - 2)));
            continue;
        }
        const auto eq = line.find('=');
        if (eq == std::string::npos) {
            s.errors.push_back("line " + std::to_string(n) + ": no '='");
            continue;
        }
        const auto key = trim(line.substr(0, eq)), value = trim(line.substr(eq + 1));
        if (section == "settings") {
            const auto k = lower(key);
            if (k == "benabled") s.enabled = value != "0";
            else if (k == "bonlyempty") s.only_empty = value != "0";
            else if (k == "iloglevel") s.log_level = std::atoi(value.c_str());
            else s.errors.push_back("line " + std::to_string(n) + ": unknown setting " + key);
        } else if (section == "covers") {
            const auto a = parse_ref(key), b = parse_ref(value);
            if (!a || !b) {
                s.errors.push_back("line " + std::to_string(n) + ": want Plugin.esm:LTEXID = Plugin.esm:GCVRID");
                continue;
            }
            s.covers.push_back({*a, *b, note});
        } else {
            s.errors.push_back("line " + std::to_string(n) + ": outside [Settings] / [Covers]");
        }
    }
    return s;
}

// The load order: the run-time FormID of a plugin's record ({} when the plugin is not loaded). Full plugins:
// index << 24; medium: 0xFD, index << 16; small (light): 0xFE, index << 12.
struct LoadedPlugin {
    std::string name;
    enum class Kind { kFull, kMedium, kSmall } kind = Kind::kFull;
    std::uint32_t index = 0;
};

inline std::optional<std::uint32_t> runtime_id(const FormRef& r, const std::vector<LoadedPlugin>& order) {
    const auto want = lower(r.plugin);
    for (const auto& p : order) {
        if (lower(p.name) != want) continue;
        switch (p.kind) {
            case LoadedPlugin::Kind::kFull: return (p.index << 24) | (r.local & 0xFFFFFFu);
            case LoadedPlugin::Kind::kMedium: return 0xFD000000u | ((p.index & 0xFFu) << 16) | (r.local & 0xFFFFu);
            case LoadedPlugin::Kind::kSmall: return 0xFE000000u | ((p.index & 0xFFFu) << 12) | (r.local & 0xFFFu);
        }
    }
    return std::nullopt;
}

// Palette entries as FUN_1409a9570 leaves them (Starfield 1.16.244).
inline constexpr std::size_t kEntryStride = 0x38, kEntryLtex = 0x00, kEntryGcvr = 0x04;

struct PatchResult {
    std::uint32_t entries = 0, patched = 0, kept = 0;   // kept: had a cover already (only_empty)
};

// Writes map[LTEX] into +0x04 of every entry whose LTEX is in the map. Memory: count entries, stride 0x38.
inline PatchResult patch_entries(std::uint8_t* data, std::uint32_t count, const std::map<std::uint32_t, std::uint32_t>& map,
                                 bool only_empty) {
    PatchResult r;
    r.entries = count;
    if (!data) return r;
    for (std::uint32_t i = 0; i < count; ++i) {
        std::uint8_t* e = data + static_cast<std::size_t>(i) * kEntryStride;
        std::uint32_t ltex, gcvr;
        std::memcpy(&ltex, e + kEntryLtex, 4);
        std::memcpy(&gcvr, e + kEntryGcvr, 4);
        const auto it = map.find(ltex);
        if (it == map.end()) continue;
        if (gcvr != 0 && only_empty) {
            ++r.kept;
            continue;
        }
        std::memcpy(e + kEntryGcvr, &it->second, 4);
        ++r.patched;
    }
    return r;
}

}  // namespace s2s::grass
