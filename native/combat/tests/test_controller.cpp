// Tests for the controller (keys + animation events -> game commands). Same mini harness as test_combat.cpp.
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
    Controller ctl;
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
    cs = ctl.on_key(208, true, 0.2, s);                                   // same key again: back to no stance
    CHECK(cs.size() == 2 && cs[0].kind == Command::Kind::RemoveKeyword && cs[1].kind == Command::Kind::RemoveKeyword &&
          ctl.stance().empty());
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
    CHECK(keys.size() == 6 && keys[4].key == 258 && keys[4].action == "lock" && keys[5].key == 273);   // MMB, R3
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

int main() {
    key_codes();
    hits();
    menus();
    stance_refresh();
    sample_ini();
    settings();
    payload_commands();
    windows_and_buffer();
    dodging();
    key_bindings();
    if (failures == 0) std::printf("all controller tests passed\n");
    return failures;
}
