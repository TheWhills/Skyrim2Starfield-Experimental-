// S2SClash SFSE plugin entry: the weapon clash add-on to S2SCombat (src/ClashApi.h, clash/ClashPlugin.h).
#include "ClashPlugin.h"

namespace {

// S2SCombat's message (sender "S2SCombat", sent at SFSE's PostLoad): its CombatServices.
void OnCombatMessage(SFSE::MessagingInterface::Message* a_msg) {
    if (!a_msg || a_msg->type != s2s::api::kMessage || !a_msg->data) return;
    s2s::clash::ClashPlugin::Get().Connect(static_cast<const s2s::api::CombatServices*>(a_msg->data));
}

void OnSfseMessage(SFSE::MessagingInterface::Message* a_msg) {
    if (!a_msg) return;
    if (a_msg->type == SFSE::MessagingInterface::kPostDataLoad || a_msg->type == SFSE::MessagingInterface::kPostPostDataLoad)
        s2s::clash::ClashPlugin::Get().InstallGraphFilter();
}

}  // namespace

SFSE_PLUGIN_LOAD(const SFSE::LoadInterface* a_sfse) {
    SFSE::Init(a_sfse);
    REX::INFO("S2SClash loading (needs S2SCombat)");
    s2s::clash::ClashPlugin::Get().LoadSettings("Data\\SFSE\\Plugins\\S2SClash.ini");
    auto* messaging = SFSE::GetMessagingInterface();
    if (!messaging->RegisterListener(OnSfseMessage) || !messaging->RegisterListener("S2SCombat", OnCombatMessage)) {
        REX::ERROR("could not register for SFSE / S2SCombat messages");
        return false;
    }
    return true;
}
