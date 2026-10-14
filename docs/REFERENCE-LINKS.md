# Translating preserved placement relationships

`dotnet/ReferenceLinks` is an optional postprocessing stage after PluginSpike. It
reads the generated plugin, its persistent `formids.json`, and version-2 cell
exports. It writes to a separate output directory; the input plugin is unchanged.
It refuses to overwrite an existing output plugin.

```powershell
$env:STARFIELD_DATA = '<Starfield Data directory>'
dotnet run --project dotnet/ReferenceLinks -- <input FO4Port.esm> <formids.json> <fresh output directory> <cell1.json> <cell2.json>
```

Supply every involved cell export together so cross-cell targets can resolve.
The tool reads Starfield's current vanilla static records to locate EnableMarker,
XMarker, XMarkerHeading and LightBox by EditorID. Needed source control markers are recreated
with stable IDs, source transforms, disabled state and persistent grouping. It
does not guess an equivalent record for arbitrary missing objects or actors.

LightBox helpers require a fresh export containing primitive bounds, RGBA color,
type and the primitive's unknown value. Bounds convert to metres; RGB colors and
the unknown value are retained. The JSON retains alpha, but the target primitive
binary color stores RGB, so alpha is not a supported target property.
Missing geometry or an unrecognized primitive
type produces an issue instead of creating an empty lighting volume. This has
binary round-trip coverage; equivalent lighting behavior still needs game testing.

Implemented translation:

- Persistent source object placements move into target cell persistent groups and
  retain the persistent flag.
- Enable parents resolve to actual placed target records, including recreated
  control markers. The opposite-state and pop-in flags retain their meanings.
- Linked references resolve placed targets. A null discriminator remains null; a
  discriminator that resolves to a placed object is translated as that reference.
- Default-open state applies to actual converted door bases.
- Absolute teleport destinations resolve converted doors and transition cells;
  positions convert from source units to metres and rotations remain radians.

Generic linked-reference keywords (`None` or an absent category, no flags or
attraction rule) now become source-scoped target KYWD records with stable
`KYWD:<source FormKey>` map entries. Color, resolved name and notes are retained.
EditorIDs include a source-identity digest rather than reusing unrelated vanilla
keywords with similar names. Specialized keyword categories/flags/attraction
semantics still need translators. Targets
outside the supplied exports, skipped actors/objects, unsupported flag bits and
relative-position teleports are reported as unresolved. Relative teleports need
additional handling for the converted door pivot. Ownership, locks, actor behavior
and scripts remain separate work. No unsupported case is assigned a numeric-ID
guess.

The default refuses to write a plugin while unresolved relationships remain. A
`relationships-report.json` lists issues and counts unplaced source references.
`--report-only` computes that report without emitting a plugin; incomplete state
is recorded in `build-state.json`. `--no-markers` disables marker recreation.
`--allow-unresolved` explicitly emits a partial plugin and records its unresolved
count and partial fidelity; this is for research, not proof of complete gameplay.

The output includes an updated `formids.json` reserving marker identities. Preserve
that map in subsequent writer/postprocessor runs, or newly added base records
could reuse IDs that were previously allocated to markers. Keep the output map
with the output plugin. The tool currently expects the standalone generated
plugin's only external master to be Starfield.esm; it does not guess master styles
for unrelated mod dependencies.

Synthetic tests run with:

```powershell
dotnet run --project dotnet/ReferenceLinks.Tests
```

They verify cross-cell parent/link/teleport identities, units, persistent grouping,
default-open state, stable control-marker IDs, idempotent links and binary output
round-tripping. They also compare Fallout 4 and Starfield flag names/values and
reject missing targets even if their IDs remain reserved in the map.

A local Vault 81 research run recreated six control markers and restored 109
enable-parent relationships, five linked references, 51 persistent placements and
two default-open door states. Binary read-back confirmed these counts. There were
65 unresolved issues and no resolved teleports in that one-cell run; missing
outside-cell destinations and keyword mapping remain open. This partial plugin
was written only to research scratch, never installed or tested in-game.

A refreshed export retained seven source linked-reference keywords, all generic.
The subsequent research pass created one keyword needed by currently placed
children; issues dropped to 35. Linked references stayed at five because missing
placed targets still block the remaining links. Binary read-back confirmed the
keyword record. Synthetic tests separately prove that a resolvable keyworded link
retains both target identities and survives serialization without duplicates.
Specialized categories are rejected rather than flattened to generic labels.
