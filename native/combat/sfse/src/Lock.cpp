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
        // Dead: the kDead bit (never set on 1.16, owner's run) or Health <= 0 (ActorValueOwner::GetActorValue, a
        // virtual mapped in CommonLibSF; supported, not verified: the log prints the target's health on lock).
        std::optional<float> health;
        if (const auto* hp = HealthInfo()) health = static_cast<RE::ActorValueOwner*>(actor)->GetActorValue(*hp);
        c.alive = !combat::target_dead(actor->IsDead(), health);
        if (only && health && (!last_health_ || std::fabs(*last_health_ - *health) >= 1.0f) && health_logs_ < 20) {
            ++health_logs_;
            REX::INFO("lock-on: target {:08X} health {:.0f} (dead flag {})", actor->GetFormID(), *health, actor->IsDead());
        }
        if (only) last_health_ = health;
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
        // the handle manager only hands out live objects; the memory check (a VirtualQuery) is for the scan, not for
        // the per-frame target (owner's run: ~1 ms per frame in such checks)
        if (!a || (!only && !game::Readable(a, sizeof(RE::Actor)))) return nullptr;
        return static_cast<RE::TESObjectREFR*>(a)->IsActor() ? a : nullptr;
    };
    // Owner's run 2026-10-23: four arrays - +070 with 1238 handles (every actor the game knows: resolving them all froze
    // the game for ~3 s per press) and +060 / +080 / +090 with 21-26 (the process levels near the player). Only arrays
    // of at most kMaxArray handles are used, together, each handle once.
    constexpr std::uint32_t kMaxArray = 512;
    const auto base = reinterpret_cast<std::uintptr_t>(lists);
    if (only) {
        auto* a = resolve(*only);
        target_ref_ = RE::NiPointer<RE::Actor>(a);
        if (a) add(a);
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
    if (id && !was) {
        camera_last_.clear();                                       // a full dump at the start of each lock
        camera_logged_ = write_checks_ = 0;
        wrote_.reset();
    }
    if (id && id != locked_) {                                      // a new target eases in again
        locked_at_ = game::Now();
        acquired_ = false;
        last_health_.reset();
    }
    locked_ = id;
    if (id) REX::INFO("lock-on: target {:08X} ({})", *id, why);      // rare (key presses, deaths): always logged
    else REX::INFO("lock-on: released ({})", why);
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
    const combat::Angles look = Look();
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
    const combat::Angles look = Look();
    const auto eye = V(player->data.location, s_.eye_height);
    if (auto id = core_.switch_target(Gather(look, eye), eye, dx, dy, game::Now())) SetLocked(id, "switch");
}

// Finding Starfield's third-person camera rotation (not mapped in CommonLibSF): while locked, every 0.5 s, the camera
// root's world rotation (TESCamera +0x08 -> NiAVObject world.rotate at +0x80, 3x3 floats) and the floats of
// PlayerCamera::cameraStates[kThirdPerson] (checked against ThirdPersonState's vtable) that look like angles; after the
// first dump only the ones that changed. The owner turns the camera with the mouse meanwhile; the field that follows
// the camera's yaw is the one to steer.
void Lock::CameraProbe(double now, float player_yaw) {
    if (camera_logged_ >= s_.camera_samples || now < next_camera_) return;
    next_camera_ = now + 0.5;
    ++camera_logged_;
    auto* cam = RE::PlayerCamera::GetSingleton();
    if (!cam || !game::Readable(cam, 0x188 + 8 * RE::CameraState::kTotal)) {
        REX::INFO("camera probe: no PlayerCamera");
        return;
    }
    std::string rot = "unreadable";
    auto* root = cam->cameraRoot.get();
    if (root && game::Readable(root, 0xC0)) {
        float m[12];
        std::memcpy(m, reinterpret_cast<const std::byte*>(root) + 0x80, sizeof(m));
        rot = std::format("[{:.3f} {:.3f} {:.3f} | {:.3f} {:.3f} {:.3f} | {:.3f} {:.3f} {:.3f} | {:.3f} {:.3f} {:.3f}]",
                          m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9], m[10], m[11]);
    }
    auto* state = static_cast<std::byte*>(cam->cameraStates[RE::CameraState::kThirdPerson]);
    const auto vt = state && game::Readable(state, 8) ? *reinterpret_cast<std::uintptr_t*>(state) : 0;
    const bool is_third = vt && vt == RE::VTABLE::ThirdPersonState[0].address();
    const bool current = state && cam->currentState == state;
    std::string floats;
    constexpr std::size_t kSpan = 0x400;
    if (state && game::Readable(state, kSpan)) {
        std::vector<float> now_f(kSpan / 4);
        std::memcpy(now_f.data(), state, kSpan);
        for (std::size_t i = 2; i < now_f.size(); ++i) {
            const float v = now_f[i];
            if (!std::isfinite(v) || std::fabs(v) > 1e6f || (v != 0.0f && std::fabs(v) < 1e-4f)) continue;
            if (!camera_last_.empty() && std::fabs(camera_last_[i] - v) < 0.005f) continue;
            floats += std::format(" +{:03X}={:.3f}", i * 4, v);
        }
        camera_last_ = std::move(now_f);
    }
    REX::INFO("camera probe {}: player yaw {:.3f}; root rotation {}; third-person state {} ({}, {}):{}", camera_logged_,
              player_yaw, rot, static_cast<void*>(state), is_third ? "ThirdPersonState vtable" : "vtable not matched",
              current ? "current" : "not current", floats.empty() ? std::string(" no change") : floats);
}

namespace {
constexpr std::ptrdiff_t kThirdPersonRotation = 0x170;      // owner's camera probe, Starfield 1.16.244
constexpr std::ptrdiff_t kCameraYaw0 = 0x22C;                // three copies of the camera's yaw (radians)

}  // namespace

const RE::ActorValueInfo* Lock::HealthInfo() {
    if (!health_looked_up_) {
        health_looked_up_ = true;
        health_info_ = RE::TESForm::LookupByEditorID<RE::ActorValueInfo>(RE::BSFixedString("Health"));
        if (!health_info_) REX::WARN("lock-on: actor value 'Health' not found: dead targets are seen by the dead flag only");
    }
    return health_info_;
}

std::byte* Lock::ThirdPerson() {
    auto* cam = RE::PlayerCamera::GetSingleton();
    if (!cam) return nullptr;
    const double now = game::Now();
    // Memory checks (VirtualQuery) only when the camera or its third-person state is a new object: the owner's timing
    // lines showed 14-24 ms frames while locked when they ran every second.
    if (cam != checked_cam_) {
        if (!game::Readable(cam, 0x188 + 8 * RE::CameraState::kTotal)) return nullptr;
        checked_cam_ = cam;
        camera_state_ = nullptr;
    }
    auto* state = static_cast<std::byte*>(cam->cameraStates[RE::CameraState::kThirdPerson]);
    if (state != camera_state_ && now - camera_checked_at_ > 1.0) {
        camera_checked_at_ = now;
        camera_state_ = nullptr;
        if (!state || !game::Readable(state, kCameraYaw0 + 12)) return nullptr;
        if (*reinterpret_cast<std::uintptr_t*>(state) != RE::VTABLE::ThirdPersonState[0].address()) return nullptr;
        camera_state_ = state;
    }
    return camera_state_ && cam->currentState == camera_state_ ? camera_state_ : nullptr;
}

std::optional<combat::Angles> Lock::CameraAngles() {
    auto* state = ThirdPerson();
    if (!state) return std::nullopt;
    combat::Quat q;
    std::memcpy(&q, state + kThirdPersonRotation, sizeof(q));
    const float n = q.w * q.w + q.x * q.x + q.y * q.y + q.z * q.z;
    if (!std::isfinite(n) || std::fabs(n - 1.0f) > 0.05f) return std::nullopt;
    return combat::camera_angles(q);
}

bool Lock::SetCameraAngles(combat::Angles a, combat::Angles look) {
    auto* state = ThirdPerson();
    if (!state) return false;
    float current = 0;
    std::memcpy(&current, state + kCameraYaw0, 4);
    const float yaw = std::isfinite(current) ? combat::camera_yaw_write(current, look.yaw, a.yaw)
                                             : combat::camera_yaw_write(look.yaw, look.yaw, a.yaw);
    const auto q = combat::camera_quat(a);
    std::memcpy(state + kThirdPersonRotation, &q, sizeof(q));
    // The camera's yaw is kept as radians (clockwise from +Y, 0..2 pi) at +0x22C / +0x230 / +0x234 and the quaternion is
    // rebuilt from it (owner's write-check run 2026-10-23: a quaternion written alone was replaced next frame; these
    // three floats matched its yaw to 0.5 deg in every sample).
    for (std::ptrdiff_t off : {kCameraYaw0, kCameraYaw0 + 4, kCameraYaw0 + 8}) std::memcpy(state + off, &yaw, 4);
    wrote_ = a;
    return true;
}

combat::Angles Lock::Look() {
    if (auto a = CameraAngles()) return *a;
    auto* player = game::Player();
    return player ? combat::Angles{player->data.angle.x * s_.pitch_sign, player->data.angle.z} : combat::Angles{};
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
    const combat::Angles look = Look();
    auto eye = V(player->data.location, s_.eye_height);
    if (s_.aim_from_camera) {
        // The camera root's world position (NiAVObject world.translate, +0xB0 in CommonLibSF's layout). The crosshair
        // is on the camera's forward ray, so aiming from the player's eye leaves it beside the target (owner's run
        // 2026-10-23: "near the NPC, not on it"). Last frame's position; used only when within 10 m of the player.
        std::optional<combat::Vec3> cam_pos;
        auto* cam = RE::PlayerCamera::GetSingleton();
        auto* root = cam ? cam->cameraRoot.get() : nullptr;
        if (root && (root == camera_root_ || game::Readable(root, 0xBC))) {
            camera_root_ = root;
            const auto* t = reinterpret_cast<const float*>(reinterpret_cast<const std::byte*>(root) + 0xB0);
            cam_pos = combat::Vec3{t[0], t[1], t[2]};
        }
        const auto from = combat::aim_origin(eye, cam_pos ? &*cam_pos : nullptr);
        if (!origin_logged_ && cam_pos) {
            origin_logged_ = true;
            REX::INFO("lock-on: camera at ({:.2f}, {:.2f}, {:.2f}), player eye at ({:.2f}, {:.2f}, {:.2f}): aiming from the {}",
                      cam_pos->x, cam_pos->y, cam_pos->z, eye.x, eye.y, eye.z,
                      from.x == cam_pos->x ? "camera" : "player's eye (camera too far away)");
        }
        eye = from;
    }
    // Validity (alive, in range, handle still good) every 0.25 s; between checks only the target's position is read
    // (owner's runs: ~1 ms per frame when everything was re-resolved and re-checked each frame).
    combat::Vec3 target_pos{};
    if (now - target_checked_at_ >= 0.25 || !target_ref_) {
        target_checked_at_ = now;
        const auto h = handle_of_.find(*locked_);
        if (h == handle_of_.end()) {
            core_.release();
            SetLocked(std::nullopt, "target has no handle");
            return;
        }
        auto cands = Gather(look, eye, h->second);
        const auto self = std::find_if(cands.begin(), cands.end(), [&](const auto& c) { return c.id == *locked_; });
        const bool died = self != cands.end() && !self->alive;
        if (!core_.update(cands, eye, now)) {
            // A dead target always releases (core: !alive); checked every 0.25 s through Actor::IsDead (the kDead
            // bit, CommonLibSF's layout, not verified on 1.16: a kill that does not log "target died" means it is not).
            target_ref_.reset();
            SetLocked(std::nullopt, died ? "target died" : self == cands.end() ? "target gone" : "target lost (too far)");
            return;
        }
        if (core_.target() != locked_) SetLocked(core_.target(), "core");
        const auto it = std::find_if(cands.begin(), cands.end(), [&](const auto& c) { return c.id == *locked_; });
        if (it == cands.end() || !target_ref_) return;
    }
    target_pos = V(target_ref_->data.location, s_.target_height);
    const auto* it = &target_pos;
    auto want = combat::aim_angles(eye, target_pos);
    if (now >= next_report_ && logged_ < s_.log_targets) {      // to check the steering on the first runs
        next_report_ = now + 2.0;
        ++logged_;
        REX::INFO("lock-on: following {:08X}: distance {:.1f}, yaw error {:.0f} deg, pitch error {:.0f} deg", *locked_,
                  std::sqrt((it->x - eye.x) * (it->x - eye.x) + (it->y - eye.y) * (it->y - eye.y)),
                  combat::wrap_pi(want.yaw - look.yaw) * 57.2958f, (want.pitch - look.pitch) * 57.2958f);
    }
    if (!s_.steer_pitch) want.pitch = look.pitch;
    CameraProbe(now, player->data.angle.z);
    if (wrote_ && now >= next_write_check_ && write_checks_ < 10) {    // look = this frame's camera, after the game ran
        next_write_check_ = now + 0.5;
        ++write_checks_;
        REX::INFO("camera write check: wrote yaw {:.1f} deg last frame, now yaw {:.1f}; pitch now {:.1f} deg, target "
                  "{:.1f} deg (player look input {:.1f} deg)",
                  wrote_->yaw * 57.2958f, look.yaw * 57.2958f, look.pitch * 57.2958f, want.pitch * 57.2958f,
                  player->data.angle.x * 57.2958f);
    }
    if (!acquired_ && combat::lock_acquired(look, want, static_cast<float>(now - locked_at_), s_.acquire_time)) {
        acquired_ = true;
        REX::INFO("lock-on: on target after {:.2f} s easing", now - locked_at_);
    }
    const bool hold = s_.hard_lock && acquired_;
    const float ease = std::min(1.0f, (s_.hard_lock ? s_.acquire_rate : s_.pitch_rate) * dt);
    auto next = hold ? combat::steer(look, want, dt, 1e6f, 1e6f)
                     : combat::steer(look, want, dt, s_.hard_lock ? s_.acquire_rate : s_.yaw_rate,
                                     s_.hard_lock ? s_.acquire_rate : s_.pitch_rate);
    // Up / down goes through the player's look input (below); the camera's own pitch is rebuilt by the game, so the
    // quaternion keeps this frame's pitch instead of fighting it.
    const float pitch_step =
        combat::pitch_input(look.pitch, want.pitch, hold ? s_.pitch_gain : ease);
    next.pitch = look.pitch;
    if (s_.steer_camera && !SetCameraAngles(next, look) && !camera_warned_) {
        camera_warned_ = true;
        REX::WARN("lock-on: the third-person camera's rotation is not available (not in third person, or the layout "
                  "changed): the camera is not steered");
    }
    // Supported, not verified: the third-person camera's pitch is rebuilt from the player's pitch (Skyrim's is; no
    // pitch float changed in ThirdPersonState's first 0x400 bytes while the quaternion's pitch did, owner's probes).
    if (combat::lock_writes_player_pitch(s_.steer_camera, s_.steer_player, s_.steer_pitch))
        player->data.angle.x = pitch_step * s_.pitch_sign;
    if (s_.steer_player) player->data.angle.z = next.yaw;
}

}  // namespace s2s::sfse
