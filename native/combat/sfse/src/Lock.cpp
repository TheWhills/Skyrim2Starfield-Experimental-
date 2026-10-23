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

std::vector<combat::Candidate> Lock::Gather(combat::Angles look, combat::Vec3 eye, std::optional<std::uint32_t> only) {
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
    // 1. the high-process actor array. CommonLibSF's ProcessLists +0x58 was always empty on 1.16 (owner's runs), so the
    //    array is looked for at run time: every plausible handle array in the object, the one with the most actors wins
    //    (re-scanned at most every 2 s while nothing is found). Handles resolve through BSPointerHandleManager (mapped).
    auto* lists = RE::ProcessLists::GetSingleton();
    auto readable = [](const void* p, std::size_t n) { return game::Readable(p, n); };
    auto resolve = [&](std::uint32_t raw) -> RE::Actor* {
        RE::BSPointerHandle<RE::Actor> h;
        static_assert(sizeof(h) == sizeof(raw));
        std::memcpy(&h, &raw, sizeof(raw));
        auto ptr = h.get();
        auto* a = ptr.get();
        if (!a || !game::Readable(a, sizeof(RE::Actor))) return nullptr;
        return static_cast<RE::TESObjectREFR*>(a)->IsActor() ? a : nullptr;
    };
    // Owner's run 2026-10-23: four arrays - +070 with 1238 handles (every actor the game knows: resolving them all froze
    // the game for ~3 s per press) and +060 / +080 / +090 with 21-26 (the process levels near the player). Only arrays
    // of at most kMaxArray handles are used, together, each handle once.
    constexpr std::uint32_t kMaxArray = 512;
    const auto base = reinterpret_cast<std::uintptr_t>(lists);
    if (only) {
        if (auto* a = resolve(*only)) add(a);
        return out;
    }
    if (lists && game::Readable(lists, 0x300)) {
        std::vector<std::uint32_t> handles;
        for (const auto& at : actors_at_) {
            auto part = combat::read_handle_array(base, at, readable);
            if (part.size() <= kMaxArray) handles.insert(handles.end(), part.begin(), part.end());
        }
        if (handles.empty() && game::Now() >= next_scan_) {
            next_scan_ = game::Now() + 2.0;
            auto found = combat::scan_handle_arrays(base, 0x300, readable, [&](std::uint32_t raw) {
                auto* a = resolve(raw);
                return a && a != player;
            });
            actors_at_.clear();
            std::string list;
            for (const auto& f : found) {
                const bool use = f.size <= kMaxArray;
                list += std::format(" +{:03X}{} size {} actors {}{};", f.offset, f.data_first ? " (data first)" : "",
                                    f.size, f.actors, use ? "" : " (too big, not used)");
                if (use) actors_at_.push_back(f);
            }
            if (scans_logged_ < 5) {
                ++scans_logged_;
                REX::INFO("lock-on: actor arrays in ProcessLists:{}", list.empty() ? std::string(" none found") : list);
            }
            for (const auto& at : actors_at_) {
                auto part = combat::read_handle_array(base, at, readable);
                handles.insert(handles.end(), part.begin(), part.end());
            }
        }
        std::sort(handles.begin(), handles.end());
        handles.erase(std::unique(handles.begin(), handles.end()), handles.end());
        handle_of_.clear();
        for (auto raw : handles)
            if (auto* a = resolve(raw)) {
                handle_of_[a->GetFormID()] = raw;
                add(a);
            }
    }
    // 2. fallback: the actors placed in the player's own cell (interiors: the whole room; exteriors: one cell only).
    //    Owner's fifth run: ForEachReference crashed the game (TESObjectCELL's layout on 1.16 is not CommonLibSF's, like
    //    ProcessLists'). Now read without the cell lock and with every step checked; a list that does not look like one
    //    switches the fallback off (logged once).
    int from_cell = 0;
    std::string cell_note = "not needed";
    if (out.empty() && player->parentCell && !cell_list_bad_) {
        const auto& refs = player->parentCell->references;
        const auto* data = refs.data();
        const auto n = refs.size(), cap = refs.capacity();
        const bool plausible = game::Readable(&refs, sizeof(refs)) && n <= cap && cap < 400000 &&
                               (n == 0 || game::Readable(data, std::size_t(n) * sizeof(void*)));
        if (!plausible) {
            cell_list_bad_ = true;
            cell_note = std::format("does not look like a list (size {}, capacity {}): fallback off", n, cap);
        } else {
            std::vector<RE::TESObjectREFR*> snapshot;
            for (std::uint32_t i = 0; i < n; ++i) snapshot.push_back(data[i].get());
            int unreadable = 0;
            for (auto* ref : snapshot) {
                if (!ref || !game::Readable(ref, sizeof(RE::TESObjectREFR))) {
                    ++unreadable;
                    continue;
                }
                if (!ref->IsActor() || ref->IsDisabled() || ref->IsDeleted()) continue;
                if (!game::Readable(ref, sizeof(RE::Actor))) {
                    ++unreadable;
                    continue;
                }
                add(static_cast<RE::Actor*>(ref));
                ++from_cell;
            }
            cell_note = std::format("{} references, {} unreadable, {} actors", n, unreadable, from_cell);
            if (n > 0 && unreadable * 2 > static_cast<int>(n)) {
                cell_list_bad_ = true;
                out.clear();
                cell_note += ": mostly unreadable, fallback off";
            }
        }
    }
    if (!diagnosed_ || cell_list_bad_ != cell_bad_logged_) {
        diagnosed_ = true;
        cell_bad_logged_ = cell_list_bad_;
        REX::INFO("lock-on lists: ProcessLists {} (actor array {}), {} candidates; player's cell: {}",
                  lists ? "found" : "missing",
                  actors_at_.empty() ? std::string("not found") : std::format("{} arrays", actors_at_.size()), out.size(),
                  cell_note);
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
            // the nearest few, to check the distance units (fMaxDistance is taken as metres) and the screen test
            std::vector<std::pair<float, const combat::Candidate*>> near;
            for (const auto& c : cands)
                near.emplace_back(std::sqrt((c.position.x - eye.x) * (c.position.x - eye.x) +
                                            (c.position.y - eye.y) * (c.position.y - eye.y)), &c);
            std::sort(near.begin(), near.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
            std::string list;
            for (std::size_t i = 0; i < near.size() && i < 4; ++i)
                list += std::format(" {:08X} at {:.1f} (alive {}, screen {:.2f} / {:.2f});", near[i].second->id,
                                    near[i].first, near[i].second->alive, near[i].second->screen_x,
                                    near[i].second->screen_y);
            REX::INFO("lock-on: no target among {} nearby actors (max distance {}); nearest:{}", cands.size(),
                      s_.max_distance, list.empty() ? std::string(" none") : list);
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
    const auto h = handle_of_.find(*locked_);
    if (h == handle_of_.end()) {
        core_.release();
        SetLocked(std::nullopt, "target has no handle");
        return;
    }
    auto cands = Gather(look, eye, h->second);
    if (!core_.update(cands, eye, now)) {
        SetLocked(std::nullopt, "target lost (dead, too far or gone)");
        return;
    }
    if (core_.target() != locked_) SetLocked(core_.target(), "core");
    const auto it = std::find_if(cands.begin(), cands.end(), [&](const auto& c) { return c.id == *locked_; });
    if (it == cands.end()) return;
    auto want = combat::aim_angles(eye, it->position);
    if (now >= next_report_ && logged_ < s_.log_targets) {      // to check the steering on the first runs
        next_report_ = now + 2.0;
        ++logged_;
        REX::INFO("lock-on: following {:08X}: distance {:.1f}, yaw error {:.0f} deg, pitch error {:.0f} deg", *locked_,
                  std::sqrt((it->position.x - eye.x) * (it->position.x - eye.x) +
                            (it->position.y - eye.y) * (it->position.y - eye.y)),
                  combat::wrap_pi(want.yaw - look.yaw) * 57.2958f, (want.pitch - look.pitch) * 57.2958f);
    }
    if (!s_.steer_pitch) want.pitch = look.pitch;
    const auto next = combat::steer(look, want, dt, s_.yaw_rate, s_.pitch_rate);
    // UNVERIFIED: writing the angle directly is enough for the player and the camera to turn (Skyrim's lock-on mods
    // do this on PlayerCharacter). Mouse look still adds on top; a lock that fights the mouse is expected for now.
    player->data.angle.z = next.yaw;
    if (s_.steer_pitch) player->data.angle.x = next.pitch * s_.pitch_sign;
}

}  // namespace s2s::sfse
