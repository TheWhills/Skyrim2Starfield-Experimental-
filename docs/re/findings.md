# Reverse-engineering findings: Starfield 1.16.244

Program: `Starfield.exe.1` in the owner's Ghidra project "Starfiled 44" (MD5 `0a73ecdc1d54b14a91818cddeb03aa9e`,
image base 0x140000000). Tool: ReVa 7.3 MCP server in Ghidra 12.1, session of 2026-11-23 (Claude). Brief:
docs/re/ghidra-ai-setup.md section 4. Background: docs/ai/decisions.md 2026-10-26 / 27 and 2026-11-23 (left hand).

All of this is offline static analysis. Nothing here has been called from a plugin or tested in game.

Confidence labels follow docs/ai/research-log.md:
- **verified**: read directly from the decompiled code or memory (address, slot and behaviour all seen).
- **supported hypothesis**: the code fits the name, but part of the reading is inference.
- **unresolved**: not established.

Address Library IDs (verified): looked up in the Address Library v22 offsets table for 1.16.244.0
(`offsets-1-16-244-0.txt`, from the owner's download of the SFSE Address Library mod; not in Git). The table maps
ID -> absolute address. As a check, CommonLibSF's vtable IDs land exactly on the vtables found from RTTI: NiNode
497979 = 0x144eefb60, NiAVObject 497991 = 0x144eefed8, WeaponAttachHandler 453937 = 0x144cc5068. Every ID is listed in
the rename index at the end. In a plugin, use `REL::ID(n)`, not the raw address.

Every function below has been renamed in Ghidra. Names that start with `S2S_` are our own, not Bethesda's. Save the
project (Ctrl+S) to keep them.

## 1. NiObject / NiAVObject / NiNode vtables

| Class | Type descriptor | Complete object locator | vtable | Addr. Lib. ID (CommonLibSF) | Confidence |
|---|---|---|---|---|---|
| NiNode | 0x1459bec88 | 0x145388470 | **0x144eefb60** (95 slots, 0-94) | 497979 | verified |
| NiAVObject | 0x1459beca8 | 0x145388598 | **0x144eefed8** | 497991 | verified (location only, slots not dumped) |
| NiObject | 0x1459bc248 | none found | none: no complete object locator references it (it only appears as a base class), so it has no vtable of its own | n/a | verified |

How it was found: the RTTI string `.?AVNiNode@@` (0x1459bec98) - 0x10 gives the type descriptor. The reference
from inside a complete object locator gives the locator. The reference to the locator gives `vftable_meta_ptr`, and the
vtable starts 8 bytes after that.

### Identified slots (NiNode vtable 0x144eefb60)

| Slot | Offset | Address | Name (in Ghidra) | What it does | Confidence |
|---|---|---|---|---|---|
| 41 | 0x148 | 0x142bd2cc0 | `NiNode__CreateClone` | Allocates 0x150 bytes, constructs a NiNode (vtable `NiNode::vftable`, children array vtable `NiTObjectArray<NiPointer<NiAVObject>>` at +0x130), then calls CopyMembers(this, clone, cloningProcess) and returns the clone. | verified |
| (non-virtual) | | 0x142bd2de0 | `NiNode__CopyMembers` | Base copy (0x142bd49d0), reserves the clone's child array to the source count, then for each child (skipping flag bit 46 of +0x118) calls **child->CreateClone (slot 41)** and installs the copy with **slot 92 (0x2e0) SetAt(index, child)**. This is the recursion into children. | verified |
| 47 | 0x178 | 0x142bd2ed0 | `NiNode__ProcessClone` | Base ProcessClone (0x142bd4af0), then calls slot 47 on each child. | verified |
| 84 | 0x2a0 | 0x142bd15e0 | `NiNode__AttachChild` | `(this, child, bool firstAvailable)`. Calls SetParent(child, this) (writes child +0x38), appends to children at +0x138 (or reuses the first null entry when firstAvailable), stores the index in child +0xC (u16), then MarkDirtyUpward if needed and sets byte +0x88 of the object at +0x20. | verified |
| 85 | 0x2a8 | 0x142bd1820 | `NiNode__InsertChildAt` | `(this, uint index, child)`. Inserts and renumbers the children's +0xC indices. | verified |
| 86 | 0x2b0 | 0x142bd1b20 | `NiNode__DetachChild_Out` | `(this, child, NiPointer<NiAVObject>& out)`. Checks child +0x38 == this, clears the entry, returns the child in `out`, then MarkDirtyUpward. | verified |
| 87 | 0x2b8 | 0x142bd1ad0 | `NiNode__DetachChild` | `(this, child)`: wrapper around slot 86 that drops the reference. SetParent calls it on the old parent. | verified |
| 88 | 0x2c0 | 0x142bd1c70 | `NiNode__DetachChild_NoBoundUpdate` | Like 86, but without the MarkDirtyUpward call and without the out pointer. | supported hypothesis (purpose) |
| 90 | 0x2d0 | 0x142bd1960 | (not renamed) | Called as `(node, index)` to remove a child by index in 0x14034d400. | supported hypothesis |
| 92 | 0x2e0 | 0x142bd1de0 | (not renamed) | SetAt(index, child): CopyMembers uses it to put cloned children in place. | supported hypothesis |
| 62 | 0x1f0 | 0x142bd2c30 | (CommonLibSF: GetObjectByName) | Called with a BSFixedString* to find a named node (0x141987c60, 0x14034d400). | supported hypothesis |

Non-virtual helpers:

| Address | Name | What it does | Confidence |
|---|---|---|---|
| 0x142bd4260 | `NiAVObject__SetParent` | `(child, newParent)`: calls oldParent->slot 87 (DetachChild), writes child +0x38 = newParent, and copies inherited flag bits from the parent's +0x118 through slots 66 / 69 / 71. | verified |
| 0x142bd4620 | `NiAVObject__MarkDirtyUpward` | Sets bit 29 (0x20000000) of +0x118 on the node and on each parent up the +0x38 chain, stopping at the first one that already has it. AttachChild and DetachChild both call it. This is probably the "needs update" flag the update pass looks for. | verified (code), supported hypothesis (meaning) |
| 0x142421370 | `S2S_FindNodeByName` | `(root, BSFixedString* name, bool recursive)` -> NiAVObject*. Every weapon / attach path uses it to look up bones and attach nodes. | supported hypothesis |

Layout seen on the way (fits the owner's 2026-10-26 dump):
- +0x0C u16: index in the parent's child array (0xFFFF = none).
- +0x38: parent.
- +0x118: flags (u64).
- +0x130: `NiTObjectArray<NiPointer<NiAVObject>>` with vtable at +0x130, data at +0x138, capacity u16 at +0x140, size u16 at +0x142, free-slot count u16 at +0x144, grow step u16 at +0x146.
- NiNode is 0x150 bytes.

### Compared with CommonLibSF (native/combat/sfse/lib/commonlibsf/include/RE/N)

- `NiObject.h`: no CreateClone. Slots 41..54 are `Unk41..Unk54`. **Slot 41 = CreateClone and slot 47 = ProcessClone**
  (verified above). In earlier games the slots in between were LoadBinary / LinkObject / RegisterStreamables /
  SaveBinary / IsEqual (slots 42-46 were not checked).
- `NiAVObject.h`: slots 55-83. Matches NiNode's vtable length (NiNode adds slots 84-94).
- `NiNode.h`: **the declared order is wrong for 1.16.244.** With MSVC's ordering, the declared new virtuals land on
  AddChild = 84 (correct, but the real function takes a third `bool firstAvailable` argument),
  RemoveChild = 85 (actually **InsertChildAt**), FindObjectRecursive = 86 (actually **DetachChild with out pointer**),
  GetLocalTransform = 87 (actually **DetachChild**), SetLocalTransform = 88 (a detach variant).
  The `children` member as a `BSTArray` also does not match. That is the known +0x130 / +0x138 / +0x140 layout
  (decisions 2026-10-26).
- Our code does not call `RemoveChild` / `FindObjectRecursive` / `Get/SetLocalTransform` anywhere outside
  commonlibsf (grep of native/, verified). Anything that adds such calls must use the real slots above.

## 2. Copying a loaded model: how the engine does it

`S2S_ModelEntry_CloneOrShareRoot` (0x140e4b9b0) clones a loaded model's root (entry +0x20). It is called by a
queued-model-load task (0x140e4d6b0). When the root is already shared (refcount >= 4) and flag 2 asks for a copy,
it does this (verified):

```
NiCloningProcess cp{};          // 0x38 bytes on the stack
// +0x00..0x1F  map(s), zeroed  (freed afterwards; buffer released with FUN_1402ba340(ptr, 0x80))
// +0x20 u32    copy type  = DAT_145e7a424  (global default copy type)
// +0x24 u16    0x2400     -> byte +0x25 = '$' (append char, as in Gamebryo), byte +0x24 = 0
// +0x26 u8     1
// +0x28..0x33  scale = (1.0, 1.0, 1.0)
clone = root->vtbl[41](root, &cp);   // CreateClone
root->vtbl[47](root, &cp);           // ProcessClone
```

There is no separate non-virtual `Clone()` here. The two calls are inlined at each call site. At least 40 functions
make a slot-41 call (the search stopped at 40), and many follow it with slot 47 on the same object, for example
0x140353d80, 0x140a07b30, 0x140e49060. **Plan for S2SCombat:** build the same 0x38-byte struct
and call slots 41 and 47 on the weapon's 3D root, then free the struct as below.

**Cleanup (second session).** The same cleanup is inlined after every clone (0x140e4b9b0 lines 94-194 and
0x140a07b30 lines 109-200 match). The first 0x20 bytes are a small tree map that CreateClone fills (original -> copy):
+0x00 root node, +0x10 element count, +0x18 one spare node. Nodes are 0x80 bytes: int +0x00 = 0 for a leaf,
u32 +0x04 = key count, child pointers from +0x40.

```
if (cp.count /*+0x10*/ != 0) {
    S2S_CloneMap_FreeNode(&cp, cp.root /*+0x00*/);   // 0x140359090, ID 38088: frees the tree; keeps one node at +0x18
    cp.root = 0; cp.+0x08 = 0; cp.count = 0;
}
if (cp.spare /*+0x18*/) S2S_MemoryManager_FreeSized(cp.spare, 0x80);   // 0x1402ba340, ID 35771
```

`S2S_CloneMap_FreeNode(map, node)` frees the children first, then makes `node` the new spare and frees the old spare
with `S2S_MemoryManager_Free` (0x1402b7910, ID 35698, the engine's global free). The inlined code does the same, except
that for a leaf root it skips the call (the result is identical). Status: the code is **verified**; that calling
`S2S_CloneMap_FreeNode` on any root gives the same result as the inlined code is a **supported hypothesis**.

## 3. Drawing a weapon: how the model is attached

Strings: `"Weapon"` and `"WeaponLeft"` (and `"WeaponBack"`) are global BSFixedStrings, created at start-up:
`"Weapon"` at **0x145e89cc0**, `"WeaponLeft"` at **0x145e89cc8**, `"Prn"` at **0x145e89cb8** (init functions
0x140039290 / 0x1400392c0 / 0x140039260). `"WEAPON"` has no references.

Call chain on draw (verified unless marked):

1. **`WeaponAttachHandler__Handle`** 0x141aebca0 = vtable `WeaponAttachHandler` 0x144cc5068 slot 1 (Addr. Lib.
   vtable ID 453937). It is the animation-event handler (`IHandlerFunctor<Actor, BSFixedString>`). It works out the
   hand / equip slot (0x141ae4ef0), gets the equipped weapon and its instance data (0x141985270), and calls step 2.
2. **`S2S_AttachWeaponToHand_RunOrQueue`** 0x1418c0a60 (manager at DAT_145e71728): if called on the main thread
   it runs step 3 at once, otherwise it queues a `BSService::Detail::TCmd<lambda>` that does it later.
3. **`S2S_AttachWeaponToHand_Run`** 0x1418c0c40 calls the **Actor virtual at +0x740 (slot 232 = 0xE8)**.
   CommonLibSF has this slot as `Unk_E8` in TESObjectREFR.h.
4. **`Actor__AttachWeapon_vE8`** 0x140b41240 (Actor vtable **0x144cb9248**, ID 451614, slot 232; locator 0x1451c0458):
   picks first or third person, calls step 5, and for the player also calls 0x141a60900(DAT_145f43230).
5. **`S2S_Actor_AttachWeapon_Impl`** 0x140b6fe60 `(actor, weaponData, slot, bool firstPerson)`: gets the biped
   (actor slot 0x8c8 / 0x8d0) and a per-slot object (0x8d8 / 0x8e0). Under the actor's lock (slot 0x948) it calls
   step 6 for each entry in the actor's list (slot 0x950).
6. **`S2S_Actor_SubmitAttachRequest`** 0x140b6ff90: builds a 0x160-byte attach request (0x140aa75b0, from
   weapon + biped + slot), then calls
   - `S2S_AttachRegistry_AddRequest` 0x14034bcc0: a hash map keyed by the request. It makes a 0x40-byte entry and
     notifies its listeners (0x140350c30) (supported hypothesis),
   - 0x14034dd90: walks the registry's listeners (callback at +0x80) (supported hypothesis),
   - 0x14034c090: looks up / publishes in a global table (DAT_145e7edb8) (unresolved).

   **So the draw does not call `NiNode::AttachChild` directly.** It files a request that is carried out later.

7. The request is carried out by **`S2S_Actor_ProcessAttachRegistry`** 0x140b718d0 -> 0x14034c240 -> 0x14034cb90
   -> **`S2S_AttachRegistry_BindSkinAndAttach`** 0x14034d400 (verified code; "registry" naming is ours):
   - Attach target: the node named by the model root's **`Prn` extra data** (NiStringExtraData looked up with
     0x142bcfbf0, node found through slot 62 GetObjectByName on the actor root, then slot 4). Without `Prn`, the
     target is the parent of the actor's 3D root.
   - **Skinned geometry is rebound here:** for each child it calls slot 10 (0x50), which presumably returns the
     geometry or null. For a geometry with a skin instance at +0x1b0, every bone name in the skin is looked up in the
     actor's 3D (`S2S_FindNodeByName`). Found: bones[i] = node and boneWorld[i] = node + 0x80 (the world transform).
     Not found: bit 30 is set on the bone's flags. Then skin +0x38 = skin root (the attach target). This is the step
     that is missing when a skinned shape is attached by hand (setup doc target 4, our run of 2026-10-26).
   - Children that were not bound are removed through slot 90, and 0x14034fdb0 runs.
   - Then **`NiNode__AttachChild` (slot 84)** on the target: if there is exactly one child, that child is attached
     directly and step 8 runs; otherwise the whole model root is attached (firstAvailable = 1).
8. **After the attach:** `S2S_AttachRegistry_PostAttach` 0x140354910 `(slotEntry, newObject)` (second Ghidra
   label `S2S_AttachSlot_ReplaceObject`). It swaps the slot's old 3D (`*slotEntry`) for the new one and carries over
   the old object's extras (all verified from the full function):
   - the first controller in the old object's list (+0x18, found through vtable +0x1b0) is moved onto the new object
     (0x142be0500), and its target is set to the new object (vtable +0x1d0 on the controller's +200 member);
   - the `"CPA"` extra data (global 0x145f613d0, ID 929960; connect-point parents, the attach points object mods use)
     is merged into a new 0x28-byte object (0x142372c50 + 0x140353340), removed from the old object and added to the new
     one (`S2S_NiObjectNET_AddExtraData` 0x142bdff20, ID 147347);
   - the `"CED"` extra data (global 0x145f61448, ID 929972; meaning unresolved) is added to the new object;
   - `*slotEntry = newObject` (smart-pointer assignment).

   So step 8 is bookkeeping for the slot. **It does not register anything with the renderer** (the earlier guess was
   wrong). A copy we attach ourselves does not need it unless we also want its connect points.

   AttachChild itself marks the new branch dirty (`NiAVObject__MarkDirtyUpward`, bit 29) and sets +0x88 = 1 on the
   object at +0x20 of the parent node. Neither step 7 nor step 8 calls an update. The per-frame update is
   `NiNode__UpdateSelectedDownwardPass` (slot 74, 0x142bd23a0, ID 147185; verified). It visits a child only when bit 1 of
   the child's +0x118 is set. Bit 2 = update the world transform (slot 79), bit 3 = run controllers, bit 4 = rigid
   (slot 75). These are Gamebryo's selective-update flags. The plain `NiNode__UpdateDownwardPass` (slot 73,
   0x142bd21e0, ID 147184) updates all children. Neither reads bit 29. Who reads it is **unresolved**: the constant
   search hit ReVa's instruction limit, and a full decompile search of 203k functions was not run. Consequence for us
   (supported hypothesis): a copy follows its new parent if it carries the selective bits 1-2. A clone of the drawn
   weapon copies them from the original.

Related: **`TESRace__GetEquipSlotAttachNodeName`** 0x140683300 `(race, equipSlotIndex)` -> BSFixedString*.
It returns the race's per-slot node name (race +0x5a8, count +0x5a0, 16-byte entries, name at +8). When that name is
empty it falls back to `"Weapon"` for the right-hand slot (DAT_145e810c4) and `"WeaponLeft"` for every other slot.
The race is obtained through actor vfunc +0x580. 18 call sites use it to find the hand node (for example 0x141987c60:
weapon sub-parts under the hand node). Verified.

### Sheathe / unequip: how the model is detached (second session)

The mirror of the draw path (verified unless marked):

1. **`WeaponDetachHandler__Handle`** 0x141aebd20 (ID 104063) = vtable `WeaponDetachHandler` 0x144cc5080 (ID 453939)
   slot 1. Same slot / weapon lookup as the attach handler. It only acts when the hand's state (0x140b72b60) is
   0x10 or 0x11.
2. **`S2S_DetachWeaponFromHand_RunOrQueue`** 0x1418c1850 (ID 100012), same manager: runs on the main thread or
   queues a `BSService` command.
3. **`S2S_DetachWeaponFromHand_Run`** 0x1418c19d0 (ID 100013) calls the **Actor virtual at +0x748 (slot 233 =
   0xE9)**, the next slot after attach.
4. **`Actor__DetachWeapon_vE9`** 0x140b412d0 (ID 63324): under the actor's lock (slot 0x948) it calls
   **`S2S_AttachRegistry_RemoveRequest`** 0x14034bdf0 (ID 37948) on each registry in the actor's list (slot 0x950),
   keyed by the weapon object's +0x238. That is the same key the attach request stores (0x140aa75b0).
5. `S2S_AttachRegistry_RemoveRequest` takes the entry out of the map (+0x20), puts its object in a pending list at
   +0x50, then runs 0x14034dd90 / 0x14034c090 (as on attach) and 0x14034bf70 (ID 37950). That last one presumably
   processes the pending list, ending in DetachChild (**supported hypothesis**, not read).

For our copy this means: the game never removes it, because it was never in the registry. S2SCombat has to call
`NiNode__DetachChild` (slot 87, ID 147177) on the left node itself on sheathe / unequip / load (as the plan in
decisions.md 2026-11-23 says). Hooking `Actor__DetachWeapon_vE9` (Actor vtable 451614 slot 233) is one way to catch
the moment.

## 4. What this means for the left hand

- Copy: slots 41 and 47 with the NiCloningProcess above. This is the same thing the engine does for shared models.
- Attach: find the left node with `TESRace__GetEquipSlotAttachNodeName(race, leftSlot)` (gives "WeaponLeft") or
  `S2S_FindNodeByName`, then NiNode slot 84 `AttachChild(child, true)` (not CommonLibSF's `AddChild` signature).
- The 2026-10-27 finding ("writing the node's local / world did nothing visible") fits section 3: the drawn weapon is
  owned by the attach registry, and skinned parts take their bone transforms from pointers (`node + 0x80`) bound at
  attach time. They do not use the transforms of the shape's own parent node. A copy attached under `WeaponLeft`
  should follow that node, unless its geometry is skinned to the right-hand bones. Then the bones need rebinding
  as in step 7, or the copy has to go through the registry. **Unresolved until tested in game.**
- Free the cloning process after the copy (section 2, cleanup).
- Remove the copy yourself (detach section above): the game's sheathe path only empties its own registry.
- Still open: who reads bit 29, what `"CED"` is, and whether 0x14034bf70 ends in DetachChild. None of them blocks
  the first in-game test.

## Index of renames

| Address | Addr. Lib. ID | Name |
|---|---|---|
| 0x142bd2cc0 | 147194 | NiNode__CreateClone |
| 0x142bd2de0 | 147195 | NiNode__CopyMembers |
| 0x142bd2ed0 | 147196 | NiNode__ProcessClone |
| 0x142bd15e0 | 147173 | NiNode__AttachChild |
| 0x142bd1820 | 147174 | NiNode__InsertChildAt |
| 0x142bd1b20 | 147178 | NiNode__DetachChild_Out |
| 0x142bd1ad0 | 147177 | NiNode__DetachChild |
| 0x142bd1c70 | 147179 | NiNode__DetachChild_NoBoundUpdate |
| 0x142bd4260 | 147223 | NiAVObject__SetParent |
| 0x142bd4620 | 147226 | NiAVObject__MarkDirtyUpward |
| 0x142421370 | 127050 | S2S_FindNodeByName |
| 0x140e4b9b0 | 71477 | S2S_ModelEntry_CloneOrShareRoot |
| 0x140683300 | 49314 | TESRace__GetEquipSlotAttachNodeName |
| 0x141aebca0 | 104062 | WeaponAttachHandler__Handle |
| 0x1418c0a60 | 99999 | S2S_AttachWeaponToHand_RunOrQueue |
| 0x1418c0c40 | 100000 | S2S_AttachWeaponToHand_Run |
| 0x140b41240 | 63323 | Actor__AttachWeapon_vE8 |
| 0x140b6fe60 | 63662 | S2S_Actor_AttachWeapon_Impl |
| 0x140b6ff90 | 63663 | S2S_Actor_SubmitAttachRequest |
| 0x14034bcc0 | 37947 | S2S_AttachRegistry_AddRequest |
| 0x140b718d0 | 63676 | S2S_Actor_ProcessAttachRegistry |
| 0x14034d400 | 37954 | S2S_AttachRegistry_BindSkinAndAttach |
| 0x140354910 | 38059 | S2S_AttachRegistry_PostAttach (also labelled S2S_AttachSlot_ReplaceObject) |
| 0x140359090 | 38088 | S2S_CloneMap_FreeNode |
| 0x1402b7910 | 35698 | S2S_MemoryManager_Free |
| 0x1402ba340 | 35771 | S2S_MemoryManager_FreeSized |
| 0x142bd21e0 | 147184 | NiNode__UpdateDownwardPass (slot 73) |
| 0x142bd23a0 | 147185 | NiNode__UpdateSelectedDownwardPass (slot 74) |
| 0x141aebd20 | 104063 | WeaponDetachHandler__Handle |
| 0x1418c1850 | 100012 | S2S_DetachWeaponFromHand_RunOrQueue |
| 0x1418c19d0 | 100013 | S2S_DetachWeaponFromHand_Run |
| 0x140b412d0 | 63324 | Actor__DetachWeapon_vE9 |
| 0x14034bdf0 | 37948 | S2S_AttachRegistry_RemoveRequest |
| 0x142bdff20 | 147347 | S2S_NiObjectNET_AddExtraData |

Not renamed, but with IDs:

| Address | Addr. Lib. ID | What |
|---|---|---|
| 0x142bd1960 | 147175 | NiNode slot 90 (remove child by index, supported hypothesis) |
| 0x142bd1de0 | 147181 | NiNode slot 92 SetAt (supported hypothesis) |
| 0x142bd2c30 | 147193 | NiNode slot 62 GetObjectByName override |
| 0x144eefb60 | 497979 | NiNode vtable |
| 0x144eefed8 | 497991 | NiAVObject vtable |
| 0x144cb9248 | 451614 | Actor primary vtable (offset 0). CommonLibSF's `VTABLE::Actor[0]` (451608 = 0x144cb8c98) is a secondary vtable (locator offset 0x48), so use `VTABLE::Actor[22]` or REL::ID(451614) for slot 232 |
| 0x144cc5068 | 453937 | WeaponAttachHandler vtable |
| 0x145e89cc0 | 888911 | BSFixedString global "Weapon" |
| 0x145e89cc8 | 888912 | BSFixedString global "WeaponLeft" |
| 0x145e89cb8 | 888910 | BSFixedString global "Prn" |
| 0x145e7a424 | 884304 | default NiCloningProcess copy type (u32) |
| 0x144cc5080 | 453939 | WeaponDetachHandler vtable |
| 0x145f613d0 | 929960 | BSFixedString global "CPA" |
| 0x145f61448 | 929972 | BSFixedString global "CED" |

Note: the Ghidra project was not set up with PyGhidra, so ReVa's `run-script` was unavailable. Every lookup
above was done with ReVa's decompile / cross-reference / vtable tools.
