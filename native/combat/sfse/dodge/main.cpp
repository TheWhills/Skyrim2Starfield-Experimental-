// S2SDodge SFSE plugin entry: TK Dodge style dodging, standalone (s2s/dodge_only.h). Do not install with S2SCombat
// (it has the same dodge): when S2SCombat.dll is loaded, S2SDodge switches itself off.
#include "Dodge.h"

namespace {

void OnMessage(SFSE::MessagingInterface::Message* a_msg) {
    if (!a_msg) return;
    switch (a_msg->type) {
        case SFSE::MessagingInterface::kPostLoad:
            // every plugin is loaded: S2SCombat would dodge too (both would send the dodge event per press)
            if (REX::W32::GetModuleHandleW(L"S2SCombat.dll"))
                s2s::dodge::Plugin::Get().Disable("S2SCombat.dll is loaded and has the same dodge (use one of the two)");
            break;
        case SFSE::MessagingInterface::kPostDataLoad:
            s2s::dodge::InstallHooks();
            break;
        case SFSE::MessagingInterface::kPostPostDataLoad:
            if (!s2s::dodge::InstallHooks()) REX::ERROR("hooks could not be installed: S2SDodge inactive");
            break;
        default:
            break;
    }
}

}  // namespace

SFSE_PLUGIN_LOAD(const SFSE::LoadInterface* a_sfse) {
    SFSE::Init(a_sfse);
    REX::INFO("S2SDodge loading");
    s2s::dodge::Plugin::Get().LoadSettings("Data\\SFSE\\Plugins\\S2SDodge.ini");
    if (!SFSE::GetMessagingInterface()->RegisterListener(OnMessage)) {
        REX::ERROR("could not register for SFSE messages");
        return false;
    }
    return true;
}
