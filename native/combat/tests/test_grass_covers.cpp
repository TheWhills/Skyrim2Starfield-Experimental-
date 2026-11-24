// s2s/grass_covers.h: the S2SGrass INI and the palette entry patch (synthetic entries, no game).
#include "s2s/grass_covers.h"

#include <cstdio>
#include <cstring>
#include <sstream>

static int g_fail = 0;
#define CHECK(c)                                                         \
    do {                                                                 \
        if (!(c)) {                                                      \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);     \
            ++g_fail;                                                    \
        }                                                                \
    } while (0)

using namespace s2s::grass;

static void test_parse() {
    std::istringstream in(
        "; comment\n[Settings]\nbEnabled=1\nbOnlyEmpty = 0\niLogLevel=2\n"
        "[Covers]\nStarfield.esm:030137 = S2SGrass.esm:00080D ; LFieldGrass02\n"
        "Starfield.esm:0x1 = nope\nbad line\n[Other]\nx=1\n");
    const auto s = parse_settings(in);
    CHECK(s.enabled);
    CHECK(!s.only_empty);
    CHECK(s.log_level == 2);
    CHECK(s.covers.size() == 1);
    CHECK((s.covers[0].ltex == FormRef{ "Starfield.esm", 0x030137 }));
    CHECK((s.covers[0].gcvr == FormRef{ "S2SGrass.esm", 0x80D }));
    CHECK(s.covers[0].note == "LFieldGrass02");
    CHECK(s.errors.size() == 3);
    CHECK(parse_ref("A.esm:FF00080D")->local == 0x80D);   // the load-order byte is dropped
    CHECK(!parse_ref(":12"));
    CHECK(!parse_ref("A.esm:"));
}

static void test_runtime_id() {
    using K = LoadedPlugin::Kind;
    const std::vector<LoadedPlugin> order{ { "Starfield.esm", K::kFull, 0 }, { "S2SGrass.esm", K::kFull, 7 },
                                           { "Med.esm", K::kMedium, 2 }, { "Light.esp", K::kSmall, 0x12 } };
    CHECK(runtime_id({ "starfield.ESM", 0x030137 }, order) == 0x00030137u);
    CHECK(runtime_id({ "S2SGrass.esm", 0x80D }, order) == 0x0700080Du);
    CHECK(runtime_id({ "Med.esm", 0x80D }, order) == 0xFD02080Du);
    CHECK(runtime_id({ "Light.esp", 0x80D }, order) == 0xFE01280Du);
    CHECK(!runtime_id({ "Missing.esm", 1 }, order));
}

static void test_patch() {
    std::uint8_t buf[3 * kEntryStride]{};
    const std::uint32_t ltex[3] = { 0x30137, 0x10861, 0x99 }, gcvr[3] = { 0, 0x123, 0 };
    for (int i = 0; i < 3; ++i) {
        std::memcpy(buf + i * kEntryStride, &ltex[i], 4);
        std::memcpy(buf + i * kEntryStride + 4, &gcvr[i], 4);
        buf[i * kEntryStride + 8] = 0xAB;    // the rest of the entry stays as it was
    }
    const std::map<std::uint32_t, std::uint32_t> map{ { 0x30137, 0x0700080D }, { 0x10861, 0x0700080E } };
    auto r = patch_entries(buf, 3, map, true);
    CHECK(r.entries == 3 && r.patched == 1 && r.kept == 1);
    std::uint32_t v;
    std::memcpy(&v, buf + 4, 4);
    CHECK(v == 0x0700080Du);
    std::memcpy(&v, buf + kEntryStride + 4, 4);
    CHECK(v == 0x123u);                                  // a vanilla slot cover is kept
    std::memcpy(&v, buf + 2 * kEntryStride + 4, 4);
    CHECK(v == 0u);
    CHECK(buf[8] == 0xAB && buf[kEntryStride + 8] == 0xAB);
    r = patch_entries(buf, 3, map, false);
    std::memcpy(&v, buf + kEntryStride + 4, 4);
    CHECK(r.patched == 2 && v == 0x0700080Eu);
    CHECK(patch_entries(nullptr, 3, map, true).patched == 0);
}

int main() {
    test_parse();
    test_runtime_id();
    test_patch();
    std::printf(g_fail ? "%d failure(s)\n" : "grass_covers: all passed\n", g_fail);
    return g_fail ? 1 : 0;
}
