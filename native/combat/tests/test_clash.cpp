// Tests for the weapon clash standoff (s2s/clash.h). Same mini harness as test_combat.cpp.
#include "s2s/clash.h"

#include <cmath>
#include <cstdio>
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

static bool has_events_for(const std::vector<Command>& cs, std::uint32_t who) {
    for (const auto& c : cs)
        if (c.kind == Command::Kind::ActorEvents && c.target == who) return true;
    return false;
}

static void start_and_guard() {
    Clash c;
    auto out = c.start(0x1234, 10.0);
    CHECK(c.active());
    CHECK(c.opponent() == 0x1234u);
    CHECK(std::abs(c.meter() - 0.5) < 1e-9);
    const auto* begin = first(out, Command::Kind::ClashBegin);
    CHECK(begin && begin->target == 0x1234u && std::abs(begin->amount - 0.7f) < 1e-6f);
    const auto* var = first(out, Command::Kind::ActorVariable);
    CHECK(var && var->variable.name == "iWantBlock" && var->variable.value == 1.0);
    CHECK(count(out, Command::Kind::Guard) == 2);           // both guards, each with the interrupt
    for (const auto& g : out)
        if (g.kind == Command::Kind::Guard) CHECK(g.name == "BlockStart" && g.extra == "ActionInterrupt" &&
                                                  (g.target == 0x1234u || g.target == 0x14u));
    CHECK(!has_events_for(out, 0x1234) && !has_events_for(out, 0x14));
    CHECK(count(out, Command::Kind::Notify) == 1);
    // a second start while running does nothing
    CHECK(c.start(0x5678, 10.1).empty());
    CHECK(c.opponent() == 0x1234u);
}

static void win_by_mashing() {
    Clash c;
    c.start(0x1234, 0.0);
    double t = 0.0;
    std::vector<Command> last;
    // 8 presses a second against a push of 4 (normal): the meter climbs 0.36 / s net
    for (int i = 0; i < 100 && c.active(); ++i) {
        t += 0.125;
        last = c.on_attack(true, t);
        c.on_attack(false, t + 0.01);
    }
    CHECK(!c.active());
    CHECK(c.last_outcome() == Clash::Outcome::Win);
    CHECK(t < 5.0);
    const auto* end = first(last, Command::Kind::ClashEnd);
    CHECK(end && end->name == "win" && end->target == 0x1234u);
    CHECK(has_events_for(last, 0x1234));                    // the opponent staggers
    bool mag = false;
    for (const auto& c : last)
        if (c.kind == Command::Kind::ActorVariable && c.target == 0x1234u && c.variable.name == "staggerMagnitude" &&
            c.variable.value == 1.0)
            mag = true;
    CHECK(mag);
    CHECK(!has_events_for(last, 0x14));                     // no winner events by default
}

static void lose_when_idle() {
    ClashConfig no_grace;
    no_grace.grace_time = 0.0;
    Clash c(no_grace);
    c.start(0x1234, 0.0);
    std::vector<Command> last;
    double t = 0.0;
    while (c.active() && t < 10.0) {
        t += 1.0 / 60.0;
        last = c.tick(t);
    }
    CHECK(c.last_outcome() == Clash::Outcome::Lose);
    // 0.5 / 0.36 per second = ~1.39 s
    CHECK(t > 1.3 && t < 1.5);
    CHECK(has_events_for(last, 0x14));                      // the player staggers
    const auto* end = first(last, Command::Kind::ClashEnd);
    CHECK(end && end->name == "lose");
}

static void draw_on_timeout() {
    ClashConfig cfg;
    cfg.duration = 2.0;
    Clash c(cfg);
    c.start(0x1234, 0.0);
    std::vector<Command> last;
    double t = 0.0;
    // exactly 4 presses a second holds the meter still
    while (c.active() && t < 5.0) {
        t += 0.25;
        last = c.on_attack(true, t);
    }
    CHECK(c.last_outcome() == Clash::Outcome::Draw);
    CHECK(t >= 2.0 && t < 2.3);
    CHECK(has_events_for(last, 0x14) && has_events_for(last, 0x1234));
}

static void timeout_favours_meter() {
    ClashConfig cfg;
    cfg.duration = 1.1;
    cfg.grace_time = 0.0;
    cfg.timeout_resolution = 1;
    cfg.mode = 0;                           // easy: 3 / s
    Clash c(cfg);
    c.start(0x1234, 0.0);
    double t = 0.0;
    while (c.active() && t < 3.0) {         // 4 / s against 3 / s: slowly ahead
        t += 0.25;
        c.on_attack(true, t);
    }
    CHECK(c.last_outcome() == Clash::Outcome::Win);
}

static void hold_to_mash_matches_opponent() {
    ClashConfig cfg;
    cfg.hold_to_mash = true;
    cfg.duration = 2.0;
    Clash c(cfg);
    c.start(0x1234, 0.0);
    c.on_attack(true, 0.0);
    double t = 0.0;
    while (c.active() && t < 3.0) {
        t += 1.0 / 60.0;
        c.tick(t);
        if (c.active()) CHECK(std::abs(c.meter() - 0.5) < 1e-6);
    }
    CHECK(c.last_outcome() == Clash::Outcome::Draw);
}

static void cooldown_and_chance() {
    ClashConfig cfg;
    cfg.cooldown = 2.0;
    cfg.trigger_chance = 50.0;
    Clash c(cfg);
    CHECK(c.start(0x1234, 0.0, 60.0).empty());              // roll over the chance
    CHECK(!c.start(0x1234, 0.0, 10.0).empty());
    c.abort(1.0, "test");
    CHECK(!c.active());
    CHECK(c.last_outcome() == Clash::Outcome::Abort);
    CHECK(c.start(0x1234, 2.5, 0.0).empty());               // 1.5 s after the end
    CHECK(!c.start(0x1234, 3.1, 0.0).empty());
}

static void abort_releases() {
    Clash c;
    c.start(0x1234, 0.0);
    auto out = c.abort(0.5, "opponent died");
    CHECK(count(out, Command::Kind::Log) == 1);
    const auto* end = first(out, Command::Kind::ClashEnd);
    CHECK(end && end->name == "abort");
    const auto* var = first(out, Command::Kind::ActorVariable);
    CHECK(var && var->variable.value == 0.0);
    CHECK(!has_events_for(out, 0x14) && !has_events_for(out, 0x1234));   // no staggers
    CHECK(c.abort(0.6, "again").empty());
}

static void sparks_and_guard_repeat() {
    ClashConfig sc;
    sc.spark_interval = 0.25;
    sc.grace_time = 0.0;
    Clash c(sc);
    c.start(0x1234, 0.0);
    int sparks = 0, guards = 0;
    double t = 0.0;
    for (int i = 0; i < 60; ++i) {               // one second, mashing enough to stay in
        t += 1.0 / 60.0;
        auto out = (i % 15 == 0) ? c.on_attack(true, t) : c.tick(t);
        sparks += count(out, Command::Kind::Spark);
        guards += count(out, Command::Kind::Guard);
    }
    CHECK(c.active());
    CHECK(sparks >= 4 && sparks <= 5);           // every 0.25 s
    CHECK(guards >= 2 && guards <= 4);           // both, every 0.5 s
}

static void zone_messages() {
    Clash c;
    c.start(0x1234, 0.0);
    int msgs = 0;
    double t = 0.0;
    while (c.active() && t < 3.0) {
        t += 1.0 / 60.0;
        msgs += count(c.tick(t), Command::Kind::Notify);
    }
    // the losing message on crossing 0.25, then the lose message
    CHECK(msgs == 2);
}

static void perfect_block_trigger() {
    std::vector<Command> cmds;
    cmds.emplace_back(Command::Kind::RestoreHealth);
    Command parry{Command::Kind::ActorEvents, "StaggerStart"};
    parry.target = 0x1234;
    cmds.push_back(parry);
    cmds.emplace_back(Command::Kind::Feedback, "Timed block");
    CHECK(!take_perfect_block(cmds, 0));
    CHECK(!take_perfect_block(cmds, 0x9999));
    CHECK(cmds.size() == 3);
    CHECK(take_perfect_block(cmds, 0x1234));
    CHECK(cmds.size() == 2);
    CHECK(count(cmds, Command::Kind::ActorEvents) == 0);
    CHECK(count(cmds, Command::Kind::RestoreHealth) == 1);
}

static void settings() {
    std::vector<std::string> problems;
    auto c = parse_clash_config(
        "[Combat]\nfDuration = 9\n"
        "[Clash]\n"
        "bEnabled = 0\nfDuration = 3 ; shorter\niMode = 2\nfHardPressesPerSecond = 6\n"
        "sLoserEvents = recoilLargeStart\nfSparkInterval = 0\nbHoldToMash = 1\niMode2 = 1\nfPressGain = x\nbFaceEachOther = 0\n",
        &problems);
    CHECK(!c.enabled);
    CHECK(c.duration == 3.0);
    CHECK(c.mode == 2);
    CHECK(c.presses_per_second[2] == 6.0);
    CHECK(c.loser_events == "recoilLargeStart");
    CHECK(c.spark_interval == 0.0);
    CHECK(c.hold_to_mash);
    CHECK(!c.face_each_other);
    CHECK(c.press_gain == 0.09);
    CHECK(problems.size() == 2);
    Clash clash(c);
    CHECK(std::abs(clash.push_rate() - 0.09 * 6.0) < 1e-9);
    CHECK(clash.start(1, 0.0).empty());           // disabled
}

#ifdef S2S_SAMPLE_INI
#include <fstream>
#include <sstream>
static void sample_ini() {
    std::ifstream in(S2S_SAMPLE_INI);
    std::stringstream buf;
    buf << in.rdbuf();
    std::vector<std::string> problems;
    auto c = parse_clash_config(buf.str(), &problems);
    for (const auto& p : problems) std::printf("sample INI: %s\n", p.c_str());
    CHECK(problems.empty());
    CHECK(c.enabled);
}
#endif

static void grace_time() {
    Clash c;                                     // 1 s grace by default
    c.start(0x1234, 0.0);
    double t = 0.0;
    while (c.active() && t < 10.0) {
        t += 1.0 / 60.0;
        c.tick(t);
        if (t < 0.59) CHECK(c.meter() == 0.5);
    }
    CHECK(c.last_outcome() == Clash::Outcome::Lose);
    CHECK(t > 1.9 && t < 2.1);                   // 0.6 s grace + 1.39 s
    c = Clash();
    c.start(0x1234, 0.0);
    c.on_attack(true, 0.3);                      // in the grace: ignored
    CHECK(c.presses() == 0 && c.meter() == 0.5);
    c.on_attack(true, 0.6);
    c.on_attack(true, 0.6);
    CHECK(c.presses() == 2);
    CHECK(std::abs(c.meter() - 0.68) < 1e-9);
}

static void early_guard_repeat() {
    Clash c;                                      // 0.6 s grace: both guards checked every 0.1 s
    c.start(0x1234, 0.0);
    int guards = 0;
    double t = 0.0;
    for (int i = 0; i < 36; ++i) {
        t += 1.0 / 60.0;
        guards += count(c.tick(t), Command::Kind::Guard);
    }
    CHECK(guards >= 10 && guards <= 12);
    CHECK(count(c.tick(t + 0.01), Command::Kind::Spark) == 0);   // sparks off by default
}

static void event_filter_and_heading() {
    ClashConfig c;
    const auto prefixes = MenuGate::parse_list(c.blocked_events);
    CHECK(matches_prefix("MeleeAttack02", prefixes));
    CHECK(matches_prefix("recoilStart", prefixes));
    CHECK(matches_prefix("staggerStart", prefixes));          // any case
    CHECK(matches_prefix("BlockStop", prefixes) && matches_prefix("blockStopInstant", prefixes));
    CHECK(matches_prefix("turnLeft", prefixes));
    CHECK(!matches_prefix("BlockStart", prefixes));
    CHECK(!matches_prefix("ActionInterrupt", prefixes));
    CHECK(!matches_prefix("staggerStop", prefixes) && !matches_prefix("recoilStop", prefixes));
    CHECK(!matches_prefix("MeleeAttackStop", prefixes));
    CHECK(!matches_prefix("SoundPlay", prefixes));
    CHECK(!matches_prefix("Melee", prefixes));                // shorter than every prefix
    CHECK(!matches_prefix("anything", {}));
    const float deg = 3.14159265f / 180.0f;
    CHECK(!heading_drifted(1.0f, 1.0f + 0.3f * deg, 0.5f * deg));
    CHECK(heading_drifted(1.0f, 1.0f + 0.7f * deg, 0.5f * deg));
    CHECK(!heading_drifted(3.14f, -3.14f, 0.5f * deg));        // across the wrap: 0.18 deg apart
    CHECK(c.settle_time == 0.5 && c.zero_variables == "Speed, SpeedSampled, Direction, TurnDelta");
}

int main() {
    event_filter_and_heading();
    early_guard_repeat();
    grace_time();
    start_and_guard();
    win_by_mashing();
    lose_when_idle();
    draw_on_timeout();
    timeout_favours_meter();
    hold_to_mash_matches_opponent();
    cooldown_and_chance();
    abort_releases();
    sparks_and_guard_repeat();
    zone_messages();
    perfect_block_trigger();
    settings();
#ifdef S2S_SAMPLE_INI
    sample_ini();
#endif
    if (failures) {
        std::printf("%d failure(s)\n", failures);
        return 1;
    }
    std::printf("clash: all passed\n");
    return 0;
}
