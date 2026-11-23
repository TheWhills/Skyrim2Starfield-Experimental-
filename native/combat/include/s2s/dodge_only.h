// S2SDodge: the dodge alone, as a standalone plugin (sfse/dodge, S2SDodge.dll). It drives the same Controller as
// S2SCombat, so the dodge behaves the same (direction from the movement keys / stick, the graph event per direction,
// i-frames, the end on AttackEnd / TKDR_DodgeEnd / timeout), with every other system switched off in its settings and
// only the dodge's commands carried out.
#pragma once

#include "s2s/controller.h"

namespace s2s::combat {

// `cfg` with everything but the dodge off: no attack buffer, no power attack key handling, no queued-power cancel, no
// stance re-equip, no dual wield, no timed block / parry / block reduction / re-raise / deferred kill. The dodge
// settings (key, events, i-frames, 8-way, idle direction, cancel, stamina cost) are kept.
ControllerConfig dodge_only(ControllerConfig cfg);

// Whether S2SDodge carries out this command (the event to the graph, the stamina cost, a log line); everything else is
// dropped, so nothing outside the dodge can happen even if the controller produced it.
bool dodge_only_command(Command::Kind kind);

// The settings of S2SDodge.ini: its [Combat] section read as S2SCombat's, then dodge_only.
ControllerConfig parse_dodge_config(std::string_view ini, std::vector<std::string>* problems = nullptr);

}  // namespace s2s::combat
