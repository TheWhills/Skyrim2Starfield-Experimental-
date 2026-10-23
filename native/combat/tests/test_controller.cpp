// Tests for the controller (keys + animation events -> game commands). Same mini harness as test_combat.cpp.
#include <cstring>
#include "s2s/controller.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

using namespace s2s::combat;

static int failures = 0;
#define CHECK(cond)                                                                   \
    do {                                                                              \
        if (!(cond)) {                                                                \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);               \
            ++failures;                                                               \
        }                                                                             \
    } while (0)

static int count(const std::vector<Command>& cs, Command::Kind k) {
    int n = 0;
    for (const auto& c : cs) n += c.kind == k;
    return n;
}

static const Command* first(const std::vector<Command>& cs, Command::Kind k) {
    for (const auto& c : cs)
        if (c.kind == k) return &c;
    return nullptr;
}

static void settings() {
    std::vector<std::string> problems;
    auto c = parse_config(
        "[Combat]\n"
        "bBufferAttacks = 0\n"
        "fBufferTime=0.5 ; longer\n"
        "uDodgeKey=0x2A\n"
        "bEightWayDodge=1\n"
        "sIdleDodge=Forward\n"
        "fDodgeStaminaCost=12.5\n"
        "sPluginEventHost=S2S\n"
        "fPowerHold=abc\n"
        "bLogEvents=1\n"                // game-side key: ignored here, not a problem
        "[Other]\n"
        "uAttackKey=1\n",
        &problems);
    CHECK(!c.buffer_attacks);
    CHECK(c.buffer_time == 0.5);
    CHECK(c.dodge_key == 0x2A);
    CHECK(c.dodge.eight_way && c.dodge.idle_direction == Direction::Forward);
    CHECK(c.dodge.stamina_cost == 12.5f);
    CHECK(c.plugin_event_host == "S2S");
    CHECK(c.power_hold == 0.30);                     // unreadable: default kept and reported
    CHECK(problems.size() == 1);
    CHECK(c.attack_key == 256);                      // other sections are not read
}

static void payload_commands() {
    Controller ctl;
    auto cs = ctl.on_anim_event("PIE", "@SGVI|MCO_nextattack|2", 1.0);
    auto v = first(cs, Command::Kind::SetVariable);
    CHECK(v && v->variable.name == "MCO_nextattack" && v->variable.value == 2.0 &&
          v->variable.type == VariableSet::Type::Int);
    cs = ctl.on_anim_event("PIE", "@SVGF|MCO_AttackSpeed|1.1", 1.0);     // misspelt: nothing set, logged
    CHECK(count(cs, Command::Kind::SetVariable) == 0 && count(cs, Command::Kind::Log) == 1);
    cs = ctl.on_anim_event("HitFrame", "", 1.0);                          // plain event: no payload
    CHECK(cs.empty());

    ControllerConfig cfg;
    cfg.plugin_event_host = "S2S";                                        // whole annotation in the payload
    Controller hosted(cfg);
    cs = hosted.on_anim_event("S2S", "PIE.@SGVF|MCO_AttackSpeed|0.9", 1.0);
    v = first(cs, Command::Kind::SetVariable);
    CHECK(v && v->variable.type == VariableSet::Type::Float && v->variable.name == "MCO_AttackSpeed");
    cs = hosted.on_anim_event("S2S", "MCO_WinOpen", 1.0);
    CHECK(hosted.normal_window());
}

static void windows_and_buffer() {
    Controller ctl(parse_config("[Combat]\nbPowerInCombo = 0\n"));      // MCO's power buffering (see power_in_combo)
    PlayerState s;
    // Not attacking: the game handles the press, nothing is buffered or sent.
    ctl.on_key(256, true, 0.0, s);
    auto cs = ctl.on_key(256, false, 0.1, s);
    CHECK(count(cs, Command::Kind::SendEvent) == 0);
    ctl.on_anim_event("MCO_WinOpen", "", 0.2);
    CHECK(ctl.phase() == AttackPhase::End);
    // (the window-open above found nothing queued)
    ctl.on_anim_event("MCO_WinClose", "", 0.3);
    CHECK(ctl.phase() == AttackPhase::None && !ctl.normal_window());

    // Attacking, window closed: a quick press is kept and fired when the window opens.
    ctl.on_anim_event("preHitFrame", "", 1.0);
    CHECK(ctl.phase() == AttackPhase::Start);
    ctl.on_key(256, true, 1.05, s);
    cs = ctl.on_key(256, false, 1.10, s);
    CHECK(count(cs, Command::Kind::SendEvent) == 0 && count(cs, Command::Kind::Log) == 1);
    cs = ctl.on_anim_event("MCO_WinOpen", "", 1.30);
    auto e = first(cs, Command::Kind::SendEvent);
    CHECK(e && e->name == "MeleeAttackStart");
    cs = ctl.on_anim_event("MCO_WinClose", "", 1.40);
    CHECK(count(cs, Command::Kind::SendEvent) == 0);                     // fired once only

    // A press older than the buffer time is dropped.
    ctl.on_anim_event("preHitFrame", "", 2.0);
    ctl.on_key(256, true, 2.0, s);
    ctl.on_key(256, false, 2.05, s);
    cs = ctl.on_anim_event("MCO_WinOpen", "", 2.60);
    CHECK(count(cs, Command::Kind::SendEvent) == 0);
    ctl.on_anim_event("AttackEnd", "", 2.7);                              // Starfield's end event
    CHECK(ctl.phase() == AttackPhase::None);

    // A held press is a power attack and waits for the power window (BFCO names).
    ctl.on_anim_event("preHitFrame", "", 3.0);
    ctl.on_key(256, true, 3.0, s);
    ctl.on_key(256, false, 3.4, s);
    cs = ctl.on_anim_event("BFCO_NextWinStart", "", 3.5);
    CHECK(count(cs, Command::Kind::SendEvent) == 0);
    cs = ctl.on_anim_event("BFCO_NextPowerWinStart", "", 3.55);
    e = first(cs, Command::Kind::SendEvent);
    CHECK(e && e->name == "MeleeAttackPowerStart");

    // A press inside an open window is the game's: not sent again.
    Controller open;
    open.on_anim_event("preHitFrame", "", 0.0);
    open.on_anim_event("MCO_WinOpen", "", 0.1);
    open.on_key(256, true, 0.15, s);
    open.on_key(256, false, 0.2, s);
    cs = open.on_anim_event("MCO_WinOpen", "", 0.25);
    CHECK(count(cs, Command::Kind::SendEvent) == 0);

    // Buffering off: never sends attacks.
    ControllerConfig off;
    off.buffer_attacks = false;
    Controller nob(off);
    nob.on_anim_event("preHitFrame", "", 0.0);
    nob.on_key(256, true, 0.0, s);
    nob.on_key(256, false, 0.05, s);
    cs = nob.on_anim_event("MCO_WinOpen", "", 0.1);
    CHECK(count(cs, Command::Kind::SendEvent) == 0);
}

static void dodging() {
    Controller ctl;
    PlayerState s;
    auto cs = ctl.on_key(56, true, 0.0, s);                               // standing: back
    auto e = first(cs, Command::Kind::SendEvent);
    CHECK(e && e->name == "TKDodgeBack");
    CHECK(ctl.dodging() && ctl.invulnerable(0.1) && !ctl.invulnerable(0.35));
    CHECK(count(cs, Command::Kind::SpendStamina) == 0);                   // no cost by default in Starfield
    cs = ctl.on_key(56, true, 0.1, s);                                    // no second dodge mid-dodge
    CHECK(count(cs, Command::Kind::SendEvent) == 0);
    ctl.tick(0.4, s);                                                     // no TKDR events: over with the i-frames
    CHECK(!ctl.dodging());

    ctl.on_key(17, true, 1.0, s);                                         // W held: forward
    cs = ctl.on_key(56, true, 1.0, s);
    e = first(cs, Command::Kind::SendEvent);
    CHECK(e && e->name == "TKDodgeForward");
    ctl.on_key(17, false, 1.1, s);
    ctl.on_anim_event("TKDR_DodgeStart", "", 1.05);                       // clip events: end comes from the clip
    ctl.tick(1.5, s);
    CHECK(ctl.dodging());
    ctl.on_anim_event("TKDR_DodgeEnd", "", 1.8);
    CHECK(!ctl.dodging());

    s.stick_x = 0.9f;                                                     // the stick wins over keys
    cs = ctl.on_key(56, true, 2.0, s);
    e = first(cs, Command::Kind::SendEvent);
    CHECK(e && e->name == "TKDodgeRight");
    ctl.on_anim_event("TKDR_DodgeStart", "", 2.0);
    ctl.tick(5.5, s);                                                     // lost end event: timeout
    CHECK(!ctl.dodging());

    ControllerConfig cfg;
    cfg.dodge.stamina_cost = 20;
    Controller tired(cfg);
    PlayerState low;
    low.stamina = 10;
    cs = tired.on_key(56, true, 0.0, low);
    CHECK(count(cs, Command::Kind::SendEvent) == 0 && count(cs, Command::Kind::Log) == 1);
    low.stamina = 50;
    cs = tired.on_key(56, true, 0.0, low);
    auto st = first(cs, Command::Kind::SpendStamina);
    CHECK(st && st->amount == 20.0f);

    Controller iframes;                                                   // annotation i-frames
    iframes.on_anim_event("TKDR_IframeDuration", "", 5.0);
    CHECK(iframes.invulnerable(5.2));
    iframes.on_anim_event("TKDR_IframeEnd", "", 5.1);
    CHECK(!iframes.invulnerable(5.2));
}

static void key_bindings() {
    auto binds = parse_bindings(
        "[Keys]\n"
        "high = 200|keyword|StanceHigh\n"
        "low = 208|keyword|StanceLow\n"
        "neutral = 205|keyword\n"
        "taunt = 20|event|Taunt\n"
        "speed = 21|float|MCO_AttackSpeed=1.2\n"
        "flag = 22|bool|bFlag=5\n"
        "bad = 23|int|NoValue\n"
        "lock = 0x102|lock\n"
        "left = 203|switch_left\n"
        "odd = 24|teleport\n");
    Controller ctl({}, binds);
    PlayerState s;
    auto cs = ctl.on_key(200, true, 0.0, s);                              // high: the others out, high in
    CHECK(cs.size() == 2 && cs[0].kind == Command::Kind::RemoveKeyword && cs[0].name == "StanceLow" &&
          cs[1].kind == Command::Kind::AddKeyword && cs[1].name == "StanceHigh" && ctl.stance() == "StanceHigh");
    cs = ctl.on_key(208, true, 0.1, s);                                   // switching stance: old out, new in
    CHECK(cs.size() == 2 && cs[0].kind == Command::Kind::RemoveKeyword && cs[0].name == "StanceHigh" &&
          cs[1].kind == Command::Kind::AddKeyword && cs[1].name == "StanceLow");
    cs = ctl.on_key(208, true, 0.2, s);                                   // same key again: the stance stays
    CHECK(cs.size() == 2 && cs[0].kind == Command::Kind::RemoveKeyword && cs[1].kind == Command::Kind::AddKeyword &&
          cs[1].name == "StanceLow" && ctl.stance() == "StanceLow");
    cs = ctl.on_key(205, true, 0.25, s);                                  // neutral: every stance keyword removed
    CHECK(cs.size() == 2 && cs[0].kind == Command::Kind::RemoveKeyword && cs[1].kind == Command::Kind::RemoveKeyword);
    CHECK(ctl.on_key(200, false, 0.3, s).empty());                        // releases do nothing
    cs = ctl.on_key(20, true, 0.4, s);
    CHECK(cs.size() == 1 && cs[0].kind == Command::Kind::SendEvent && cs[0].name == "Taunt");
    cs = ctl.on_key(21, true, 0.4, s);
    CHECK(cs.size() == 1 && cs[0].variable.type == VariableSet::Type::Float && cs[0].variable.value == 1.2);
    cs = ctl.on_key(22, true, 0.4, s);
    CHECK(cs.size() == 1 && cs[0].variable.type == VariableSet::Type::Bool && cs[0].variable.value == 1.0);
    cs = ctl.on_key(23, true, 0.4, s);
    CHECK(cs.size() == 1 && cs[0].kind == Command::Kind::Log);
    cs = ctl.on_key(0x102, true, 0.4, s);
    CHECK(cs.size() == 1 && cs[0].kind == Command::Kind::ToggleLock);
    cs = ctl.on_key(203, true, 0.4, s);
    CHECK(cs.size() == 1 && cs[0].kind == Command::Kind::SwitchTarget && cs[0].dx == -1 && cs[0].dy == 0);
    cs = ctl.on_key(24, true, 0.4, s);
    CHECK(cs.size() == 1 && cs[0].kind == Command::Kind::Log);
}

static void stance_repeat_neutral() {
    ControllerConfig cfg = parse_config("[Combat]\nbStanceRepeatNeutral = 1\n");
    CHECK(cfg.stance_repeat_neutral);
    Controller ctl(cfg, parse_bindings("[Keys]\nhigh = 200|keyword|S2S_StanceHigh\nlow = 208|keyword|S2S_StanceLow\n"));
    PlayerState s;
    ctl.on_key(208, true, 0.0, s);
    auto cs = ctl.on_key(208, true, 0.1, s);                              // LoreRim's toggle: same key, back to none
    CHECK(cs.size() == 2 && cs[0].kind == Command::Kind::RemoveKeyword && cs[1].kind == Command::Kind::RemoveKeyword &&
          ctl.stance().empty());
    CHECK(!parse_config("[Combat]\n").stance_repeat_neutral);
}

static void stance_refresh() {
    ControllerConfig cfg = parse_config("[Combat]\nsStanceRefreshEvents = BlockStart, BlockStop\n");
    CHECK(cfg.stance_refresh_events.size() == 2 && cfg.stance_refresh_events[1] == "BlockStop");
    Controller ctl(cfg, parse_bindings("[Keys]\nhigh = 200|keyword|S2S_StanceHigh\nneutral = 205|keyword\n"));
    PlayerState s;
    auto cs = ctl.on_key(200, true, 0.0, s);
    CHECK(cs.size() == 3 && cs[0].kind == Command::Kind::AddKeyword && cs[1].kind == Command::Kind::SendEvent &&
          cs[1].name == "BlockStart" && cs[2].name == "BlockStop");
    cs = ctl.on_key(205, true, 0.1, s);                                   // right arrow: back to neutral
    CHECK(cs.size() == 3 && cs[0].kind == Command::Kind::RemoveKeyword && cs[0].name == "S2S_StanceHigh");
    CHECK(ctl.stance().empty());
    cs = ctl.on_key(205, true, 0.2, s);                                   // still neutral: keywords cleared again,
    CHECK(cs.size() == 1 && cs[0].kind == Command::Kind::RemoveKeyword);  // no refresh (nothing changed)
}

static void key_codes() {
    CHECK(key_from_vk('W') == 17 && key_from_vk('A') == 30 && key_from_vk('S') == 31 && key_from_vk('D') == 32);
    CHECK(key_from_vk(0x26) == 200 && key_from_vk(0x25) == 203 && key_from_vk(0x28) == 208 && key_from_vk(0x27) == 205);
    CHECK(key_from_vk(0x12) == 56 && key_from_vk(0xA4) == 56);      // Alt: TK Dodge's default key either way
    CHECK(key_from_vk('1') == 2 && key_from_vk('0') == 11 && key_from_vk(0x70) == 59 && key_from_vk(0x7B) == 88);
    CHECK(key_from_vk(0xFF) == 0);
    CHECK(key_from_mouse(0) == 256 && key_from_mouse(1) == 257 && key_from_mouse(0x800) == 264 &&
          key_from_mouse(0x900) == 265 && key_from_mouse(9) == 0);
}

static void sample_ini() {
    // The INI shipped with the plugin (sfse/S2SCombat.ini) parses cleanly and holds the documented defaults.
    std::ifstream in(S2S_SAMPLE_INI);
    CHECK(in.good());
    std::stringstream buf;
    buf << in.rdbuf();
    std::vector<std::string> problems;
    auto c = parse_config(buf.str(), &problems);
    CHECK(problems.empty());
    ControllerConfig d;
    CHECK(c.buffer_attacks == d.buffer_attacks && c.buffer_time == d.buffer_time && c.power_hold == d.power_hold);
    CHECK(c.attack_key == d.attack_key && c.dodge_key == d.dodge_key && c.move_keys == d.move_keys);
    CHECK(c.dodge.idle_direction == Direction::Back && !c.dodge.eight_way && c.dodge.stamina_cost == 0.0f);
    CHECK(c.attack_event == "MeleeAttackStart" && c.power_event == "MeleeAttackPowerStart");
    CHECK(c.plugin_event_host.empty());
    auto keys = parse_bindings(buf.str(), "Keys");                   // the arrow-key stances
    CHECK(keys.size() == 6 && keys[0].key == 200 && keys[0].argument == "S2S_StanceHigh" && keys[3].key == 205 &&
          keys[3].argument.empty());
    CHECK(keys.size() == 6 && keys[4].key == 260 && keys[4].action == "lock" && keys[5].key == 273);   // MMB, R3
    auto lock = ini_section(buf.str(), "Lock");
    CHECK(lock["fmaxdistance"] == "28.0" && lock["slockvariable"] == "TDM_TargetLock");
    CHECK(c.stance_refresh_events.empty());
    auto plugin = ini_section(buf.str(), "Plugin");
    CHECK(plugin["benabled"] == "1" && plugin["ilogkeys"] == "40" && plugin["sstaminaactorvalue"].empty());
}

static void menus() {
    MenuGate gate;
    CHECK(!gate.blocked());
    gate.on_menu("HUDMenu", true);                      // always-open HUD: still gameplay
    CHECK(!gate.blocked());
    gate.on_menu("InventoryMenu", true);
    CHECK(gate.blocked());
    gate.on_menu("inventorymenu", false);               // names compare without case
    CHECK(!gate.blocked() && gate.open().size() == 1);
    gate.on_menu("Console", true);
    gate.on_menu("Console", true);                      // repeated open: counted once
    gate.on_menu("Console", false);
    CHECK(!gate.blocked());
    MenuGate custom(MenuGate::parse_list(" FooMenu , BarMenu,"));
    custom.on_menu("BarMenu", true);
    CHECK(custom.blocked());
    custom.on_menu("Console", true);                    // not in the custom list
    custom.on_menu("BarMenu", false);
    CHECK(!custom.blocked());
}

static void hits() {
    CHECK(hit_kind("MeleeAttackPowerStart") == HitKind::Power && hit_kind("attackPowerStartForward") == HitKind::Power);
    CHECK(hit_kind("MeleeAttackStart") == HitKind::Normal && hit_kind("  ") == HitKind::Unknown);
    Controller ctl;
    auto cs = ctl.on_hit(HitKind::Power, true, 1.0);
    CHECK(cs.size() == 1 && cs[0].kind == Command::Kind::SetVariable && cs[0].variable.name == "iS2SBlockHitType" &&
          cs[0].variable.value == 1.0);
    cs = ctl.on_hit(HitKind::Normal, true, 1.0);
    CHECK(cs.size() == 1 && cs[0].variable.value == 0.0);
    CHECK(ctl.on_hit(HitKind::Power, false, 1.0).empty());             // not blocking: nothing to pick
    PlayerState s;
    ctl.on_key(56, true, 2.0, s);                                        // dodge: i-frames 2.0 - 2.3
    cs = ctl.on_hit(HitKind::Normal, false, 2.1);
    CHECK(cs.size() == 1 && cs[0].kind == Command::Kind::Log);
    auto off = parse_config("[Combat]\nsBlockHitVariable =\n");
    CHECK(off.block_hit_variable.empty() && Controller(off).on_hit(HitKind::Power, true, 0).empty());
}

static void test_layout_probe() {
    using S = LayoutProbe::Slot;
    // Starfield-like guess: payload, tag, holder (names made up for the test)
    LayoutProbe p(3, 10);
    const std::vector<S> ev = {S::Other, S::Text, S::EmptyText, S::Self, S::Other};
    CHECK(p.feed(ev) == LayoutProbe::State::Probing);
    CHECK(p.feed(ev) == LayoutProbe::State::Probing);
    CHECK(p.feed(ev) == LayoutProbe::State::Found);
    CHECK(p.tag() == 1 && p.payload() == 2 && p.holder() == 3);
    CHECK(p.feed({S::Other}) == LayoutProbe::State::Found);            // settled: later events change nothing
    // a disagreeing event restarts the streak; an event without any text breaks it
    LayoutProbe q(2, 10);
    q.feed({S::Text, S::Text});
    q.feed({S::Other, S::Text, S::Text});
    CHECK(q.state() == LayoutProbe::State::Probing && q.tag() == 1);
    q.feed({S::Other, S::Other});
    q.feed({S::Other, S::Text, S::Text});
    CHECK(q.state() == LayoutProbe::State::Probing);
    CHECK(q.feed({S::Other, S::Text, S::Text}) == LayoutProbe::State::Found && q.tag() == 1 && q.payload() == 2);
    // no payload slot at all
    LayoutProbe r(2, 10);
    r.feed({S::Self, S::Text});
    CHECK(r.feed({S::Self, S::Text}) == LayoutProbe::State::Found && r.payload() == -1 && r.holder() == 0);
    // nothing readable: gives up
    LayoutProbe f(2, 4);
    for (int i = 0; i < 3; ++i) CHECK(f.feed({S::Other, S::Other}) == LayoutProbe::State::Probing);
    CHECK(f.feed({S::Other}) == LayoutProbe::State::Failed && f.tag() == -1);
}

namespace {
struct alignas(8) PoolEntry {
    std::uintptr_t left = 0, right_or_len = 0;
    std::uint32_t ref = 0;
    std::uint8_t flags = 0, pad[3] = {};
    char text[32] = {};
};
}  // namespace

static void test_pool_strings() {
    auto readable = [](const void* p, std::size_t) { return reinterpret_cast<std::uintptr_t>(p) > 0x10000; };
    PoolEntry leaf, ext, loop, bad, bin;
    leaf.right_or_len = 11;
    std::memcpy(leaf.text, "weaponSwing", 12);
    ext.flags = 2;
    ext.right_or_len = reinterpret_cast<std::uintptr_t>(&leaf);          // external: the text is in another entry
    loop.flags = 2;
    loop.right_or_len = reinterpret_cast<std::uintptr_t>(&loop);         // a cycle
    bad.flags = 2;
    bad.right_or_len = 0x1234;                                           // into unmapped memory
    bin.right_or_len = 3;
    std::memcpy(bin.text, "\x01\x02\x03", 4);
    const std::uintptr_t slots[6] = {reinterpret_cast<std::uintptr_t>(&leaf), reinterpret_cast<std::uintptr_t>(&ext),
                                     reinterpret_cast<std::uintptr_t>(&loop), reinterpret_cast<std::uintptr_t>(&bad), 0,
                                     reinterpret_cast<std::uintptr_t>(&bin)};
    auto at = [&](int i) { return pool_string_at(reinterpret_cast<std::uintptr_t>(&slots[i]), readable); };
    CHECK(at(0) && *at(0) == "weaponSwing");
    CHECK(at(1) && *at(1) == "weaponSwing");
    CHECK(!at(2));
    CHECK(!at(3));
    CHECK(at(4) && at(4)->empty());
    CHECK(!at(5));
    CHECK(!pool_string_at(0x20, readable));                             // the slot itself unreadable
}

// Starfield picks the weapon's animation set at equip time: a stance change unequips once the keys are quiet and
// equips again on UnequipComplete (or after fStanceReequipWait without it).
static void stance_reequip() {
    Controller ctl({}, parse_bindings("[Keys]\nhigh = 200|keyword|S2S_StanceHigh\nlow = 208|keyword|S2S_StanceLow\n"
                                      "neutral = 205|keyword\n"));
    PlayerState s;
    auto count = [](const std::vector<Command>& cs, Command::Kind k) {
        int n = 0;
        for (const auto& c : cs) n += c.kind == k;
        return n;
    };
    using K = Command::Kind;
    ctl.on_key(200, true, 0.0, s);
    CHECK(count(ctl.tick(0.1, s), K::UnequipWeapon) == 0);                // not before the delay
    ctl.on_key(208, true, 0.2, s);                                        // another press moves it on
    CHECK(count(ctl.tick(0.4, s), K::UnequipWeapon) == 0);
    CHECK(count(ctl.tick(0.46, s), K::UnequipWeapon) == 1);               // 0.25 s after the last change: once
    CHECK(ctl.tick(0.5, s).empty());                                      // waiting for the unequip
    CHECK(count(ctl.on_anim_event("UnequipComplete", "", 0.6), K::EquipWeapon) == 1);
    CHECK(ctl.tick(1.5, s).empty());                                      // no second equip from the timeout
    CHECK(ctl.on_anim_event("UnequipComplete", "", 1.6).empty());         // a later unequip is not ours
    ctl.on_key(208, true, 1.7, s);                                        // same stance again: nothing to re-pick
    CHECK(ctl.tick(3.0, s).empty());
    ctl.on_key(205, true, 3.1, s);                                        // back to neutral is a change too
    CHECK(count(ctl.tick(3.4, s), K::UnequipWeapon) == 1);
    CHECK(ctl.tick(3.8, s).empty());
    CHECK(count(ctl.tick(3.91, s), K::EquipWeapon) == 1);                 // no UnequipComplete: equip after 0.5 s
    ControllerConfig off = parse_config("[Combat]\nbStanceReequip = 0\nfStanceReequipDelay = 0.5\n"
                                        "fStanceReequipWait = 1.5\n");
    CHECK(!off.stance_reequip && off.stance_reequip_delay == 0.5 && off.stance_reequip_wait == 1.5);
    Controller quiet(off, parse_bindings("[Keys]\nhigh = 200|keyword|S2S_StanceHigh\n"));
    quiet.on_key(200, true, 0.0, s);
    CHECK(quiet.tick(5.0, s).empty());
    std::vector<std::string> problems;
    parse_config("[Combat]\nfStanceReequipDelay = -1\nbStanceReequip = yes\nfStanceReequipWait = x\n", &problems);
    CHECK(problems.size() == 3);
    CHECK(parse_config("[Combat]\n").stance_reequip);
}

// A held attack during a combo sends the power event at once (vanilla Starfield never sends it mid-combo).
static void power_in_combo() {
    Controller ctl;
    PlayerState s;
    CHECK(ctl.config().power_in_combo);
    ctl.on_key(256, true, 0.0, s);                                        // standing: the game's own power attack
    CHECK(count(ctl.on_key(256, false, 0.5, s), Command::Kind::SendEvent) == 0);
    ctl.on_anim_event("preHitFrame", "", 1.0);                            // in a combo
    ctl.on_key(256, true, 1.0, s);
    auto cs = ctl.on_key(256, false, 1.4, s);
    auto e = first(cs, Command::Kind::SendEvent);
    CHECK(e && e->name == "S2S_ComboPower" && cs.size() == 1);
    CHECK(count(ctl.on_anim_event("BFCO_NextPowerWinStart", "", 1.5), Command::Kind::SendEvent) == 0);   // not again
    ctl.on_key(256, true, 1.6, s);                                        // a quick press still buffers
    cs = ctl.on_key(256, false, 1.65, s);
    CHECK(count(cs, Command::Kind::SendEvent) == 0 && count(cs, Command::Kind::Log) == 1);
    CHECK(!parse_config("[Combat]\nbPowerInCombo = 0\n").power_in_combo);
    // Starfield's power attack key (V = 47): the game's own when standing, ours during a combo
    Controller v;
    CHECK(v.config().power_key == 47);
    CHECK(count(v.on_key(47, true, 0.0, s), Command::Kind::SendEvent) == 0);
    v.on_anim_event("preHitFrame", "", 1.0);
    cs = v.on_key(47, true, 1.1, s);                                      // (first() points into cs: keep it)
    e = first(cs, Command::Kind::SendEvent);
    CHECK(e && e->name == "S2S_ComboPower");
    CHECK(v.last_key_consumed());                                          // the game must not see it
    CHECK(v.on_key(47, false, 1.2, s).empty());                            // release: nothing sent,
    CHECK(v.last_key_consumed());                                          // and hidden too
    CHECK(v.hides_power_press(47) && !v.hides_power_press(256));          // the game's controls must not see it
    v.on_anim_event("AttackEnd", "", 2.0);
    CHECK(!v.hides_power_press(47));                                       // standing: the game's own
    v.on_key(47, true, 3.0, s);                                            // standing: the game's
    CHECK(!v.last_key_consumed());
    v.on_key(47, false, 3.1, s);
    CHECK(!v.last_key_consumed());
    CHECK(parse_config("[Combat]\nuPowerAttackKey = 33\n").power_key == 33);
    CHECK(parse_config("[Combat]\nsComboPowerEvent = MeleeAttackPowerStart\n").combo_power_event ==
          "MeleeAttackPowerStart");
}

// A fake image laid out like MSVC x64 RTTI: class Manager : Sink (offset 0), BSInputEventReceiver (offset 0x10).
static void rtti_vtables() {
    alignas(8) static unsigned char img[0x400] = {};
    const auto base = reinterpret_cast<std::uintptr_t>(img);
    auto put32 = [&](std::size_t at, std::uint32_t v) { std::memcpy(img + at, &v, 4); };
    auto put64 = [&](std::size_t at, std::uintptr_t v) { std::memcpy(img + at, &v, 8); };
    auto name = [&](std::size_t td, const char* n) { std::memcpy(img + td + 0x10, n, std::strlen(n) + 1); };
    name(0x100, ".?AVManager@PlayerControls@@");
    name(0x140, ".?AVSink@@");
    name(0x180, ".?AVBSInputEventReceiver@@");
    // hierarchy at 0x1C0: 3 bases, array at 0x1D0
    put32(0x1C0 + 8, 3);
    put32(0x1C0 + 0x0C, 0x1D0);
    const std::uint32_t tds[3] = {0x100, 0x140, 0x180}, mds[3] = {0, 0, 0x10};
    for (int i = 0; i < 3; ++i) {
        const std::size_t bcd = 0x200 + 0x20 * i;
        put32(0x1D0 + 4 * i, static_cast<std::uint32_t>(bcd));
        put32(bcd, tds[i]);
        put32(bcd + 8, mds[i]);
        put32(bcd + 0x0C, 0xFFFFFFFFu);
    }
    // two complete object locators (offset 0 and 0x10) and their vtables
    const std::size_t cols[2] = {0x280, 0x2A0}, vts[2] = {0x300, 0x340};
    for (int i = 0; i < 2; ++i) {
        put32(cols[i], 1);
        put32(cols[i] + 4, i ? 0x10 : 0);
        put32(cols[i] + 0x0C, 0x100);
        put32(cols[i] + 0x10, 0x1C0);
        put32(cols[i] + 0x14, static_cast<std::uint32_t>(cols[i]));
        put64(vts[i] - 8, base + cols[i]);
    }
    auto inside = [&](const void* p, std::size_t n) {
        const auto a = reinterpret_cast<std::uintptr_t>(p);
        return a >= base && a + n <= base + sizeof(img);
    };
    auto r = rtti_base_vtable({base + vts[0], base + vts[1]}, ".?AVBSInputEventReceiver@@", inside);
    CHECK(r && r->index == 1 && r->vtable == base + vts[1] && r->complete_class == ".?AVManager@PlayerControls@@");
    r = rtti_base_vtable({base + vts[1], base + vts[0]}, ".?AVSink@@", inside);       // any order
    CHECK(r && r->index == 1);
    CHECK(!rtti_base_vtable({base + vts[0]}, ".?AVOther@@", inside));                 // not a base
    CHECK(!rtti_base_vtable({base + 0x10}, ".?AVSink@@", inside));                    // no locator there
    CHECK(!rtti_base_vtable({base + vts[0]}, ".?AVSink@@", [](const void*, std::size_t) { return false; }));
}

int main() {
    rtti_vtables();
    key_codes();
    power_in_combo();
    stance_reequip();
    hits();
    menus();
    stance_refresh();
    stance_repeat_neutral();
    sample_ini();
    settings();
    payload_commands();
    windows_and_buffer();
    dodging();
    key_bindings();
    test_layout_probe();
    test_pool_strings();
    if (failures == 0) std::printf("all controller tests passed\n");
    return failures;
}
