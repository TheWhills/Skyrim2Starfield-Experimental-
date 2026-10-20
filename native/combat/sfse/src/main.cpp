// S2SCombat SFSE plugin entry (docs/armor/combat-plugin-spec.md; build and first-run notes in sfse/README.md).
#include "Hooks.h"
#include "Plugin.h"

namespace {

void OnMessage(SFSE::MessagingInterface::Message* a_msg) {
    if (!a_msg) return;
    switch (a_msg->type) {
        case SFSE::MessagingInterface::kPostDataLoad:
            // The player and UI singletons exist once the game data is loaded (supported: SFSE plugins install
            // per-object hooks here). Retried at kPostPostDataLoad if not.
            s2s::sfse::hooks::Install();
            break;
        case SFSE::MessagingInterface::kPostPostDataLoad:
            if (!s2s::sfse::hooks::Install()) REX::ERROR("hooks could not be installed: plugin inactive");
            break;
        default:
            break;
    }
}

}  // namespace

SFSE_PLUGIN_LOAD(const SFSE::LoadInterface* a_sfse) {
    SFSE::Init(a_sfse);
    REX::INFO("S2SCombat loading");

    // Data\SFSE\Plugins\S2SCombat.ini (the game's working directory is the Starfield folder).
    s2s::sfse::Plugin::Get().LoadSettings("Data\\SFSE\\Plugins\\S2SCombat.ini");

    if (!SFSE::GetMessagingInterface()->RegisterListener(OnMessage)) {
        REX::ERROR("could not register for SFSE messages");
        return false;
    }
    return true;
}
