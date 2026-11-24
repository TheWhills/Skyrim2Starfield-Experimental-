// S2SGrass SFSE plugin: every converted Skyrim ground texture grows its own Skyrim grass (docs/re/ground-cover-density.md
// route B, 2026-11-24). Hooks the one call of FUN_1409a9570 (Address Library 58316: an overlay's LTEX table -> palette
// entries) inside FUN_140795410 (51867, +0x1D6; the add-overlay functor of the planet palette rebuild). After the game
// filled the entries, each entry whose ground texture is in S2SGrass.ini [Covers] gets that ground cover (+0x04).
// The INI is written by scripts/terrain/skyrim_grass_native.py --palette-hook next to S2SGrass.esm's covers.
#include "s2s/grass_covers.h"

#include <atomic>
#include <fstream>
#include <map>

namespace {

constexpr auto kIni = "Data\\SFSE\\Plugins\\S2SGrass.ini";
constexpr REL::ID kAddOverlay{ 51867 };      // FUN_140795410 (Starfield 1.16.244)
constexpr REL::ID kBuildEntries{ 58316 };    // FUN_1409a9570
constexpr std::ptrdiff_t kCallOffset = 0x1D6;  // 0x1407955e6: e8 -> FUN_1409a9570
constexpr std::uint8_t kGroundCoverType = 0xA8;   // TESForm +0x2E of a GCVR (FUN_1409a84d0's check)
constexpr std::ptrdiff_t kTerrainWorld = 0xC0;   // FUN_1409a9570's first argument: the overlay terrain, world at +0xC0

s2s::grass::Settings g_settings;
std::map<std::uint32_t, std::uint32_t> g_map;    // run-time LTEX FormID -> GCVR FormID
std::atomic<bool> g_ready{ false };
std::atomic<int> g_calls{ 0 };

using BuildEntries_t = void(void* a_terrain, std::uint32_t* a_out, void* a_3, void* a_4, std::int32_t* a_anchor);
BuildEntries_t* g_original = nullptr;

void BuildEntries(void* a_terrain, std::uint32_t* a_out, void* a_3, void* a_4, std::int32_t* a_anchor) {
    g_original(a_terrain, a_out, a_3, a_4, a_anchor);
    if (!g_ready.load() || !a_out) return;
    const auto count = a_out[0];
    auto* data = *reinterpret_cast<std::uint8_t**>(reinterpret_cast<std::uint8_t*>(a_out) + 8);
    const auto r = s2s::grass::patch_entries(data, count, g_map, g_settings.only_empty);
    std::uint32_t world = 0;
    if (a_terrain) {
        const auto* w = *reinterpret_cast<RE::TESForm* const*>(static_cast<std::uint8_t*>(a_terrain) + kTerrainWorld);
        if (w) world = w->GetFormID();
    }
    const int n = ++g_calls;
    if (g_settings.log_level >= 1 && (r.patched || g_settings.log_level >= 2 || n <= 20))
        REX::INFO("overlay palette (world {:08X}): {} entries, {} given our ground cover, {} kept their own",
                  world, r.entries, r.patched, r.kept);
    if (g_settings.log_level >= 2 && data) {
        for (std::uint32_t i = 0; i < count; ++i) {
            std::uint32_t ltex, gcvr;
            std::memcpy(&ltex, data + i * s2s::grass::kEntryStride, 4);
            std::memcpy(&gcvr, data + i * s2s::grass::kEntryStride + 4, 4);
            REX::INFO("  entry {}: LTEX {:08X} GCVR {:08X}", i, ltex, gcvr);
        }
    }
}

std::vector<s2s::grass::LoadedPlugin> LoadOrder() {
    std::vector<s2s::grass::LoadedPlugin> out;
    auto* dh = RE::TESDataHandler::GetSingleton();
    if (!dh) return out;
    using Kind = s2s::grass::LoadedPlugin::Kind;
    for (auto* f : dh->compiledFileCollection.files)
        if (f) out.push_back({ f->fileName, Kind::kFull, f->compileIndex });
    for (auto* f : dh->compiledFileCollection.mediumFiles)
        if (f) out.push_back({ f->fileName, Kind::kMedium, f->fileIndex.mediumIndex });
    for (auto* f : dh->compiledFileCollection.smallFiles)
        if (f) out.push_back({ f->fileName, Kind::kSmall, f->fileIndex.smallIndex });
    return out;
}

void ResolveCovers() {
    const auto order = LoadOrder();
    REX::INFO("{} plugins loaded", order.size());
    int bad = 0;
    for (const auto& c : g_settings.covers) {
        const auto ltex = s2s::grass::runtime_id(c.ltex, order);
        const auto gcvr = s2s::grass::runtime_id(c.gcvr, order);
        if (!ltex || !gcvr) {
            if (bad++ < 10)
                REX::WARN("{}: {} or {} not loaded", c.note, c.ltex.plugin, c.gcvr.plugin);
            continue;
        }
        const auto* form = RE::TESForm::LookupByID(*gcvr);
        if (!form || static_cast<std::uint8_t>(form->GetFormType()) != kGroundCoverType) {
            if (bad++ < 10)
                REX::WARN("{}: {:08X} is not a ground cover (form type {})", c.note, *gcvr,
                          form ? static_cast<int>(static_cast<std::uint8_t>(form->GetFormType())) : -1);
            continue;
        }
        g_map[*ltex] = *gcvr;
        if (g_settings.log_level >= 2) REX::INFO("  {}: LTEX {:08X} -> GCVR {:08X}", c.note, *ltex, *gcvr);
    }
    REX::INFO("{} of {} ground textures have a ground cover ({} skipped)", g_map.size(), g_settings.covers.size(), bad);
    g_ready = !g_map.empty();
}

bool InstallHook() {
    REL::Relocation<std::uintptr_t> site{ kAddOverlay, kCallOffset };
    const auto at = site.address();
    const auto* bytes = reinterpret_cast<const std::uint8_t*>(at);
    if (bytes[0] != 0xE8) {
        REX::ERROR("no call at {:X} (byte {:02X}): other game version? S2SGrass inactive", at, bytes[0]);
        return false;
    }
    std::int32_t rel;
    std::memcpy(&rel, bytes + 1, 4);
    const auto dst = at + 5 + static_cast<std::intptr_t>(rel);
    if (dst != kBuildEntries.address()) {
        REX::ERROR("the call at {:X} goes to {:X}, not {:X}: other game version? S2SGrass inactive", at, dst,
                   kBuildEntries.address());
        return false;
    }
    g_original = reinterpret_cast<BuildEntries_t*>(site.write_call<5>(BuildEntries));
    REX::INFO("hook installed at {:X} (original {:X})", at, reinterpret_cast<std::uintptr_t>(g_original));
    return true;
}

void OnMessage(SFSE::MessagingInterface::Message* a_msg) {
    if (a_msg && a_msg->type == SFSE::MessagingInterface::kPostDataLoad) ResolveCovers();
}

}  // namespace

SFSE_PLUGIN_LOAD(const SFSE::LoadInterface* a_sfse) {
    SFSE::Init(a_sfse, { .trampoline = true, .trampolineSize = 64 });
    REX::INFO("S2SGrass loading");
    std::ifstream in(kIni);
    if (!in) {
        REX::ERROR("{} missing: S2SGrass inactive (rebuild the grass mod with --palette-hook)", kIni);
        return true;
    }
    g_settings = s2s::grass::parse_settings(in);
    for (const auto& e : g_settings.errors) REX::WARN("{}: {}", kIni, e);
    REX::INFO("{} covers in {}", g_settings.covers.size(), kIni);
    if (!g_settings.enabled) {
        REX::INFO("bEnabled = 0: S2SGrass inactive");
        return true;
    }
    if (!InstallHook()) return true;
    if (!SFSE::GetMessagingInterface()->RegisterListener(OnMessage)) REX::ERROR("could not register for SFSE messages");
    return true;
}
