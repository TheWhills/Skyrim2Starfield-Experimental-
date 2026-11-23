// S2SDodge's hooks: the same three as S2SCombat's (sfse/src/Hooks.cpp), reduced to what the dodge needs. No player
// controls hook (the dodge hides no key from the game), no hit sink, no lock-on, no layout probe: the animation event
// layout is Starfield 1.16's (tag +08, payload +10; S2SCombat's probe found it on the owner's runs).
#include "Dodge.h"

#include "Game.h"
#include "s2s/controller.h"

namespace s2s::dodge {
namespace game = sfse::game;    // the shared game helpers (src/Game.h), as S2SClash uses them
namespace {

using PerformInputProcessing_t = void(RE::BSInputEventReceiver*, const RE::InputEvent*);
PerformInputProcessing_t* g_input_original = nullptr;

// ThumbstickEvent (not mapped in CommonLibSF): idCode +0x30 (0x0B left stick), x / y at +0x38 / +0x3C (S2SCombat).
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
            const bool down = b->value != 0.0f && b->heldDownSecs == 0.0f;
            const bool up = b->value == 0.0f && b->heldDownSecs != 0.0f;
            if (!down && !up) continue;                          // held repeats
            if (b->deviceType == RE::InputEvent::DeviceType::kMouse && (b->idCode == 0x800 || b->idCode == 0x900) && !down)
                continue;                                        // the wheel's zero "release" after each notch
            plugin.OnButton(KeyCode(b), down, std::string_view(b->strUserEvent));
        } else if (e->eventType == RE::InputEvent::EventType::kThumbstick) {
            const auto* bytes = reinterpret_cast<const std::byte*>(e);
            if (*reinterpret_cast<const std::int32_t*>(bytes + kStickId) == kLeftStick)
                plugin.OnStick(*reinterpret_cast<const float*>(bytes + kStickX),
                               *reinterpret_cast<const float*>(bytes + kStickY));
        }
    }
    plugin.Tick();
    g_input_original(a_this, a_head);
}

using Sink = RE::BSTEventSink<RE::BSAnimationGraphEvent>;
using ProcessEvent_t = RE::BSEventNotifyControl(Sink*, const RE::BSAnimationGraphEvent&,
                                                RE::BSTEventSource<RE::BSAnimationGraphEvent>*);
ProcessEvent_t* g_event_original = nullptr;
constexpr std::ptrdiff_t kAnimSinkOffset = 0x50;
constexpr std::ptrdiff_t kTagOffset = 0x08, kPayloadOffset = 0x10;    // Starfield 1.16.244 (S2SCombat's probe)

std::string_view View(const RE::BSFixedString& s) {
    const char* p = s.c_str();
    return p ? std::string_view(p) : std::string_view();
}

RE::BSEventNotifyControl ProcessEvent(Sink* a_this, const RE::BSAnimationGraphEvent& a_event,
                                      RE::BSTEventSource<RE::BSAnimationGraphEvent>* a_source) {
    const auto ev = reinterpret_cast<std::uintptr_t>(&a_event);
    const auto tag = View(*reinterpret_cast<const RE::BSFixedString*>(ev + kTagOffset));
    const auto payload = View(*reinterpret_cast<const RE::BSFixedString*>(ev + kPayloadOffset));
    if (!tag.empty()) Plugin::Get().OnAnimEvent(tag, payload);
    return g_event_original(a_this, a_event, a_source);
}

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

bool InstallHooks() {
    static bool installed = false;
    if (installed) return true;
    if (!Plugin::Get().settings().enabled) return true;       // off (bEnabled = 0, or S2SCombat present): no hooks
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
    installed = true;
    REX::INFO("hooks installed: input receiver vtable {:X}, player animation sink vtable {:X}", input_vtbl.address(),
              sink_vtbl.address());
    return true;
}

}  // namespace s2s::dodge
