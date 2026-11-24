// Left-hand copy test (docs/re/findings.md, docs/ai/decisions.md 2026-11-23 "Any weapon in the left hand"): a key
// makes a runtime copy of the drawn right-hand weapon's 3D with the engine's own clone virtuals and hangs it under the
// left weapon node; the same key, a sheathe / unequip, or a load takes it off again. This header holds the parts that
// do not touch the game: when to make / drop the copy, and the NiCloningProcess bytes the engine builds on the stack.
#pragma once

#include <array>
#include <optional>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "s2s/xform.h"

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

// Orientation of the copy under the left node (owner's run 2026-11-23: it kept the right weapon's local transform and
// pointed outward). The copy's local rotation = original * turn(turn_index) * euler(degrees).
// turn: the 24 rotations by multiples of 90 degrees (index taken mod 24; 0 = none), so a key can step through every
// axis-aligned orientation in game.
Xform turn(int index);
// Rotation from x, y, z degrees (about x, then y, then z: R = Rz * Ry * Rx).
Xform euler_degrees(float x, float y, float z);
// "x y z" (spaces or commas); false (out untouched) unless three numbers.
bool parse_degrees(std::string_view text, float out[3]);
// WeaponLeft's rest grip on L_Wrist (Starfield skeleton, skeletonmap.LEFT_GRIP; = skyrimweapon.left_grip_metres(),
// checked by tests/test_left_copy_grip.py): a weapon model's local transform under L_Wrist that holds it where the dual
// clips put WeaponLeft. Metres. Owner's run 2026-11-23: under WeaponLeft the copy faced outward in turns (the vanilla
// turn / idle clips leave WeaponLeft at its rest, away from the hand; the worn blade had the same problem, fixed by
// skinning it to L_Wrist at this grip, decisions.md 2026-10-26).
Xform left_grip();
// The copy's local transform: `original` with its rotation turned (translation and scale kept).
Xform oriented(const Xform& original, int turn_index, const float degrees[3]);

// The copy's node names get this prefix. The game finds attach nodes by name (the 'Prn' lookup, findings.md section 3
// step 7): owner's run 2026-11-23, a copy root named "Weapon" under L_Wrist and the right weapon stopped showing after
// the stance re-equip (it most likely went into the copy). "" stays "", an already prefixed name is kept.
inline constexpr std::string_view kCopyNamePrefix = "S2SL_";
std::string copy_node_name(std::string_view name);

// Native left-hand equip test (owner, 2026-11-24: a real left-hand weapon, not a copy). Starfield.esm has the slots
// (EQUP): RightHand 00013F42, LeftHand 00013F43, EitherHand 00013F44 (parents Right + Left), BothHands 00013F45; the
// combat robots hold crModelA_CombatRightGun_Auto in RightHand and crModelA_CombatLeftGun_Auto in LeftHand, and the
// player's melee weapons (CombatKnife, RescueAxe, ...) are BothHands (read from Starfield.esm, 2026-11-24).
inline constexpr std::uint32_t kSlotRightHand = 0x00013F42, kSlotLeftHand = 0x00013F43, kSlotEitherHand = 0x00013F44,
                               kSlotBothHands = 0x00013F45;
// The equip slot each weapon's record gets (in memory) while the native left weapon is on. Owner's runs 2026-11-24:
// melee weapons are BothHands (a LeftHand equip bumped the right weapon); with both set to EitherHand the right weapon's
// model was built under WeaponLeft too (the attach node follows the weapon's own slot: only the right-hand slot maps to
// "Weapon", findings.md TESRace__GetEquipSlotAttachNodeName). So: the right weapon RightHand, the left one LeftHand;
// one record for both hands (two of the same weapon) stays RightHand (the game builds no left model for it anyway).
struct HandSlots { std::uint32_t right_weapon = 0, left_weapon = 0; };   // 0 = no record to change
HandSlots hand_slots(std::uint32_t left_id, std::uint32_t right_id);

// The last right / left pair of the native left weapon, kept in a small file beside the INI (SFSE on 1.16 has no
// save-game hook for plugins), so the records can be set when a loading screen opens, also after a restart.
// Format: "right=0026D8A5\nleft=0004F760\n". parse: nullopt unless both are FormIDs.
struct HandPair { std::uint32_t right = 0, left = 0; };
std::string format_hand_pair(const HandPair& p);
std::optional<HandPair> parse_hand_pair(std::string_view text);

// After a load, what to do with the native left weapon. Owner's runs 2026-11-24: the game saves which weapon is in
// which hand but rebuilt no model with the records back at BothHands; with the records set while the loading screen
// was up the game may build both itself.
//   Nothing: no left weapon in the save and no records set. UndoRecords: records were set but the save has no left
//   weapon (put them back). Keep: the expected left weapon is in LeftHand and both models were built. Redo: anything
//   else with a left weapon in hand (take it off, run the sequence again).
enum class AfterLoad { Nothing, UndoRecords, Keep, Redo };
AfterLoad after_load(bool records_set, std::uint32_t expected_left, std::uint32_t left_in_hand, bool left_model,
                     bool right_model);

// A FormID from the INI: "0x0001234F", "0001234F", "1234f" (hex); "" or 0 or anything else -> nullopt.
std::optional<std::uint32_t> parse_form_id(std::string_view text);

// The game's left-hand model that the plugin moved from WeaponLeft onto L_Wrist (bLeftEquipGrip): what to do with it
// each tick. Forget: it is no longer on the wrist (the game took it off itself). LetGo: detach it from the wrist: the
// left weapon is off, the game released its own reference (fewer references than right after the move: unequipped or
// sheathed), or the game hung a new model under WeaponLeft (a redraw). Keep otherwise.
enum class FollowStep { Keep, Forget, LetGo };
FollowStep follow_step(bool on_wrist, bool active, long refs_now, long refs_at_move, bool new_model_under_weaponleft);

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
