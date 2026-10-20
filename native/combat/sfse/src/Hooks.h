#pragma once

namespace s2s::sfse::hooks {

// Input (UI's input receiver) and the player's animation-graph event sink. Call once the game data is loaded
// (the player and UI objects exist); safe to call again (installs once).
bool Install();

}  // namespace s2s::sfse::hooks
