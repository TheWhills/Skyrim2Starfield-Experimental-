#include "Hooks.h"

#include "Game.h"
#include "Plugin.h"

#include "s2s/controller.h"

namespace s2s::sfse::hooks {
namespace {

// ------------------------------------------------------------------------------------------------ input
// UI's BSInputEventReceiver::PerformInputProcessing sees every input event once per frame (supported: OSF Animation
// hooks the same function for its scene controls). The hook only watches: events still reach the game unchanged.
// The vtable is read from the live UI object (its BSInputEventReceiver base, UI + 0x10 in CommonLibSF's layout), so
// no vtable index from the Address Library is needed.
using PerformInputProcessing_t = void(RE::BSInputEventReceiver*, const RE::InputEvent*);
PerformInputProcessing_t* g_input_original = nullptr;

// ThumbstickEvent is not mapped in CommonLibSF. Layout (supported: OSF Animation's in-game notes): IDEvent idCode at
// +0x30 = 0x0B left stick / 0x0C right stick, then x / y floats at +0x38 / +0x3C (-1..1).
// UNVERIFIED: y > 0 is "forward" (XInput convention). The key log shows it on the first run.
constexpr std::ptrdiff_t kStickId = 0x30, kStickX = 0x38, kStickY = 0x3C;
constexpr std::int32_t kLeftStick = 0x0B;

std::uint32_t KeyCode(const RE::ButtonEvent* e) {
    const auto id = static_cast<std::uint32_t>(e->idCode);
    switch (e->deviceType) {
        case RE::InputEvent::DeviceType::kKeyboard: return combat::key_from_vk(id);
        case RE::InputEvent::DeviceType::kMouse: return combat::key_from_mouse(id);
        case RE::InputEvent::DeviceType::kGamepad: {
            const auto code = SFSE::InputMap::GamepadMaskToKeycode(id);
            return code < SFSE::InputMap::kMaxMacros ? code : 0;
        }
        default: return 0;
    }
}

void PerformInputProcessing(RE::BSInputEventReceiver* a_this, const RE::InputEvent* a_head) {
    auto& plugin = Plugin::Get();
    for (auto* e = a_head; e; e = e->next) {
        if (e->eventType == RE::InputEvent::EventType::kButton) {
            const auto* b = static_cast<const RE::ButtonEvent*>(e);
            // Skyrim's convention (IsDown: value != 0 and held 0; IsUp: value 0 and held != 0). UNVERIFIED for
            // Starfield: the key log on the first run shows value / held for presses and releases.
            const bool down = b->value != 0.0f && b->heldDownSecs == 0.0f;
            const bool up = b->value == 0.0f && b->heldDownSecs != 0.0f;
            if (!down && !up) continue;          // held repeats
            if (b->deviceType == RE::InputEvent::DeviceType::kMouse && (b->idCode == 0x800 || b->idCode == 0x900) &&
                !down)
                continue;                        // the wheel sends a zero "release" after each notch
            const auto user = std::string_view(b->strUserEvent);
            plugin.OnButton(KeyCode(b), down, user, static_cast<std::uint32_t>(b->deviceType), b->idCode, b->value,
                            b->heldDownSecs);
        } else if (e->eventType == RE::InputEvent::EventType::kThumbstick) {
            const auto* bytes = reinterpret_cast<const std::byte*>(e);
            if (*reinterpret_cast<const std::int32_t*>(bytes + kStickId) == kLeftStick)
                plugin.OnStick(*reinterpret_cast<const float*>(bytes + kStickX),
                               *reinterpret_cast<const float*>(bytes + kStickY));
        }
    }
    // UNVERIFIED: this runs every frame, also without input (the tick depends on it). If the log shows buffered
    // attacks or i-frames that never end, move Tick to a per-frame hook (e.g. the player's update).
    plugin.Tick();
    g_input_original(a_this, a_head);
}

// ------------------------------------------------------------------------------------------------ safe reads
// Reads memory only after VirtualQuery says it is committed and readable: used for layouts CommonLibSF does not map.
bool Readable(const void* a_ptr, std::size_t a_len) {
    if (!a_ptr) return false;
    REX::W32::MEMORY_BASIC_INFORMATION mbi{};
    if (!REX::W32::VirtualQuery(a_ptr, &mbi, sizeof(mbi)) || mbi.state != REX::W32::MEM_COMMIT) return false;
    if (mbi.protect & (REX::W32::PAGE_NOACCESS | 0x100u)) return false;            // no access / guard page
    const auto ok = mbi.protect & (REX::W32::PAGE_READONLY | REX::W32::PAGE_READWRITE | REX::W32::PAGE_WRITECOPY |
                                   REX::W32::PAGE_EXECUTE_READ | REX::W32::PAGE_EXECUTE_READWRITE | 0x80u);
    const auto end = reinterpret_cast<std::uintptr_t>(mbi.baseAddress) + mbi.regionSize;
    return ok && reinterpret_cast<std::uintptr_t>(a_ptr) + a_len <= end;
}

// The BSFixedString at a_addr: nullopt when anything on the way is unreadable or not printable text, "" for an empty
// string (null entry).
std::optional<std::string> SafeText(std::uintptr_t a_addr) {
    const auto* fs = reinterpret_cast<const RE::BSFixedString*>(a_addr);
    if (!Readable(fs, sizeof(void*))) return std::nullopt;
    const auto* entry = *reinterpret_cast<void* const*>(fs);
    if (!entry) return std::string();
    if (!Readable(entry, 0x20)) return std::nullopt;
    const char* text = fs->c_str();
    std::string out;
    for (std::size_t i = 0; i < 96; ++i) {
        if (!Readable(text + i, 1)) return std::nullopt;
        const char ch = text[i];
        if (ch == '\0') return out;
        if (ch < 0x20 || ch > 0x7E) return std::nullopt;
        out.push_back(ch);
    }
    return std::nullopt;
}

// A BSFixedString at a_addr, or "" when anything on the way is not readable or not printable text.
std::string SafeFixedString(std::uintptr_t a_addr) { return SafeText(a_addr).value_or(std::string()); }

// ------------------------------------------------------------------------------------------------ animation events
// The player is a BSTEventSink<BSAnimationGraphEvent> (TESObjectREFR base at +0x50 in CommonLibSF's layout); its graph
// calls ProcessEvent (vtable slot 1) for every clip / graph event. Patching that vtable from the live player object
// affects only the player's class. BSAnimationGraphEvent is not mapped in CommonLibSF.
// The layout is found at run time (Probe below): Skyrim's (holder, tag, payload) did not hold in Starfield.

using Sink = RE::BSTEventSink<RE::BSAnimationGraphEvent>;
using ProcessEvent_t = RE::BSEventNotifyControl(Sink*, const RE::BSAnimationGraphEvent&,
                                                RE::BSTEventSource<RE::BSAnimationGraphEvent>*);
ProcessEvent_t* g_event_original = nullptr;
constexpr std::ptrdiff_t kAnimSinkOffset = 0x50;

std::string_view View(const RE::BSFixedString& s) {
    const char* p = s.c_str();
    return p ? std::string_view(p) : std::string_view();
}

// Layout probe (owner's first run, 2026-10-21: Skyrim's holder / tag / payload order did not hold, the first field was
// not the player). Only PlayerCharacter's vtable is patched, so every event here is the player's. For the first events
// each 8-byte slot is classified with memory checks (Self / name / empty string / other) and logged; the core's
// LayoutProbe settles on the tag and payload slots once 3 events in a row agree, then events are read from there.
constexpr int kProbeSlots = 8, kProbeLogged = 8;
std::mutex g_probe_lock;
combat::LayoutProbe g_probe;
int g_probe_count = 0;
std::atomic_int g_state{0};                       // 0 probing, 1 found, -1 given up
std::atomic<std::ptrdiff_t> g_tag_off{-1}, g_payload_off{-1};

void Probe(std::uintptr_t ev, const void* self, const void* as_holder) {
    std::lock_guard lock(g_probe_lock);
    if (g_state.load() != 0) return;
    std::vector<combat::LayoutProbe::Slot> slots;
    std::string line;
    const bool readable = Readable(reinterpret_cast<const void*>(ev), kProbeSlots * 8);
    for (int i = 0; readable && i < kProbeSlots; ++i) {
        const auto addr = ev + static_cast<std::uintptr_t>(i) * 8;
        const auto value = *reinterpret_cast<const std::uintptr_t*>(addr);
        using S = combat::LayoutProbe::Slot;
        S kind = S::Other;
        std::string shown = std::format("{:X}", value);
        if (value && (reinterpret_cast<const void*>(value) == self || reinterpret_cast<const void*>(value) == as_holder)) {
            kind = S::Self;
            shown = "SELF";
        } else if (auto text = SafeText(addr)) {
            kind = text->empty() ? S::EmptyText : S::Text;
            shown = "'" + *text + "'";
        }
        slots.push_back(kind);
        line += std::format(" +{:02X}={}", i * 8, shown);
    }
    if (g_probe_count++ < kProbeLogged) REX::INFO("anim probe:{}", readable ? line : std::string(" event not readable"));
    switch (g_probe.feed(slots)) {
        case combat::LayoutProbe::State::Found:
            g_tag_off = g_probe.tag() * 8;
            g_payload_off = g_probe.payload() < 0 ? -1 : g_probe.payload() * 8;
            g_state = 1;
            REX::INFO("animation event layout found: tag +{:02X}, payload {}, holder {}", g_tag_off.load(),
                      g_probe.payload() < 0 ? std::string("none") : std::format("+{:02X}", g_payload_off.load()),
                      g_probe.holder() < 0 ? std::string("not seen") : std::format("+{:02X}", g_probe.holder() * 8));
            break;
        case combat::LayoutProbe::State::Failed:
            g_state = -1;
            Plugin::Get().DisableAnimEvents("no consistent event name slot in the first events: BSAnimationGraphEvent "
                                            "layout unknown (the 'anim probe' lines show what was there)");
            break;
        default: break;
    }
}

RE::BSEventNotifyControl ProcessEvent(Sink* a_this, const RE::BSAnimationGraphEvent& a_event,
                                      RE::BSTEventSource<RE::BSAnimationGraphEvent>* a_source) {
    const auto ev = reinterpret_cast<std::uintptr_t>(&a_event);
    const int state = g_state.load();
    if (state == 0) {
        const auto* self = reinterpret_cast<const RE::TESObjectREFR*>(reinterpret_cast<std::uintptr_t>(a_this) -
                                                                      kAnimSinkOffset);
        // the holder may be stored as the player or as its IAnimationGraphManagerHolder base (+0x60): both count
        const auto* as_holder = static_cast<const void*>(static_cast<const RE::IAnimationGraphManagerHolder*>(self));
        Probe(ev, self, as_holder);
    } else if (state == 1) {
        const auto tag = View(*reinterpret_cast<const RE::BSFixedString*>(ev + g_tag_off.load()));
        const auto poff = g_payload_off.load();
        const auto payload = poff < 0 ? std::string_view() : View(*reinterpret_cast<const RE::BSFixedString*>(ev + poff));
        Plugin::Get().OnAnimEvent(tag, payload);
    }
    return g_event_original(a_this, a_event, a_source);
}

// ------------------------------------------------------------------------------------------------ hits
// BGSAttackData is not mapped in CommonLibSF. Fallout 4's layout (NiRefObject 0x10, then BSFixedString event) is the
// UNVERIFIED guess: the attack event name (MeleeAttackStart / MeleeAttackPowerStart ...) tells normal from power
// attacks. Read with SafeFixedString, so a wrong guess only logs an empty name.
constexpr std::ptrdiff_t kAttackDataEvent = 0x10;

class HitSink : public RE::BSTEventSink<RE::TESHitEvent> {
public:
    RE::BSEventNotifyControl ProcessEvent(const RE::TESHitEvent& a_event,
                                          RE::BSTEventSource<RE::TESHitEvent>*) override {
        auto* player = game::Player();
        if (!player || a_event.target.get() != player) return RE::BSEventNotifyControl::kContinue;
        const auto attack = a_event.hitData.attackData;
        const std::string event = attack ? SafeFixedString(static_cast<std::uintptr_t>(attack) + kAttackDataEvent) : "";
        const auto* cause = a_event.cause.get();
        Plugin::Get().OnHit(event, cause ? cause->GetFormID() : 0, a_event.sourceFormID);
        return RE::BSEventNotifyControl::kContinue;
    }
};
HitSink g_hit_sink;

// Menu open / close (CommonLibSF maps MenuOpenCloseEvent: name, opening): input gating in Plugin::OnButton.
class MenuSink : public RE::BSTEventSink<RE::MenuOpenCloseEvent> {
public:
    RE::BSEventNotifyControl ProcessEvent(const RE::MenuOpenCloseEvent& a_event,
                                          RE::BSTEventSource<RE::MenuOpenCloseEvent>*) override {
        Plugin::Get().OnMenu(View(a_event.menuName), a_event.opening);
        return RE::BSEventNotifyControl::kContinue;
    }
};
MenuSink g_menu_sink;

}  // namespace

bool Install() {
    static bool installed = false;
    if (installed) return true;

    auto* ui = RE::UI::GetSingleton();
    auto* player = game::Player();
    if (!ui || !player) {
        REX::ERROR("hooks: UI {} / player {} not ready", static_cast<void*>(ui), static_cast<void*>(player));
        return false;
    }

    auto* receiver = static_cast<RE::BSInputEventReceiver*>(ui);
    REL::Relocation<std::uintptr_t> input_vtbl{*reinterpret_cast<std::uintptr_t*>(receiver)};
    g_input_original = reinterpret_cast<PerformInputProcessing_t*>(input_vtbl.write_vfunc(1, &PerformInputProcessing));

    auto* sink = reinterpret_cast<Sink*>(reinterpret_cast<std::uintptr_t>(player) + kAnimSinkOffset);
    REL::Relocation<std::uintptr_t> sink_vtbl{*reinterpret_cast<std::uintptr_t*>(sink)};
    g_event_original = reinterpret_cast<ProcessEvent_t*>(sink_vtbl.write_vfunc(1, &ProcessEvent));

    ui->RegisterSink<RE::MenuOpenCloseEvent>(&g_menu_sink);
    // CommonLibSF (9d090c4, its latest as of 2026-10-21) has no Address Library ID for this on Starfield 1.16: ID 0, and
    // calling it stops the game with "Failed to find offset for Address Library ID ... Invalid ID: 0" (owner's first run).
    if constexpr (RE::ID::TESHitEvent::GetEventSource.id() != 0) {
        if (auto* hits = RE::TESHitEvent::GetEventSource()) hits->RegisterSink(&g_hit_sink);
        else REX::WARN("no TESHitEvent source: hit handling off");
    } else {
        REX::WARN("hit events: TESHitEvent::GetEventSource is not mapped for this game version in CommonLibSF (ID 0): "
                  "hit handling off; the player's own animation events (logged) show hits instead");
    }

    installed = true;
    REX::INFO("hooks installed: input receiver vtable {:X}, player animation sink vtable {:X}", input_vtbl.address(),
              sink_vtbl.address());
    return true;
}

}  // namespace s2s::sfse::hooks
