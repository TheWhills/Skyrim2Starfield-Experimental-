#include "Lock.h"

#include "Game.h"

namespace s2s::sfse {
namespace {

combat::Vec3 V(const RE::NiPoint3& p, float dz = 0.0f) { return {p.x, p.y, p.z + dz}; }

}  // namespace

Lock& Lock::Get() {
    static Lock instance;
    return instance;
}

void Lock::Configure(const LockSettings& s) {
    s_ = s;
    combat::LockOnConfig cfg;
    cfg.max_distance = s.max_distance;
    cfg.hostile_only = s.hostile_only;
    core_ = combat::LockOn(cfg);
    locked_.reset();
}

std::vector<combat::Candidate> Lock::Gather(combat::Angles look, combat::Vec3 eye) {
    std::vector<combat::Candidate> out;
    auto* player = game::Player();
    if (!player) return out;
    auto add = [&](RE::Actor* actor) {
        if (!actor || actor == player) return;
        combat::Candidate c;
        c.id = actor->GetFormID();
        c.position = V(actor->data.location, s_.target_height);
        c.alive = !actor->IsDead();
        // Actor::IsHostileToActor has no Address Library ID for Starfield 1.16 in CommonLibSF (ID 0: calling it stops
        // the game). Until it does, every living actor counts as hostile (bHostileOnly has no effect), logged once.
        if constexpr (RE::ID::Actor::IsHostileToActor.id() != 0) {
            c.hostile = actor->IsHostileToActor(player);
        } else {
            static bool told = false;
            if (!told) {
                told = true;
                REX::WARN("lock-on: IsHostileToActor not mapped for this game version (ID 0): any living actor can be locked");
            }
            c.hostile = true;
        }
        // TODO (PC): line of sight (a ray cast) and visibility; until then every actor counts as seen.
        view_offset(look, eye, c.position, c.screen_x, c.screen_y);
        c.on_screen = std::fabs(c.screen_x) < 1.0f && std::fabs(c.screen_y) < 0.8f;
        c.under_crosshair = std::fabs(c.screen_x) < 0.05f && std::fabs(c.screen_y) < 0.08f;
        out.push_back(c);
    };
    // 1. the high-process actor list (CommonLibSF: ProcessLists +0x58). Owner's run 2026-10-21: always empty, so the
    //    layout may differ on 1.16; the counts are logged once below.
    auto* lists = RE::ProcessLists::GetSingleton();
    if (lists) {
        for (const auto& handle : lists->highActorHandles) {
            auto actor = handle.get();
            add(actor.get());
        }
    }
    // 2. fallback: the actors placed in the player's own cell (interiors: the whole room; exteriors: one cell only)
    int from_cell = 0;
    if (out.empty() && player->parentCell) {
        player->parentCell->ForEachReference([&](const RE::NiPointer<RE::TESObjectREFR>& ref) {
            if (ref && ref->IsActor() && !ref->IsDisabled() && !ref->IsDeleted()) {
                add(static_cast<RE::Actor*>(ref.get()));
                ++from_cell;
            }
            return RE::BSContainer::ForEachResult::kContinue;
        });
    }
    if (!diagnosed_) {
        diagnosed_ = true;
        REX::INFO("lock-on lists: ProcessLists {} (numberHighActors {}, high {}, low {}, middle-high {}, middle-low {}); "
                  "actors in the player's cell {}",
                  lists ? "found" : "missing", lists ? lists->numberHighActors : -1,
                  lists ? lists->highActorHandles.size() : 0, lists ? lists->lowActorHandles.size() : 0,
                  lists ? lists->middleHighActorHandles.size() : 0, lists ? lists->middleLowActorHandles.size() : 0,
                  from_cell);
    }
    return out;
}

void Lock::SetLocked(std::optional<std::uint32_t> id, const char* why) {
    const bool was = locked_.has_value();
    locked_ = id;
    if (logged_ < s_.log_targets) {
        ++logged_;
        if (id) REX::INFO("lock-on: target {:08X} ({})", *id, why);
        else REX::INFO("lock-on: released ({})", why);
    }
    if (was != locked_.has_value() && !s_.lock_variable.empty())
        game::SetVariable({combat::VariableSet::Type::Bool, s_.lock_variable, locked_ ? 1.0 : 0.0});
}

void Lock::Toggle() {
    auto* player = game::Player();
    if (!player) return;
    if (locked_) {
        core_.release();
        SetLocked(std::nullopt, "key");
        return;
    }
    const combat::Angles look{player->data.angle.x * s_.pitch_sign, player->data.angle.z};
    const auto eye = V(player->data.location, s_.eye_height);
    auto cands = Gather(look, eye);
    auto id = core_.acquire(cands, eye, combat::look_forward(look), combat::SelectMode::Combined);
    if (!id) {
        if (logged_ < s_.log_targets) {
            ++logged_;
            REX::INFO("lock-on: no target among {} nearby actors (max distance {})", cands.size(), s_.max_distance);
        }
        return;
    }
    for (const auto& c : cands)
        if (c.id == *id && logged_ < s_.log_targets)
            REX::INFO("lock-on: distance {:.1f} (check the units: metres expected), hostile {}",
                      std::sqrt((c.position.x - eye.x) * (c.position.x - eye.x) +
                                (c.position.y - eye.y) * (c.position.y - eye.y)),
                      c.hostile);
    SetLocked(id, "key");
}

void Lock::Switch(int dx, int dy) {
    auto* player = game::Player();
    if (!player || !locked_) return;
    const combat::Angles look{player->data.angle.x * s_.pitch_sign, player->data.angle.z};
    const auto eye = V(player->data.location, s_.eye_height);
    if (auto id = core_.switch_target(Gather(look, eye), eye, dx, dy, game::Now())) SetLocked(id, "switch");
}

void Lock::Update() {
    const double now = game::Now();
    const float dt = last_ < 0 ? 0.0f : static_cast<float>(std::min(0.1, now - last_));
    last_ = now;
    if (!locked_) return;
    auto* player = game::Player();
    if (!player || !player->parentCell) {
        core_.release();
        SetLocked(std::nullopt, "no player in a cell");
        return;
    }
    const combat::Angles look{player->data.angle.x * s_.pitch_sign, player->data.angle.z};
    const auto eye = V(player->data.location, s_.eye_height);
    auto cands = Gather(look, eye);
    if (!core_.update(cands, eye, now)) {
        SetLocked(std::nullopt, "target lost (dead, too far or gone)");
        return;
    }
    if (core_.target() != locked_) SetLocked(core_.target(), "core");
    const auto it = std::find_if(cands.begin(), cands.end(), [&](const auto& c) { return c.id == *locked_; });
    if (it == cands.end()) return;
    auto want = combat::aim_angles(eye, it->position);
    if (!s_.steer_pitch) want.pitch = look.pitch;
    const auto next = combat::steer(look, want, dt, s_.yaw_rate, s_.pitch_rate);
    // UNVERIFIED: writing the angle directly is enough for the player and the camera to turn (Skyrim's lock-on mods
    // do this on PlayerCharacter). Mouse look still adds on top; a lock that fights the mouse is expected for now.
    player->data.angle.z = next.yaw;
    if (s_.steer_pitch) player->data.angle.x = next.pitch * s_.pitch_sign;
}

}  // namespace s2s::sfse
