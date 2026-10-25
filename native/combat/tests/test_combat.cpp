// Tests for the combat core (no framework: each CHECK prints the failing line; the exit code is the failure count).
#include "s2s/combat.h"

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

static void payloads() {
    auto p = parse_payload("PIE.@SGVI|MCO_nextattack|2");
    CHECK(p && p->host == "PIE" && p->instruction == "SGVI" && !p->custom);
    CHECK(p && p->args.size() == 2 && p->args[0] == "MCO_nextattack" && p->args[1] == "2");
    auto v = as_variable_set(*p);
    CHECK(v && v->type == VariableSet::Type::Int && v->name == "MCO_nextattack" && v->value == 2.0);
    auto f = as_variable_set(*parse_payload("PIE.@SGVF|MCO_AttackSpeed|.9"));   // leading-dot number, as shipped
    CHECK(f && f->type == VariableSet::Type::Float && std::fabs(f->value - 0.9) < 1e-12);
    CHECK(!as_variable_set(*parse_payload("PIE.@SVGF|MCO_AttackSpeed|1.1")));  // misspelt: ignored, as in Skyrim
    auto c = parse_payload("HitFrame.$ES_Strikefly");
    CHECK(c && c->custom && c->host == "HitFrame" && c->instruction == "ES_Strikefly" && c->args.empty());
    auto cam = parse_payload("HitFrame.@CAMSHAKE|1|0.1");
    CHECK(cam && cam->instruction == "CAMSHAKE" && cam->args.size() == 2);
    CHECK(!parse_payload("HitFrame"));
    CHECK(!parse_payload("PIE.@"));
    auto b = as_variable_set(*parse_payload("PIE.@SGVB|bInIframe|1"));
    CHECK(b && b->type == VariableSet::Type::Bool && b->value == 1.0);
    CHECK(!as_variable_set(*parse_payload("PIE.@SGVI|MCO_nextattack|two")));
}

static void attack_phase() {
    AttackPhaseTracker t;
    CHECK(t.on_event("preHitFrame") == AttackPhase::Start);
    CHECK(t.turn_multiplier() == 1.0f);
    CHECK(t.on_event("weaponSwing") == AttackPhase::Mid);
    CHECK(t.on_event("preHitFrame") == AttackPhase::Mid);                      // no going back mid-swing
    CHECK(t.on_event("HitFrame.@CAMSHAKE|1|0.1") == AttackPhase::End);         // payload host counts
    CHECK(t.turn_multiplier() == 0.0f);
    CHECK(t.on_event("weaponSwing") == AttackPhase::End);
    CHECK(t.on_event("MCO_WinClose") == AttackPhase::None);
    CHECK(t.on_event("FootLeft") == AttackPhase::None);
    CHECK(t.on_event("bfco_diy_endloop") == AttackPhase::None);               // case-insensitive names
}

static void input_buffer() {
    InputBuffer b;
    b.press(0.0);
    CHECK(b.release(0.1) == AttackKind::Normal);
    CHECK(!b.take(0.2, false, false));                                         // window closed: kept
    auto a = b.take(0.3, false, true);
    CHECK(a && a->kind == AttackKind::Normal);
    CHECK(!b.take(0.31, true, true));                                          // used once
    b.press(1.0);
    CHECK(b.release(1.4) == AttackKind::Power);
    CHECK(!b.take(1.5, false, true));                                          // power needs the power window
    CHECK(!b.take(1.9, true, true));                                           // too late: forgotten
    b.press(2.0);
    CHECK(!b.charge_started(2.5));
    CHECK(b.charge_started(2.9));
    CHECK(!b.charge_started(3.0));                                             // once
    CHECK(b.release(3.5) == AttackKind::Charged);
    CHECK(!b.take(3.6, true, true));                                           // a charge is not queued again
}

static void iframes() {
    IFrames f;
    f.open(1.0, 0.3);
    CHECK(!f.invulnerable(0.99) && f.invulnerable(1.0) && f.invulnerable(1.29) && !f.invulnerable(1.3));
    f.open_until_closed(2.0);
    CHECK(f.invulnerable(5.0));
    f.close(5.5);
    CHECK(!f.invulnerable(5.6) && f.invulnerable(5.4));
    f.open(10.0, 0.0);
    CHECK(!f.invulnerable(10.0));
}

static void dodge() {
    DodgeConfig four;
    CHECK(dodge_direction(0, 0, four) == Direction::Back);                     // standing still: default
    CHECK(dodge_direction(0, 1, four) == Direction::Forward);
    CHECK(dodge_direction(1, 0.2f, four) == Direction::Right);
    CHECK(dodge_direction(-1, 0, four) == Direction::Left);
    CHECK(dodge_direction(0.2f, -1, four) == Direction::Back);
    CHECK(dodge_direction(0.7f, 0.7f, four) != Direction::ForwardRight);       // 4-way never diagonal
    DodgeConfig eight;
    eight.eight_way = true;
    CHECK(dodge_direction(0.7f, 0.7f, eight) == Direction::ForwardRight);
    CHECK(dodge_direction(-0.7f, -0.7f, eight) == Direction::BackLeft);
    CHECK(dodge_event(Direction::Left) == "TKDodgeLeft");
    CHECK(can_dodge(20, false, AttackPhase::Mid, four));
    four.allow_attack_cancel = false;
    CHECK(!can_dodge(20, false, AttackPhase::Mid, four));
    CHECK(!can_dodge(5, false, AttackPhase::None, four));
    CHECK(!can_dodge(50, true, AttackPhase::None, four));
}

static void lock_on() {
    LockOn lock;
    Vec3 player{0, 0, 0}, fwd{0, 1, 0};
    std::vector<Candidate> c(4);
    c[0] = {1, {0, 1500, 0}};                     // ahead, far
    c[1] = {2, {600, 300, 0}};                    // close, off to the right
    c[2] = {3, {0, 3000, 0}};                     // out of range
    c[3] = {4, {-100, 100, 0}};
    c[3].hostile = false;                         // friendly: ignored
    CHECK(lock.acquire(c, player, fwd, SelectMode::Closest) == 2u);
    lock.release();
    CHECK(lock.acquire(c, player, fwd, SelectMode::Center) == 1u);
    lock.release();
    c[0].under_crosshair = true;
    CHECK(lock.acquire(c, player, fwd, SelectMode::Closest) == 1u);           // crosshair first
    c[0].under_crosshair = false;
    CHECK(lock.update(c, player, 0.0));
    c[0].position = {0, 2050, 0};                                              // past 2000 but inside 2100
    CHECK(lock.update(c, player, 0.1));
    c[0].position = {0, 2200, 0};
    CHECK(!lock.update(c, player, 0.2) && !lock.target());
    c[0].position = {0, 1500, 0};
    lock.acquire(c, player, fwd, SelectMode::Center);
    c[0].line_of_sight = false;
    CHECK(lock.update(c, player, 1.0));                                        // grace period
    CHECK(!lock.update(c, player, 3.5));                                       // lost for > 2 s
    c[0].line_of_sight = true;
    // switching: target 1 at screen (0, 0); 2 to the right, 5 to the left and a bit up
    lock.acquire(c, player, fwd, SelectMode::Center);
    c.push_back({5, {-300, 1200, 0}});
    c[0].screen_x = 0; c[1].screen_x = 0.4f; c[1].screen_y = 0.05f; c[4].screen_x = -0.3f; c[4].screen_y = 0.1f;
    CHECK(lock.switch_target(c, player, +1, 0, 10.0) == 2u);
    CHECK(!lock.switch_target(c, player, +1, 0, 10.1));                       // cooldown, same direction
    CHECK(lock.switch_target(c, player, -1, 0, 10.1) == 1u);                  // other direction: allowed
    CHECK(lock.switch_target(c, player, -1, 0, 10.5) == 5u);
}

static void bindings() {
    const char* ini =
        "; stances (Stances / Key Utils defaults)\n"
        "[Keys]\n"
        "stance_high = 200|keyword|StanceHigh\n"
        "dodge = 56|dodge\n"
        "lock = 0x102|lock\n"
        "broken = x|event|A\n"
        "[Other]\n"
        "ignored = 1|event|B\n";
    auto b = parse_bindings(ini);
    CHECK(b.size() == 3);
    CHECK(b.size() == 3 && b[0].name == "stance_high" && b[0].key == 200 && b[0].action == "keyword" &&
          b[0].argument == "StanceHigh");
    CHECK(b.size() == 3 && b[1].action == "dodge" && b[1].argument.empty());
    CHECK(b.size() == 3 && b[2].key == 0x102);
}

static bool near(float a, float b, float eps = 1e-4f) { return std::fabs(a - b) < eps; }

static void aiming() {
    const float pi = 3.14159265f;
    Vec3 o{0, 0, 0};
    auto a = aim_angles(o, {0, 10, 0});
    CHECK(near(a.yaw, 0) && near(a.pitch, 0));
    CHECK(near(aim_angles(o, {10, 0, 0}).yaw, pi / 2));             // +X: clockwise quarter turn
    CHECK(near(aim_angles(o, {-10, 0, 0}).yaw, -pi / 2));
    CHECK(aim_angles(o, {0, 10, 10}).pitch < 0);                     // above: looking up = negative pitch
    auto f = look_forward(aim_angles({1, 2, 3}, {4, 6, 3}));
    CHECK(near(f.x, 0.6f) && near(f.y, 0.8f) && near(f.z, 0));
    CHECK(near(wrap_pi(3 * pi), pi, 1e-3f) && near(wrap_pi(-pi / 2 - 2 * pi), -pi / 2, 1e-3f));
    // steering across the +-pi seam goes the short way
    Angles cur{0, pi - 0.1f}, want{0, -pi + 0.1f};
    auto s = steer(cur, want, 0.05f, 10.0f);                         // half the gap (0.2 rad) per step
    CHECK(near(std::fabs(wrap_pi(s.yaw - cur.yaw)), 0.1f, 1e-3f));
    CHECK(near(steer(cur, want, 1.0f, 8.0f).yaw, want.yaw, 1e-3f)); // a long frame snaps, never overshoots
    CHECK(near(steer({0, 0}, {-3.0f, 0}, 1.0f, 8.0f, 2.0f, 1.2f).pitch, -1.2f));   // clamped pitch
    float x = 0, y = 0;
    view_offset({0, 0}, o, {10, 10, 0}, x, y);                       // ahead and to the right
    CHECK(x > 0 && near(y, 0));
    view_offset({0, 0}, o, {0, 10, 5}, x, y);                        // ahead and above
    CHECK(near(x, 0) && y > 0);
}

// The owner's camera probe (2026-10-23): ThirdPersonState +0x170 = (0.841, -0.067, -0.042, 0.536) with the camera
// root's forward row (-0.899, 0.412, -0.151); later (0.979, -0.075, -0.014, 0.191) with (-0.377, 0.915, -0.144).
static void lock_hold() {
    // a hard lock is steer() with rates that reach the target in one frame
    Angles cur{0.1f, 1.0f}, want{-0.2f, -2.5f};
    auto n = steer(cur, want, 1.0f / 60, 1e6f, 1e6f);
    CHECK(std::fabs(n.yaw - want.yaw) < 1e-4f && std::fabs(n.pitch - want.pitch) < 1e-4f);
    // mouse moves and the right stick are hidden; buttons and the left stick are not
    CHECK(hides_look_event(1, 0));
    CHECK(hides_look_event(4, 0x0C));
    CHECK(!hides_look_event(4, 0x0B));
    CHECK(!hides_look_event(0, 0));
    // the player's pitch carries the camera's up / down
    CHECK(lock_writes_player_pitch(true, false, true));
    CHECK(lock_writes_player_pitch(false, true, true));
    CHECK(!lock_writes_player_pitch(true, true, false));
    CHECK(!lock_writes_player_pitch(false, false, true));
    // aimed from the camera when it is near the player, from the eye otherwise
    Vec3 eye{0, 0, 1.6f}, cam{-0.6f, -2.5f, 1.8f}, far{100, 0, 0};
    auto o = aim_origin(eye, &cam);
    CHECK(o.x == cam.x && o.y == cam.y);
    o = aim_origin(eye, &far);
    CHECK(o.x == eye.x);
    o = aim_origin(eye, nullptr);
    CHECK(o.z == eye.z);
}

static void camera_quaternion() {
    const float pi = 3.14159265f;
    auto a = camera_angles({0.841f, -0.067f, -0.042f, 0.536f});
    auto f = look_forward(a);
    CHECK(near(f.x, -0.899f, 0.02f) && near(f.y, 0.412f, 0.02f) && near(f.z, -0.151f, 0.02f));
    auto b = camera_angles({0.979f, -0.075f, -0.014f, 0.191f});
    f = look_forward(b);
    CHECK(near(f.x, -0.377f, 0.02f) && near(f.y, 0.915f, 0.02f) && near(f.z, -0.144f, 0.02f));
    for (float yaw : {0.0f, 1.0f, -2.5f, 3.0f})                           // round trip
        for (float pitch : {0.0f, 0.4f, -0.6f}) {
            auto r = camera_angles(camera_quat({pitch, yaw}));
            CHECK(near(wrap_pi(r.yaw - yaw), 0.0f, 1e-3f) && near(r.pitch, pitch, 1e-3f));
        }
    auto q = camera_quat({0.0f, pi / 2});                                 // facing +X: a quarter turn clockwise
    CHECK(near(q.w * q.w + q.x * q.x + q.y * q.y + q.z * q.z, 1.0f));
}

int main() {
    camera_quaternion();
    lock_hold();
    aiming();
    payloads();
    attack_phase();
    input_buffer();
    iframes();
    dodge();
    lock_on();
    bindings();
    if (failures == 0) std::printf("all combat core tests passed\n");
    return failures;
}
