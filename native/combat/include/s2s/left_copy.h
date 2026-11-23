// Left-hand copy test (docs/re/findings.md, docs/ai/decisions.md 2026-11-23 "Any weapon in the left hand"): a key
// makes a runtime copy of the drawn right-hand weapon's 3D with the engine's own clone virtuals and hangs it under the
// left weapon node; the same key, a sheathe / unequip, or a load takes it off again. This header holds the parts that
// do not touch the game: when to make / drop the copy, and the NiCloningProcess bytes the engine builds on the stack.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string_view>
#include <vector>

namespace s2s::combat {

// NiCloningProcess as Starfield 1.16.244 builds it before CreateClone (NiObject vtable slot 41) and ProcessClone
// (slot 47); verified at 0x140e4b9b0 and 0x140a07b30 (findings.md section 2).
struct CloningProcessLayout {
    static constexpr std::size_t kSize = 0x38;
    static constexpr std::size_t kMapRoot = 0x00;    // tree map original -> copy: root node
    static constexpr std::size_t kMapCount = 0x10;   // element count (u64; 0 = nothing to free)
    static constexpr std::size_t kMapSpare = 0x18;   // one spare node kept by the map
    static constexpr std::size_t kCopyType = 0x20;   // u32, the engine's default copy type (global, ID 884304)
    static constexpr std::size_t kAppendChar = 0x25; // '$'
    static constexpr std::size_t kFlag = 0x26;       // 1
    static constexpr std::size_t kScale = 0x28;      // float x3 = 1.0
    static constexpr std::size_t kNodeSize = 0x80;   // a map node (freed with the sized free)
};

// The 0x38 bytes of a fresh NiCloningProcess (zeroed maps, copy type, '$', 1, scale 1,1,1).
std::array<std::uint8_t, CloningProcessLayout::kSize> cloning_process_bytes(std::uint32_t copy_type);

// A comma separated INI list, trimmed, empty entries left out.
std::vector<std::string_view> split_names(std::string_view list);

// Which child of the weapon node is the weapon's model. The owner's run 2026-11-23: the skeleton's "Weapon" node holds
// 'R_HandIk', 'L_HandIk' (IK helpers, nothing drawn) and then the model, so the first child is the wrong one.
// override_name non-empty: the child with that name (case-insensitive), else -1. Otherwise the first child whose name
// is not in skip (case-insensitive). -1 = none.
int pick_model(const std::vector<std::string_view>& children, std::string_view override_name,
               const std::vector<std::string_view>& skip);

// When the copy is made and dropped. The game side reports back whether it worked (on_result); until then nothing
// else is asked for.
class LeftCopy {
public:
    enum class Action { None, Make, Drop };

    explicit LeftCopy(bool enabled = true) : enabled_(enabled) {}

    // The test key: makes the copy, or drops it when one is on.
    Action on_key();
    // The player's animation events: 'weaponSheathe' and 'UnequipComplete' drop a copy (the game does not know it,
    // so its own sheathe leaves it hanging; findings.md "Sheathe / unequip").
    Action on_event(std::string_view tag);
    // A menu opening: 'LoadingMenu' drops the copy while the old 3D still exists (a load rebuilds the player's 3D).
    Action on_menu(std::string_view name, bool opening);
    // What the game side did: Make ok -> a copy is on; Drop (ok or not) -> none is (a failed drop is not retried).
    void on_result(Action what, bool ok);

    bool attached() const { return attached_; }
    bool busy() const { return pending_ != Action::None; }

private:
    bool enabled_;
    bool attached_ = false;
    Action pending_ = Action::None;
};

}  // namespace s2s::combat
