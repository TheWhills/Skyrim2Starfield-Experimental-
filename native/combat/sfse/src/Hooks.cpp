#include "Hooks.h"

#include "Game.h"
#include "Plugin.h"
#include "Lock.h"

#include "s2s/controller.h"

namespace s2s::sfse::hooks {
namespace {

// ------------------------------------------------------------------------------------------------ timing
// The plugin's own time, to tell its share of a stutter: per frame (input + tick) and per animation event. Reported
// every 10 s for iPerfSeconds after the hooks are installed.
struct Perf {
    std::atomic<std::uint64_t> n{0}, total_us{0}, max_us{0};
    void add(std::chrono::steady_clock::time_point t0) {
        const auto us = static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - t0).count());
        ++n;
        total_us += us;
        auto m = max_us.load();
        while (us > m && !max_us.compare_exchange_weak(m, us)) {}
    }
    std::string take() {
        const auto count = n.exchange(0), total = total_us.exchange(0), mx = max_us.exchange(0);
        return std::format("{} calls, avg {} us, max {} us", count, count ? total / count : 0, mx);
    }
};
Perf g_perf_frame, g_perf_event;
std::chrono::steady_clock::time_point g_perf_start, g_perf_last;

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
    const auto t0 = std::chrono::steady_clock::now();
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
            // The return value (hide this key) is acted on in ControlsInput below: UI is not where the game's
            // controls read the key (owner 2026-10-23: zeroing the event here did not stop the queued power attack).
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
    g_perf_frame.add(t0);
    const auto limit = std::chrono::seconds(plugin.settings().perf_seconds);
    if (t0 - g_perf_start < limit + std::chrono::seconds(1) && t0 - g_perf_last >= std::chrono::seconds(10)) {
        g_perf_last = t0;
        REX::INFO("timing (the plugin's own work): per frame {}; per animation event {}", g_perf_frame.take(),
                  g_perf_event.take());
    }
    g_input_original(a_this, a_head);
}

// ------------------------------------------------------------------------------------------------ player controls
// PlayerControls::Manager is the game's own gameplay input receiver (attacks, movement); like UI it is a
// BSInputEventReceiver and gets the frame's events through PerformInputProcessing (slot 1). Its vtables come from the
// Address Library (RE::VTABLE::PlayerControls__Manager, 9 for its bases); which one is the BSInputEventReceiver base
// is read from the class's RTTI at run time, so a wrong guess is logged instead of patched.
// The power attack key pressed during a combo (Controller::hides_power_press), its repeats and its release are
// unlinked from the list this receiver gets, and linked back right after: the game's controls never see the press, so
// they do not queue the standing power attack; UI and everyone else still get every event.
// Supported, not verified: Fallout 4's PlayerControls is a BSInputEventReceiver that reads attacks this way.
PerformInputProcessing_t* g_controls_original = nullptr;
bool g_hiding_power_key = false;                  // a press was hidden: hide its repeats and release too

bool HideFromControls(Plugin& plugin, const RE::InputEvent* e) {
    // While locked on, mouse look and the right stick are kept from the controls so they do not pull the camera off
    // the target between the lock's writes (owner's run 2026-10-23: the view slid away and back). Supported, not
    // verified: the controls' look handler turns the third-person camera, as Skyrim's LookHandler does.
    if (e->eventType != RE::InputEvent::EventType::kButton) {
        if (!Lock::Get().BlocksLook()) return false;
        const auto type = static_cast<std::uint32_t>(e->eventType);
        const auto stick = e->eventType == RE::InputEvent::EventType::kThumbstick
                               ? *reinterpret_cast<const std::int32_t*>(reinterpret_cast<const std::byte*>(e) + kStickId)
                               : 0;
        return combat::hides_look_event(type, stick);
    }
    const auto* b = static_cast<const RE::ButtonEvent*>(e);
    const auto key = KeyCode(b);
    if (key == 0 || key != plugin.PowerKey()) return false;
    const bool down = b->value != 0.0f && b->heldDownSecs == 0.0f;
    if (down) g_hiding_power_key = plugin.HidesPowerPress(key);
    const bool hide = g_hiding_power_key;
    if (b->value == 0.0f) g_hiding_power_key = false;          // released
    return hide;
}

void ControlsInput(RE::BSInputEventReceiver* a_this, const RE::InputEvent* a_head) {
    auto& plugin = Plugin::Get();
    const RE::InputEvent* head = a_head;
    std::vector<std::pair<RE::InputEvent*, RE::InputEvent*>> relink;     // (event, its original next)
    RE::InputEvent* prev = nullptr;
    for (auto* e = a_head; e; e = e->next) {
        if (HideFromControls(plugin, e)) {
            if (prev) {
                relink.emplace_back(prev, prev->next);
                prev->next = e->next;
            } else {
                head = e->next;
            }
            if (e->eventType == RE::InputEvent::EventType::kButton) plugin.NoteHiddenKey();
        } else {
            prev = const_cast<RE::InputEvent*>(e);
        }
    }
    g_controls_original(a_this, head);
    for (auto it = relink.rbegin(); it != relink.rend(); ++it) it->first->next = it->second;
}

void InstallControls() {
    std::vector<std::uintptr_t> vtables;
    for (const auto& id : RE::VTABLE::PlayerControls__Manager) vtables.push_back(id.address());
    auto found = combat::rtti_base_vtable(vtables, ".?AVBSInputEventReceiver@@",
                                          [](const void* p, std::size_t n) { return game::Readable(p, n); });
    if (!found) {
        REX::WARN("player controls: no BSInputEventReceiver vtable found in PlayerControls::Manager's RTTI: the power "
                  "attack key mid-combo still reaches the game (it may play its standing power attack afterwards)");
        return;
    }
    REL::Relocation<std::uintptr_t> vtbl{found->vtable};
    g_controls_original = reinterpret_cast<PerformInputProcessing_t*>(vtbl.write_vfunc(1, &ControlsInput));
    REX::INFO("player controls: input receiver hooked ({} vtable {} of {}, {:X})", found->complete_class, found->index,
              vtables.size(), found->vtable);
}

// ------------------------------------------------------------------------------------------------ safe reads
bool Readable(const void* a_ptr, std::size_t a_len) { return game::Readable(a_ptr, a_len); }

// The BSFixedString at a_addr: nullopt when anything on the way is unreadable or not printable text, "" for an empty
// string (null entry).
std::optional<std::string> SafeText(std::uintptr_t a_addr) {
    return combat::pool_string_at(a_addr, [](const void* p, std::size_t n) { return Readable(p, n); });
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
        // Plain reads: both slots held real strings in every event of the owner's runs. The checked reads (VirtualQuery
        // on the animation threads, several per event) were the likely cause of the stutter in the second run.
        const auto t0 = std::chrono::steady_clock::now();
        const auto tag = View(*reinterpret_cast<const RE::BSFixedString*>(ev + g_tag_off.load()));
        const auto poff = g_payload_off.load();
        const auto payload = poff < 0 ? std::string_view() : View(*reinterpret_cast<const RE::BSFixedString*>(ev + poff));
        if (!tag.empty()) Plugin::Get().OnAnimEvent(tag, payload);
        g_perf_event.add(t0);
    }
    return g_event_original(a_this, a_event, a_source);
}

// ------------------------------------------------------------------------------------------------ hits
// BGSAttackData is not mapped in CommonLibSF. Fallout 4's layout (NiRefObject 0x10, then BSFixedString event) is the
// UNVERIFIED guess: the attack event name (MeleeAttackStart / MeleeAttackPowerStart ...) tells normal from power
// attacks. Read with SafeFixedString, so a wrong guess only logs an empty name.
constexpr std::ptrdiff_t kAttackDataEvent = 0x10;

int g_any_hits_logged = 0;

// The TESHitEvent layout is not CommonLibSF's on 1.16 (owner's run 2026-10-25: target / cause at +F0 / +F8 read null
// on every event). Until it is known, each event's first 0x140 bytes are searched: 8-byte slots pointing at objects
// whose RTTI class is an actor (Actor / PlayerCharacter), in order, and 4-byte slots that resolve as reference handles
// to actors. The first actor found is taken as the target and the next as the attacker (CommonLibSF's order:
// HitData's aggressor handle comes before its target handle, the event's target pointer before its cause), and the
// first events are logged slot by slot to fix the layout.
struct ActorSlot { std::ptrdiff_t offset; bool handle; RE::Actor* actor; };

std::vector<ActorSlot> ActorSlots(const void* event, std::size_t span) {
    std::vector<ActorSlot> out;
    const auto base = reinterpret_cast<std::uintptr_t>(event);
    if (!game::Readable(event, span)) return out;
    auto readable = [](const void* p, std::size_t n) { return game::Readable(p, n); };
    for (std::size_t off = 0; off + 8 <= span; off += 8) {
        std::uintptr_t v = 0;
        std::memcpy(&v, reinterpret_cast<const void*>(base + off), 8);
        if (v < 0x10000 || (v & 7) || !game::Readable(reinterpret_cast<const void*>(v), 8)) continue;
        std::uintptr_t vt = 0;
        std::memcpy(&vt, reinterpret_cast<const void*>(v), 8);
        const auto cls = combat::rtti_class_name(vt, readable);
        if (cls == ".?AVActor@@" || cls == ".?AVPlayerCharacter@@")
            out.push_back({static_cast<std::ptrdiff_t>(off), false, reinterpret_cast<RE::Actor*>(v)});
    }
    for (std::size_t off = 0; off + 4 <= span; off += 4) {
        std::uint32_t raw = 0;
        std::memcpy(&raw, reinterpret_cast<const void*>(base + off), 4);
        if (raw == 0 || raw == 0xFFFFFFFFu) continue;
        RE::BSPointerHandle<RE::Actor> h;
        std::memcpy(&h, &raw, 4);
        auto ptr = h.get();
        auto* a = ptr.get();
        if (a && static_cast<RE::TESObjectREFR*>(a)->IsActor())
            out.push_back({static_cast<std::ptrdiff_t>(off), true, a});
    }
    return out;
}

class HitSink : public RE::BSTEventSink<RE::TESHitEvent> {
public:
    RE::BSEventNotifyControl ProcessEvent(const RE::TESHitEvent& a_event,
                                          RE::BSTEventSource<RE::TESHitEvent>*) override {
        auto* player = game::Player();
        if (!player) return RE::BSEventNotifyControl::kContinue;
        RE::Actor* target = nullptr;
        RE::Actor* cause = nullptr;
        if (auto* t = a_event.target.get()) {                         // CommonLibSF's layout, if it ever matches
            target = t->IsActor() ? static_cast<RE::Actor*>(t) : nullptr;
            auto* c = a_event.cause.get();
            cause = c && c->IsActor() ? static_cast<RE::Actor*>(c) : nullptr;
        } else {
            const auto slots = ActorSlots(&a_event, 0x140);
            std::vector<RE::Actor*> pointers;
            for (const auto& sl : slots)
                if (!sl.handle && std::find(pointers.begin(), pointers.end(), sl.actor) == pointers.end())
                    pointers.push_back(sl.actor);
            if (!pointers.empty()) target = pointers[0];
            if (pointers.size() > 1) cause = pointers[1];
            if (g_any_hits_logged < 6) {
                ++g_any_hits_logged;
                std::string list;
                for (const auto& sl : slots)
                    list += std::format(" +{:03X}{}={:08X}{}", sl.offset, sl.handle ? "(handle)" : "",
                                        sl.actor->GetFormID(), sl.actor == player ? "(player)" : "");
                REX::INFO("hit event slots:{} -> target {:08X}, attacker {:08X}", list.empty() ? std::string(" none") : list,
                          target ? target->GetFormID() : 0, cause ? cause->GetFormID() : 0);
            }
        }
        if (target != player) return RE::BSEventNotifyControl::kContinue;
        const auto attack = a_event.hitData.attackData;
        const std::string event = attack ? SafeFixedString(static_cast<std::uintptr_t>(attack) + kAttackDataEvent) : "";
        Plugin::Get().OnHit(event, cause ? cause->GetFormID() : 0, a_event.sourceFormID);
        return RE::BSEventNotifyControl::kContinue;
    }
};
HitSink g_hit_sink;

// TESHitEvent::GetEventSource has no Address Library ID on 1.16, but the source's class vtable does
// (RE::VTABLE::BSTEventSource_TESHitEvent_): the source is a static object in the game's writable data, so the image's
// writable pages are searched for that vtable (once, at load; supported, not verified: the log names what was found).
// Each object found gets the sink through BSTEventSource::RegisterSink (mapped).
void RegisterHitSinkByVtable() {
    const auto vtable = RE::VTABLE::BSTEventSource_TESHitEvent_[0].address();
    const auto base = reinterpret_cast<std::uintptr_t>(REX::W32::GetModuleHandleW(nullptr));
    std::vector<std::uintptr_t> found;
    std::size_t scanned = 0;
    const auto t0 = std::chrono::steady_clock::now();
    for (std::uintptr_t at = base;;) {
        REX::W32::MEMORY_BASIC_INFORMATION mbi{};
        if (!REX::W32::VirtualQuery(reinterpret_cast<void*>(at), &mbi, sizeof(mbi))) break;
        if (reinterpret_cast<std::uintptr_t>(mbi.allocationBase) != base) break;      // past the game's image
        const auto start = reinterpret_cast<std::uintptr_t>(mbi.baseAddress);
        const bool writable = mbi.state == REX::W32::MEM_COMMIT &&
                              (mbi.protect & (REX::W32::PAGE_READWRITE | REX::W32::PAGE_WRITECOPY)) &&
                              !(mbi.protect & (REX::W32::PAGE_NOACCESS | 0x100u));
        if (writable) {
            auto part = combat::find_vtable_objects(start, mbi.regionSize, vtable,
                                                    [](const void* p, std::size_t n) { return game::Readable(p, n); });
            found.insert(found.end(), part.begin(), part.end());
            scanned += mbi.regionSize;
        }
        at = start + mbi.regionSize;
    }
    const auto ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    if (found.empty()) {
        REX::WARN("hit events: no TESHitEvent source found ({} MB of the game's data searched in {:.0f} ms): hit "
                  "handling (block hits, parries) off", scanned >> 20, ms);
        return;
    }
    for (auto a : found) reinterpret_cast<RE::BSTEventSource<RE::TESHitEvent>*>(a)->RegisterSink(&g_hit_sink);
    REX::INFO("hit events: {} TESHitEvent source(s) found by vtable at {} ({} MB searched in {:.0f} ms); sink registered",
              found.size(), [&] {
                  std::string s;
                  for (auto a : found) s += std::format("{}+{:X}", s.empty() ? "" : ", ", a - base);
                  return s;
              }(), scanned >> 20, ms);
}

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

    InstallControls();

    ui->RegisterSink<RE::MenuOpenCloseEvent>(&g_menu_sink);
    // CommonLibSF (9d090c4, its latest as of 2026-10-21) has no Address Library ID for this on Starfield 1.16: ID 0, and
    // calling it stops the game with "Failed to find offset for Address Library ID ... Invalid ID: 0" (owner's first run).
    if constexpr (RE::ID::TESHitEvent::GetEventSource.id() != 0) {
        if (auto* hits = RE::TESHitEvent::GetEventSource()) hits->RegisterSink(&g_hit_sink);
        else REX::WARN("no TESHitEvent source: hit handling off");
    } else {
        RegisterHitSinkByVtable();
    }

    g_perf_start = g_perf_last = std::chrono::steady_clock::now();
    if (!Plugin::Get().settings().probe_layout) {
        // Starfield 1.16.244 (owner's run 2026-10-21): tag +0x08, payload +0x10
        g_tag_off = 0x08;
        g_payload_off = 0x10;
        g_state = 1;
        REX::INFO("animation events: Starfield 1.16 layout (tag +08, payload +10); bProbeEventLayout = 1 to probe again");
    }

    installed = true;
    REX::INFO("hooks installed: input receiver vtable {:X}, player animation sink vtable {:X}", input_vtbl.address(),
              sink_vtbl.address());
    return true;
}

}  // namespace s2s::sfse::hooks
