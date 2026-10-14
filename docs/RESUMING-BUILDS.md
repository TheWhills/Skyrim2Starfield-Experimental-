# Resuming model conversion

Add `--resume` to the existing `scripts/convert_batch.py` command. Each successful
model writes an atomic checkpoint to `<staging>/.checkpoints/`. If conversion is
interrupted, rerunning the command reuses completed models and converts the rest.
The completed `manifest.json` still describes the currently selected models.

Checkpoints follow the generated NIF's external geometry and generated materials,
then each material's converted texture paths. Every dependency must exist and
match its recorded SHA-256 hash before the result is reused. Missing or changed
outputs cause reconversion. Invalid checkpoint JSON is a cache miss. Failing
models, material placeholders and failed door conversions are retried, not cached.
Collision approximation/drop reports are preserved in cached results; reuse does
not promote their fidelity or constitute an in-game pass.

Input identity includes converter Python source hashes, Python/NumPy/Pillow
versions, texconv/template/content-resource hashes, door-conversion mode and the
source archive set. Archive identity uses resolved path, size and nanosecond
modification time to avoid rereading enormous archives just to resume. Archives
must stay immutable during a run. If an archive is edited while deliberately
preserving its size and modification time, touch it or run without `--resume`.
This is a metadata-based archive freshness policy, not content proof for archives.

The source-to-editor-ID map is saved as each successful model finishes. Keep
`editorids.json` and `formids.json` with staging when moving or backing it up.
Without `--resume`, conversion runs normally. Old staging without checkpoints
builds normally on its first resume run; existing manifests preserve prior names.

Manifest `stats.reused` counts models reused this run. `assets` and `failed` cover
the selected batch; material statistics count conversions performed this run,
not all materials present in staging. A fully reused run avoids constructing the
converter or regenerating the neutral material.

Every batch writes `build-state.json` as incomplete before conversion and complete
only after the final manifest is saved. The installer rejects interrupted or
inconsistent batches. Resume builds also recheck all checkpointed dependencies
after conversion finishes: a later model overwriting a shared material/texture
with different bytes fails the build before publishing a new manifest. This
detects inconsistent sharing; it does not repair material identity collisions.
Existing staging without a build-state file remains supported. Ordinary skipped
or failed assets listed in a finished manifest do not themselves set the build
state to incomplete; inspect the failure list and fidelity reports separately.

Synthetic regression checks cover interruption after the first of two models,
identity preservation, full reuse, corrupt checkpoints, changed inputs, deleted
dependencies, and changed output bytes with unchanged size/mtime. A separate
local patio-chair smoke test converted on its first run (about 1.1 seconds) and
reused on its second (about 0.5 seconds). This is one-asset evidence; large-batch
speedup has not been measured. No game installation was changed.
