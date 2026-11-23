// Tests for S2SDodge's settings (s2s/dodge_only.h): the controller with everything but the dodge off. Same mini
// harness as test_controller.cpp.
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

#include "s2s/dodge_only.h"

using namespace s2s::combat;

static int failures = 0;
#define CHECK(cond)                                                                   \
    do {                                                                              \
        if (!(cond)) {                                                                \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);               \
            ++failures;                                                               \
        }                                                                             \
    } while (0)

static std::vector<Command> kept(std::vector<Command> cs) {
    std::vector<Command> out;
    for (auto& c : cs)
        if (dodge_only_command(c.kind)) out.push_back(std::move(c));
    return out;
}

static std::vector<std::string> events(const std::vector<Command>& cs) {
    std::vector<std::string> out;
    for (const auto& c : cs)
        if (c.kind == Command::Kind::SendEvent) out.push_back(c.name);
    return out;
}

static std::string read(const char* path) {
    std::ifstream in(path);
    std::stringstream b;
    b << in.rdbuf();
    return b.str();
}

static void sample_ini() {
    std::vector<std::string> problems;
    const auto ini = read(S2S_DODGE_INI);
    CHECK(!ini.empty());
    auto c = parse_dodge_config(ini, &problems);
    for (const auto& p : problems) std::printf("problem: %s\n", p.c_str());
    CHECK(problems.empty());
    CHECK(c.dodge_key == 56);
    CHECK(c.dodge_events[static_cast<int>(Direction::Forward)] == "MeleeAttack01");
    CHECK(c.dodge_events[static_cast<int>(Direction::Back)] == "MeleeAttack02");
    CHECK(c.dodge_events[static_cast<int>(Direction::Left)] == "MeleeAttack03");
    CHECK(c.dodge_events[static_cast<int>(Direction::Right)] == "MeleeAttack04");
    CHECK(c.dodge.idle_direction == Direction::Back);
    CHECK(c.dodge_iframes == 0.3);
}

static void everything_else_off() {
    // S2SCombat's full settings turned on, then dodge_only
    ControllerConfig full;
    full.buffer_attacks = true;
    full.power_in_combo = true;
    full.parry_window = 0.25;
    full.block_reduction = 0.6;
    auto c = dodge_only(full);
    CHECK(!c.buffer_attacks && c.power_key == 0 && !c.power_in_combo && !c.cancel_queued_power && !c.stance_reequip);
    CHECK(c.dual_worn_keyword.empty() && c.dual_stance_keyword.empty());
    CHECK(c.parry_window == 0.0 && c.block_reduction == 0.0 && c.block_reraise_event.empty() && !c.defer_kill);
    CHECK(c.dodge_key == full.dodge_key && c.dodge_events == full.dodge_events && c.dodge_iframes == full.dodge_iframes);

    Controller ctl(c);
    PlayerState s;
    // the attack key and Starfield's power attack key do nothing (no buffer, no combo power event)
    CHECK(events(kept(ctl.on_key(256, true, 0.0, s))).empty());
    CHECK(events(kept(ctl.on_key(256, false, 0.5, s))).empty());
    CHECK(events(kept(ctl.on_anim_event("AttackStart", "", 0.6))).empty());
    CHECK(events(kept(ctl.on_key(47, true, 0.7, s))).empty());
    CHECK(!ctl.last_key_consumed());
    CHECK(events(kept(ctl.on_anim_event("AttackEnd", "", 1.0))).empty());
    // a hit while blocking gives nothing back and sends nothing
    s.blocking = s.block_key = true;
    for (const auto& cmd : ctl.on_hit(HitKind::Normal, true, 1.1, 0x1234)) CHECK(cmd.kind == Command::Kind::Log);
    s.blocking = s.block_key = false;
    CHECK(kept(ctl.tick(1.2, s)).empty() || events(kept(ctl.tick(1.2, s))).empty());
}

static void dodges() {
    Controller ctl(dodge_only(ControllerConfig{}));
    PlayerState s;
    // W held + Alt: forward
    ctl.on_key(17, true, 0.0, s);
    auto e = events(kept(ctl.on_key(56, true, 0.1, s)));
    CHECK(e.size() == 1 && e[0] == "MeleeAttack01");
    CHECK(ctl.dodging());
    CHECK(ctl.invulnerable(0.2));
    CHECK(!ctl.invulnerable(0.45));
    // a second press while dodging is ignored
    CHECK(events(kept(ctl.on_key(56, true, 0.3, s))).empty());
    // the dodge state ends like an attack (back to idle: AttackEnd)
    ctl.on_anim_event("AttackEnd", "", 0.9);
    CHECK(!ctl.dodging());
    ctl.on_key(17, false, 1.0, s);
    // standing still: back
    e = events(kept(ctl.on_key(56, true, 1.1, s)));
    CHECK(e.size() == 1 && e[0] == "MeleeAttack02");
    ctl.on_anim_event("AttackEnd", "", 1.8);
    // A: left, D: right
    ctl.on_key(30, true, 2.0, s);
    e = events(kept(ctl.on_key(56, true, 2.1, s)));
    CHECK(e.size() == 1 && e[0] == "MeleeAttack03");
    ctl.on_anim_event("AttackEnd", "", 2.8);
    ctl.on_key(30, false, 2.9, s);
    ctl.on_key(32, true, 3.0, s);
    e = events(kept(ctl.on_key(56, true, 3.1, s)));
    CHECK(e.size() == 1 && e[0] == "MeleeAttack04");
    // a lost end event: the dodge ends by itself (timeout), so the key works again
    ctl.tick(10.0, s);
    CHECK(!ctl.dodging());
    // the stick wins over the keys: stick back while D is held
    s.stick_y = -1.0f;
    e = events(kept(ctl.on_key(56, true, 10.1, s)));
    CHECK(e.size() == 1 && e[0] == "MeleeAttack02");
}

int main() {
    sample_ini();
    everything_else_off();
    dodges();
    if (failures) {
        std::printf("%d failure(s)\n", failures);
        return 1;
    }
    std::printf("dodge_only: all tests passed\n");
    return 0;
}
