# Next milestone: one Fallout 4 actor in Starfield

Owner direction: hardest task after the interior slice ([#31](https://github.com/dasscooby/fo4-to-starfield/issues/31)). This is a proposed execution plan for WP-13/WP-14 and spike S7, not a claim that actor conversion works or that all agents have accepted assignments.

## Start gate

Finish the eight-cell interior acceptance first: verified stairs, doorway clearance, closed/open door collision, and recoverable deployment on a recorded revision and artifact hashes. Unreadable positions are inconclusive; they must be rerun. Remaining blocked doors and Vault 114 stairs keep this gate open. Planning and read-only inventory may proceed now; actor implementation and live deployment follow the gate.

## First deliverable

One non-player humanoid with a converted Fallout 4 body/outfit, stable source identity, and Starfield-native rig, idle, walking and character collision, in a small controlled test cell. Choose the exact source actor after inventory: use the simplest supported humanoid, avoiding power armor, unusual skeletons and quest dependencies. Record every substitution; a Starfield actor wearing a converted outfit proves skinning, not full Fallout 4 actor fidelity.

## Work sequence and evidence

1. **Inventory and choose the bridge.** Compare source/target bone hierarchies, bind transforms, skin weights, mesh partitions and record dependencies. Record runtime/tool versions and a capability table. Existing native door rig/clip exports are useful tools, but do not establish skinned-actor support. Identify missing readers/writers before bulk conversion.
2. **Prove skinning offline.** Transfer one body/outfit to the Starfield human rig. Keep parent transforms, inverse bind matrices, coordinate units, bone indices and normalized weights consistent. Compare bind pose and several controlled poses against source geometry; use synthetic fixtures in Git. Reject unsupported anatomy or missing bones explicitly rather than silently assigning weights.
3. **Prove rendering in game.** Spawn the converted body on a minimal native actor configuration. Verify scale, orientation, attachments and deformation at rest. Keep persistent source-to-target record IDs. Capture build hashes and clear full-body screenshots; startup alone is insufficient.
4. **Prove idle and locomotion.** Start with native Starfield animations and behavior. Verify idle, turn, start/stop and walk without stretching, sliding, sinking or duplicate root displacement. Separate character movement from animation root motion. Custom FO4 animation retargeting is a later decision, not required for this first proof.
5. **Prove movement and physics.** Walk a known route with floor, stairs, doorway and obstacles using native Starfield character physics. Verify final XYZ, settling and route continuity. Use one known-good navmesh for AI movement; failure to path is distinct from collision failure. Never replace character physics with static boxes or teleport-based acceptance.
6. **Prove persistence and recovery.** Save/reload the actor, rebuild after source order changes, then uninstall/reinstall the test build. IDs remain stable and deployment is recoverable. Publish scripts, mappings, supported limitations and evidence; source assets remain local.

## Proposed team split

- **Claude:** actor record/runtime integration, native behavior and character physics, controlled game probes. Keep existing interior fixes first.
- **Codex:** bone/bind/weight verification, stable identities, generated dependency inventory and deployment checks. Claim new files explicitly before implementation; shared writers require coordination.
- **Grok:** independent actor acceptance checks and evidence review, including impossible/read-error positions, exact build identity and deformation/movement criteria. Report current availability and ownership in #31.

These assignments extend current strengths; existing file locks remain authoritative until a new claim is recorded. GitHub #31 holds decisions; #32 holds short progress reports.

## Stop/go decisions

If native skinning fails, isolate one synthetic weighted mesh and fix the writer before converting more actors. If source anatomy cannot map faithfully, document the mismatch and select a supported humanoid for the proof. If animation works but movement fails, isolate root motion, physics and navmesh separately. Do not call a rendered static mannequin an actor success.

After the first actor passes, expand in order: equipment and head/face fidelity, a second humanoid, FO4 animation retargeting feasibility, then creature rigs and wider AI/gameplay. Terrain, quests, dialogue and Papyrus are separate milestones. No paid tooling or new installation is assumed by this plan.
