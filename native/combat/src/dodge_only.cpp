#include "s2s/dodge_only.h"

namespace s2s::combat {

ControllerConfig dodge_only(ControllerConfig c) {
    c.buffer_attacks = false;
    c.power_key = 0;
    c.power_in_combo = false;
    c.cancel_queued_power = false;
    c.cancel_unpressed_attacks = false;
    c.stance_reequip = false;
    c.stance_refresh_events.clear();
    c.dual_worn_keyword.clear();
    c.dual_stance_keyword.clear();
    c.block_hit_variable.clear();
    c.parry_window = 0.0;
    c.perfect_block_window = 0.0;
    c.parry_restore_health = false;
    c.parry_events.clear();
    c.timed_block_message.clear();
    c.block_reduction = 0.0;
    c.block_reraise_event.clear();
    c.defer_kill = false;
    c.plugin_event_host.clear();
    return c;
}

bool dodge_only_command(Command::Kind kind) {
    return kind == Command::Kind::SendEvent || kind == Command::Kind::SpendStamina || kind == Command::Kind::Log;
}

ControllerConfig parse_dodge_config(std::string_view ini, std::vector<std::string>* problems) {
    return dodge_only(parse_config(ini, problems));
}

}  // namespace s2s::combat
