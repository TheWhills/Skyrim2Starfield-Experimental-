// Commonwealth terrain as one or more Starfield overlay worldspaces (docs/terrain/commonwealth-scale.md).
//   dotnet run -- <Starfield.esm> <staging dir>
// Reads <staging dir>/overlays_params.json (written by scripts/terrain/make_cw_overlays.py build) and writes
//   <plugin>        master Starfield.esm, own FormIDs from 0x800 (the anchors first, one per overlay, so plan.json can
//                   name them before the plugin exists), nothing shared with FO4Port.esm
//   <mars plugin>   when params hold "mars": override of MarsPlanetData that appends one PNDT CNAM entry per overlay
// Nothing is deployed.
//
// Per overlay (the records of experiment 2b, docs/terrain/overlay-records.md, once per tile):
//   SFBK <world>Block      copy of OverlayBlockLC172World (102382): ANAM = the tile's BTD, DNAM n x n, ENAM = shared
//                          height range, FNAM = one raw u16 per BTD cell (SW-corner sample), INAM/HNAM alignment
//   LCTN <world>Location   copy of LC172WorldLocation (3807BE): keyword LocTypeOverlay, parent SSol_PMars_Surface; one
//                          per overlay (the CK warns when two overlays share a location)
//   WRLD <world>           copy of LC172World (02DF8C) minus cells/offsets/location; overlay component -> the SFBK;
//                          object bounds = the BTD; every exterior cell of the BTD (empty), the COC cell with a
//                          COCMarkerHeading 2 m above the ground, a persistent XMarker anchor in the persistent cell
// PNDT CNAM entries store latitude first, then longitude (radians; Earth overlays sit at their real cities). Mutagen
// 0.55 names the first value Longitude and the second Latitude, so the params' latitude goes into .Longitude.
//
// Optional "objects": "objects.json" (core64c, docs/terrain/core64c.md, written by scripts/terrain/make_core64c.py stage):
// converted Fallout 4 models as STAT (or rigged DOOR) records and their references in one overlay's exterior cells,
// {"world": <overlay world EditorID>, "bases": [{"edid", "model", "door"?}], "refs": [{"src", "base", "cell", "pos",
// "rot", "scale", "disabled"}]} (metres, radians), as dotnet/TerrainExp2's objects mode. Their FormIDs come after every
// overlay record, so the terrain records, the anchors and the Mars plugin keep the FormIDs they have without objects;
// <staging dir>/formids.json lists the new ones.
using System.Text.Json;
using Mutagen.Bethesda.Plugins;
using Mutagen.Bethesda.Plugins.Records;
using Mutagen.Bethesda.Starfield;
using Noggog;

var sfPath = args[0];
var outDir = args[1];
var prm = JsonDocument.Parse(File.ReadAllText(Path.Combine(outDir, "overlays_params.json"))).RootElement;
bool Has(JsonElement e, string k) => e.TryGetProperty(k, out var v) && v.ValueKind is not (JsonValueKind.Null or JsonValueKind.False);

var sfData = Path.GetDirectoryName(Path.GetFullPath(sfPath))!;
var release = StarfieldRelease.Starfield;
var sfEsm = ModKey.FromNameAndExtension("Starfield.esm");
using var sf = StarfieldMod.CreateFromBinaryOverlay(sfPath, release);

// Templates: the Mars overlay records of experiment 2b by default; optional "templates": {"world", "block", "location"}
// (hex FormIDs in Starfield.esm) copy another planet's overlay world instead (make_skyrim_overlay.py --planet: a Jemison
// world, so the copy carries Jemison's climate / location parent rather than Mars's).
uint Tpl(string k, uint dflt) => prm.TryGetProperty("templates", out var t) && t.TryGetProperty(k, out var v)
    ? Convert.ToUInt32(v.GetString(), 16) : dflt;
var templateWorld = sf.Worldspaces.First(w => w.FormKey.ID == Tpl("world", 0x02DF8C));                                   // LC172World (Mars)
var templateBlock = sf.EnumerateMajorRecords<ISurfaceBlockGetter>().First(b => b.FormKey.ID == Tpl("block", 0x102382));   // OverlayBlockLC172World
var templateLoc = sf.Locations.First(l => l.FormKey.ID == Tpl("location", 0x3807BE));                                    // LC172WorldLocation
Console.WriteLine($"templates: WRLD {templateWorld.EditorID}, SFBK {templateBlock.EditorID}, LCTN {templateLoc.EditorID}");

var modKey = ModKey.FromNameAndExtension(prm.GetProperty("plugin").GetString()!);
var mod = new StarfieldMod(modKey, release);
mod.ModHeader.Flags |= StarfieldModHeader.HeaderFlag.Master;
var overlays = prm.GetProperty("overlays").EnumerateArray().ToList();

// anchors take the first FormIDs, in params order (plan.json names them as 0x800 + index)
uint next = 0x800;
foreach (var o in overlays)
{
    uint want = o.GetProperty("anchor").GetProperty("form_id").GetUInt32();
    if (want != next) throw new InvalidDataException($"anchor form_id 0x{want:X} out of order (expected 0x{next:X})");
    next++;
}
FormKey NewKey() => new(modKey, next++);

float hmin = prm.GetProperty("hmin").GetSingle(), hmax = prm.GetProperty("hmax").GetSingle();
bool absolute = prm.GetProperty("alignment").GetString() == "absolute";
short hnam = prm.GetProperty("hnam").GetInt16();
var worlds = new List<(Worldspace World, JsonElement Params)>();
var cellsOf = new Dictionary<string, Dictionary<(int, int), Cell>>();
int idx = 0;
foreach (var o in overlays)
{
    string world = o.GetProperty("world").GetString()!;
    int n = o.GetProperty("n").GetInt32(), cmin = o.GetProperty("cell_min").GetInt32(), cmax = o.GetProperty("cell_max").GetInt32();

    var block = (SurfaceBlock)templateBlock.Duplicate(NewKey());
    block.EditorID = o.GetProperty("block").GetString();
    block.ANAM = o.GetProperty("btd_path").GetString();
    block.DNAM = new SurfaceBlockIntItem { First = (uint)n, Second = (uint)n };
    // ENAM holds two floats; Mutagen 0.55 types them as uint, so pass the IEEE bits
    block.ENAM = new SurfaceBlockFloatItem { First = BitConverter.SingleToUInt32Bits(hmin), Second = BitConverter.SingleToUInt32Bits(hmax) };
    var fnam = o.GetProperty("fnam").EnumerateArray().Select(e => (ushort)e.GetInt32()).ToArray();
    if (fnam.Length != n * n) throw new InvalidDataException($"{world}: fnam has {fnam.Length} values, DNAM needs {n * n}");
    block.FNAM = fnam.SelectMany(v => new[] { (byte)(v & 0xFF), (byte)(v >> 8) }).ToArray();
    block.INAM = (byte)(absolute ? 1 : 0);
    block.HNAM = unchecked((ushort)hnam);
    block.Components.Clear();                                                // drop BlockEditorMetaData (CK bookkeeping)
    mod.SurfaceBlocks.Add(block);

    var loc = (Location)templateLoc.Duplicate(NewKey());
    loc.EditorID = o.GetProperty("location").GetString();
    // optional "name" (make_skyrim_overlay.py sets it); without it the FO4 name as before
    var displayName = Has(o, "name") ? o.GetProperty("name").GetString()!
                                     : $"Commonwealth {o.GetProperty("tag").GetString()} (FO4 terrain)";
    loc.Name = displayName;
    loc.MasterSpecialReferences?.Clear();
    loc.MasterInitiallyDisabledReferences?.Clear();
    loc.Keywords = new ExtendedList<IFormLinkGetter<IKeywordGetter>> { new FormLink<IKeywordGetter>(new FormKey(sfEsm, 0x2CA99D)) };
    // parent: SSol_PMars_Surface by default; "location_parent" (hex) for another planet (Jemison: 01AB2B
    // SAlphaCentauri_PJemison_Surface, owner's SfInspect dump)
    loc.ParentLocation.SetTo(new FormKey(sfEsm, prm.TryGetProperty("location_parent", out var lp)
        ? Convert.ToUInt32(lp.GetString(), 16) : 0x01B736));
    mod.Locations.Add(loc);

    var w = (Worldspace)templateWorld.Duplicate(NewKey());
    w.EditorID = world;
    w.Name = displayName;
    w.SubCells.Clear();
    w.TopCell = null;
    w.OffsetData = null;
    w.CellSizeData = null;
    w.Location.SetTo(loc.FormKey);
    // "world_overrides" {"biome", "climate"} (hex): the Mars template's biome (2A3777) drives its ground cover / weather;
    // another planet uses one of its own (Jemison: New Atlantis's biome 1CBD6A and climate 24E982, owner's dump)
    if (prm.TryGetProperty("world_overrides", out var wo))
    {
        if (wo.TryGetProperty("biome", out var bi)) w.Biome.SetTo(new FormKey(sfEsm, Convert.ToUInt32(bi.GetString(), 16)));
        if (wo.TryGetProperty("climate", out var cl)) w.Climate.SetTo(new FormKey(sfEsm, Convert.ToUInt32(cl.GetString(), 16)));
        Console.WriteLine($"  {world}: biome {w.Biome.FormKey}, climate {w.Climate.FormKey}, location parent {loc.ParentLocation.FormKey}");
    }
    w.Components.OfType<WorldSpaceOverlayComponent>().First().SurfaceBlock.SetTo(block.FormKey);
    // object bounds are raw metres; Mutagen shows them divided by 4096
    float bmin = o.GetProperty("bounds_min_m").GetSingle() / 4096f, bmax = o.GetProperty("bounds_max_m").GetSingle() / 4096f;
    w.ObjectBoundsMin = new P2Float(bmin, bmin);
    w.ObjectBoundsMax = new P2Float(bmax, bmax);

    var spawn = o.GetProperty("spawn").EnumerateArray().Select(e => e.GetSingle()).ToArray();
    var spawnCell = o.GetProperty("spawn_cell").EnumerateArray().Select(e => e.GetInt32()).ToArray();
    string coc = o.GetProperty("coc").GetString()!;
    var blocks = new Dictionary<(int, int), WorldspaceBlock>();
    var subs = new Dictionary<(int, int), WorldspaceSubBlock>();
    var cellAt = cellsOf[world] = new Dictionary<(int, int), Cell>();
    for (int x = cmin; x <= cmax; x++)
        for (int y = cmin; y <= cmax; y++)
        {
            // As every vanilla exterior cell (owner's compare_cells.py: NewAtlantis, Dazra, LC030World, LC172World):
            // DATA = HasWater (0x2), XCLW = float.MaxValue ("no water here"), XILS 1.0. Without them (Mutagen leaves
            // the nullable Flags null, so no DATA; `Flags |= HasWater` on null stays null) the Creation Kit refused
            // our cells: "Error adding cell ... to world space ... Cell will be destroyed".
            var c = new Cell(NewKey(), release)
            {
                Grid = new CellGrid { Point = new P2Int(x, y) },
                Flags = Cell.Flag.HasWater,
                WaterHeight = float.MaxValue,
                XILS = 1f,
            };
            cellAt[(x, y)] = c;
            if (x == spawnCell[0] && y == spawnCell[1])
            {
                c.EditorID = coc;
                c.Temporary.Add(new PlacedObject(NewKey(), release)
                {
                    EditorID = coc + "Marker",
                    Base = new FormLinkNullable<IPlaceableObjectGetter>(new FormKey(sfEsm, 0x000032)),   // COCMarkerHeading
                    Position = new P3Float(spawn[0], spawn[1], spawn[2]),
                    Rotation = new P3Float(0, 0, 0),
                });
            }
            int bx = (int)Math.Floor(x / 32.0), by = (int)Math.Floor(y / 32.0), sx = (int)Math.Floor(x / 8.0), sy = (int)Math.Floor(y / 8.0);
            if (!blocks.TryGetValue((bx, by), out var blk)) { blk = new WorldspaceBlock { BlockNumberX = (short)bx, BlockNumberY = (short)by, GroupType = GroupTypeEnum.ExteriorCellBlock }; blocks[(bx, by)] = blk; w.SubCells.Add(blk); }
            if (!subs.TryGetValue((sx, sy), out var sub)) { sub = new WorldspaceSubBlock { BlockNumberX = (short)sx, BlockNumberY = (short)sy, GroupType = GroupTypeEnum.ExteriorCellSubBlock }; subs[(sx, sy)] = sub; blk.Items.Add(sub); }
            sub.Items.Add(c);
        }
    w.TopCell = new Cell(NewKey(), release) { Flags = Cell.Flag.HasWater };   // persistent top cell (as experiments 1 and 2)
    // Optional "water": {"form": hex WATR, "cells": [[x, y, height_m], ...]} (make_skyrim_overlay.py --skyrim-water):
    // Skyrim's river / lake levels as cell water (XCLW / XCWT / HasWater), listed on the world like New Atlantis's
    // CellWaterHeightLocations + WaterHeights (owner's SfInspect dump). Supported hypothesis, not yet seen in game.
    if (Has(prm, "water"))
    {
        var wp = prm.GetProperty("water");
        var waterKey = new FormKey(sfEsm, Convert.ToUInt32(wp.GetProperty("form").GetString(), 16));
        var locs = new ExtendedList<P2Int16>();
        var hts = new ExtendedList<float>();
        int nWater = 0;
        foreach (var e in wp.GetProperty("cells").EnumerateArray())
        {
            var v = e.EnumerateArray().ToArray();
            int wx = v[0].GetInt32(), wy = v[1].GetInt32();
            float h = v[2].GetSingle();
            if (!cellAt.TryGetValue((wx, wy), out var wc)) continue;
            wc.Flags = (wc.Flags ?? 0) | Cell.Flag.HasWater;
            wc.WaterHeight = h;
            wc.Water.SetTo(waterKey);
            locs.Add(new P2Int16((short)wx, (short)wy));
            hts.Add(h);
            nWater++;
        }
        // The world-level lists stay off by default: their coordinates are not cell coordinates (New Atlantis lists
        // (5, -6) .. (3, -4) for a much larger city), and with them the owner saw cell-sized water sheets far away and
        // in the sky that vanished up close, where the cells' own XCLW water drew right. "world_lists": true restores.
        if (wp.TryGetProperty("world_lists", out var wl) && wl.GetBoolean())
        {
            w.CellWaterHeightLocations = locs;
            w.WaterHeights = hts;
        }
        else
        {
            w.CellWaterHeightLocations = null;
            w.WaterHeights = null;
        }
        Console.WriteLine($"  {world}: {nWater} cells with water (WATR {waterKey}), world lists {(w.WaterHeights != null ? "on" : "off")}");
    }
    var a = o.GetProperty("anchor");
    var p = a.GetProperty("local").EnumerateArray().Select(e => e.GetSingle()).ToArray();
    var anchor = new PlacedObject(new FormKey(modKey, a.GetProperty("form_id").GetUInt32()), release)
    {
        EditorID = a.GetProperty("edid").GetString(),
        Base = new FormLinkNullable<IPlaceableObjectGetter>(new FormKey(sfEsm, 0x00003B)),            // XMarker
        Position = new P3Float(p[0], p[1], p[2]),
        Rotation = new P3Float(0, 0, 0),
    };
    anchor.MajorRecordFlagsRaw |= 0x400;                                     // Persistent
    w.TopCell.Persistent.Add(anchor);
    mod.Worldspaces.Add(w);
    worlds.Add((w, o));
    Console.WriteLine($"  {world}: WRLD {w.FormKey}, SFBK {block.FormKey} -> {block.ANAM}, LCTN {loc.FormKey}, anchor {anchor.FormKey} at ({p[0]}, {p[1]}, {p[2]}), " +
                      $"{(cmax - cmin + 1) * (cmax - cmin + 1)} cells {cmin}..{cmax}, COC {coc} in ({spawnCell[0]}, {spawnCell[1]})");
    idx++;
}
int nStat = 0, nDoor = 0, nRef = 0, nDisabled = 0;
if (Has(prm, "objects"))
{
    // core64c: converted FO4 models and their references, allocated after every overlay record
    using var odoc = JsonDocument.Parse(File.ReadAllText(Path.Combine(outDir, prm.GetProperty("objects").GetString()!)));
    var o = odoc.RootElement;
    string world = o.TryGetProperty("world", out var wj) ? wj.GetString()! : worlds[0].World.EditorID!;
    if (!cellsOf.TryGetValue(world, out var cellAt)) throw new InvalidDataException($"objects.json names world {world}, not an overlay of these params");
    var baseKeys = new List<FormKey>();
    var baseIds = new Dictionary<string, string>();
    // "lod_layer" (make_skyrim_objects.py lod): the LAYR whose EditorID names this base's composite LOD files
    // (<layer>_<x>_<y>_lod_<L>_cell0.nif). Vanilla: Gagarin_LOD_Grp012 / NA_LOD_ApolloTower are LAYR records (owner's
    // find_in_plugin.py run); references join a layer through XLYR. LodBehavior from "lod_behavior" (default Aggregate).
    var layerByBase = new Dictionary<int, FormKey>();
    var layers = new Dictionary<string, Layer>();
    var vanillaLayers = new HashSet<string>();
    var lodBehavior = Has(o, "lod_behavior")
        ? Enum.Parse<Layer.LodBehaviorType>(o.GetProperty("lod_behavior").GetString()!) : Layer.LodBehaviorType.Aggregate;
    {
        int bi = 0;
        foreach (var b in o.GetProperty("bases").EnumerateArray())
        {
            if (b.TryGetProperty("lod_layer", out var lj))
            {
                var ln = lj.GetString()!;
                // a vanilla LAYR of that EditorID (make_skyrim_objects.py lod --lod-layer, diagnostic) is used as is
                var vanillaLayer = sf.Layers.FirstOrDefault(l => string.Equals(l.EditorID, ln, StringComparison.OrdinalIgnoreCase));
                if (vanillaLayer != null)
                {
                    if (!vanillaLayers.Contains(ln)) { vanillaLayers.Add(ln); Console.WriteLine($"LOD layer {ln}: vanilla {vanillaLayer.FormKey}"); }
                    layerByBase[bi] = vanillaLayer.FormKey;
                    bi++;
                    continue;
                }
                if (!layers.TryGetValue(ln, out var layer))
                {
                    layer = new Layer(NewKey(), release) { EditorID = ln, LodBehavior = lodBehavior };
                    mod.Layers.Add(layer);
                    layers[ln] = layer;
                }
                layerByBase[bi] = layer.FormKey;
            }
            bi++;
        }
        if (layers.Count > 0 || vanillaLayers.Count > 0)
        {
            // as vanilla Gagarin: the LOD layers sit under one parent layer (Gagarin_LOD_Grp012 -> Gagarin_LOD), and the
            // world's HNAM is [5] (SettleGagarinWorld, NewAtlantis: worlds with composite LOD) where the Mars template
            // LC172World (no composites) has [0] (owner's SfInspect wrld dumps). HNAM's meaning is unresolved.
            var parent = new Layer(NewKey(), release) { EditorID = world + "_LOD", LodBehavior = Layer.LodBehaviorType.Default };
            mod.Layers.Add(parent);
            foreach (var l in layers.Values) l.Parent.SetTo(parent.FormKey);
            var lw = worlds.First(x => x.World.EditorID == world).World;
            var hp = lw.GetType().GetProperty("HNAM")!;
            var ht = Nullable.GetUnderlyingType(hp.PropertyType) ?? hp.PropertyType;
            object hv = ht == typeof(byte[]) ? new byte[] { 5 } : System.Activator.CreateInstance(ht, new object[] { new byte[] { 5 } })!;
            hp.SetValue(lw, hv);
            Console.WriteLine($"{layers.Count} LOD layers ({lodBehavior}) under {parent.EditorID}; {world} HNAM = [5]");
            // The overlay component's SNAM / PNAM (Mutagen: unknown byte arrays). Every world whose composite LOD draws
            // (NewAtlantis, ShatteredSpace's Dazra, LC030World) has SNAM = a placed reference of that world and PNAM
            // with bit 0 set (3, 0x15, 1); the Mars template LC172World and ours had SNAM 0 and PNAM 4 (owner's
            // compare_worlds.py / SfInspect runs). Supported hypothesis, unverified: SNAM = our persistent anchor
            // (raw FormID, this plugin = master index 1 after Starfield.esm), PNAM |= 1.
            var ov = lw.Components.OfType<WorldSpaceOverlayComponent>().First();
            void SetBytes(object target, string prop, byte[] value)
            {
                var pp = target.GetType().GetProperty(prop)!;
                var pt = Nullable.GetUnderlyingType(pp.PropertyType) ?? pp.PropertyType;
                pp.SetValue(target, pt == typeof(byte[]) ? value : System.Activator.CreateInstance(pt, new object[] { value })!);
            }
            byte[] GetBytes(object target, string prop)
            {
                var v = target.GetType().GetProperty(prop)!.GetValue(target);
                if (v == null) return new byte[4];
                if (v is byte[] b) return b;
                var arr = v.GetType().GetMethod("ToArray", Type.EmptyTypes)!.Invoke(v, null);
                return (byte[])arr!;
            }
            var anchorRef = lw.TopCell!.Persistent.OfType<PlacedObject>().First(r => r.EditorID != null);
            var snam = BitConverter.GetBytes(0x01000000u | anchorRef.FormKey.ID);
            SetBytes(ov, "SNAM", snam);
            var pnam = GetBytes(ov, "PNAM").ToArray();
            if (pnam.Length == 0) pnam = new byte[4];
            pnam[0] |= 1;
            SetBytes(ov, "PNAM", pnam);
            Console.WriteLine($"{world} overlay component: SNAM = anchor {anchorRef.FormKey} (raw {BitConverter.ToUInt32(snam):X8}), PNAM = [{string.Join(", ", pnam)}]");
        }
    }
    foreach (var b in o.GetProperty("bases").EnumerateArray())
    {
        var edid = b.GetProperty("edid").GetString()!;
        var model = b.GetProperty("model").GetString()!;
        if (b.TryGetProperty("door", out var d) && d.ValueKind == JsonValueKind.Object)
        {
            // hinged door rigged like the vanilla template door (as PluginSpike and TerrainExp2): graph, skeleton, bounds
            var rec = new Door(NewKey(), release)
            {
                EditorID = edid, Model = new Model { File = model }, Name = "Door",
                SoundLevel = SoundLevel.Normal, FacingAxisOverride = Door.FacingAxisOverrideEnum.BasedOnBounds,
            };
            if (d.TryGetProperty("bounds", out var bj))
                rec.ObjectBounds = new ObjectBounds
                {
                    First = new P3Float(bj[0][0].GetSingle(), bj[0][1].GetSingle(), bj[0][2].GetSingle()),
                    Second = new P3Float(bj[1][0].GetSingle(), bj[1][1].GetSingle(), bj[1][2].GetSingle()),
                };
            rec.Components.Add(new AnimationGraphComponent
            {
                ANAM = d.GetProperty("anim_graph").GetString(), BNAM = d.GetProperty("skeleton").GetString(),
                CNAM = d.GetProperty("animations").GetString(),
            });
            mod.Doors.Add(rec);
            baseKeys.Add(rec.FormKey);
            nDoor++;
        }
        else
        {
            var stat = new Static(NewKey(), release) { EditorID = edid, Model = new Model { File = model } };
            // "bounds" [[min xyz], [max xyz]] (metres, make_skyrim_objects.py lod): OBND, as every vanilla static has
            if (b.TryGetProperty("bounds", out var sb) && sb.ValueKind == JsonValueKind.Array)
                stat.ObjectBounds = new ObjectBounds
                {
                    First = new P3Float(sb[0][0].GetSingle(), sb[0][1].GetSingle(), sb[0][2].GetSingle()),
                    Second = new P3Float(sb[1][0].GetSingle(), sb[1][1].GetSingle(), sb[1][2].GetSingle()),
                };
            // "distant_lod" (make_skyrim_objects.py lod): composite distant LOD exists for this base
            if (b.TryGetProperty("distant_lod", out var dl) && dl.GetBoolean())
                stat.MajorRecordFlagsRaw |= 0x8000;                                  // Static.MajorFlag.HasDistantLod
            mod.Statics.Add(stat);
            baseKeys.Add(stat.FormKey);
            nStat++;
        }
        baseIds[edid] = baseKeys[^1].ID.ToString("X6");
    }
    var refIds = new Dictionary<string, string>();
    // "large_cells" (make_skyrim_objects.py lod): the reference is a large reference, listed in the world's RNAM under
    // every cell its bounds cover (with its own cell). NewAtlantis and ShatteredSpace's Dazra (composite LOD that draws)
    // have RNAM; LC172World and ours had none (owner's compare_worlds.py). Mutagen: Worldspace.LargeReferences.
    var large = new SortedDictionary<(int, int), List<WorldspaceReference>>();
    foreach (var r in o.GetProperty("refs").EnumerateArray())
    {
        float[] V(string k) => r.GetProperty(k).EnumerateArray().Select(e => e.GetSingle()).ToArray();
        var cxy = r.GetProperty("cell").EnumerateArray().Select(e => e.GetInt32()).ToArray();
        if (!cellAt.TryGetValue((cxy[0], cxy[1]), out var cell))
            throw new InvalidDataException($"reference {r.GetProperty("src").GetString()} in cell ({cxy[0]}, {cxy[1]}) outside {world}'s cells");
        var pos = V("pos");
        var rot = V("rot");
        var obj = new PlacedObject(NewKey(), release)
        {
            Base = new FormLinkNullable<IPlaceableObjectGetter>(baseKeys[r.GetProperty("base").GetInt32()]),
            Position = new P3Float(pos[0], pos[1], pos[2]),
            Rotation = new P3Float(rot[0], rot[1], rot[2]),
        };
        var scale = r.GetProperty("scale").GetSingle();
        if (Math.Abs(scale - 1f) > 1e-4) obj.Scale = scale;
        if (layerByBase.TryGetValue(r.GetProperty("base").GetInt32(), out var lk)) obj.Layer.SetTo(lk);
        if (r.GetProperty("disabled").GetBoolean())
        {
            obj.MajorRecordFlagsRaw |= 0x800;                                // Initially Disabled, as in FO4
            nDisabled++;
        }
        cell.Temporary.Add(obj);
        if (r.TryGetProperty("large_cells", out var lc))
            foreach (var g in lc.EnumerateArray())
            {
                var key = (g[0].GetInt32(), g[1].GetInt32());
                if (!large.TryGetValue(key, out var lst)) large[key] = lst = new List<WorldspaceReference>();
                lst.Add(new WorldspaceReference
                {
                    Reference = new FormLink<IPlacedObjectGetter>(obj.FormKey),
                    Position = new P2Int16((short)cxy[0], (short)cxy[1]),
                });
            }
        refIds[r.GetProperty("src").GetString()!] = obj.FormKey.ID.ToString("X6");
        nRef++;
    }
    if (large.Count > 0)
    {
        var lw = worlds.First(x => x.World.EditorID == world).World;
        lw.LargeReferences.Clear();
        foreach (var (key, lst) in large)
        {
            var gr = new WorldspaceGridReference { GridPosition = new P2Int16((short)key.Item1, (short)key.Item2) };
            gr.References.AddRange(lst);
            lw.LargeReferences.Add(gr);
        }
        Console.WriteLine($"{world}: {large.Values.Sum(l => l.Count):N0} large-reference entries in {large.Count:N0} cells (RNAM)");
    }
    var ids = new Dictionary<string, object> { ["plugin"] = modKey.FileName.String, ["world"] = world, ["bases"] = baseIds, ["refs"] = refIds };
    File.WriteAllText(Path.Combine(outDir, "formids.json"), JsonSerializer.Serialize(ids));
}
// Optional "ltex_overrides": [{"form_id", "material", ...}] (make_skyrim_overlay.py build --skyrim-ground,
// src/fo4sf/skyrimground.py): spare Starfield.esm LTEX records (no vanilla BTD or biome uses them) overridden with BNAM
// = a material made from a Skyrim ground texture. Same FormKey as the vanilla record, so the BTD's raw FormIDs resolve.
// BNAM is set by reflection (AssetLink type differs between Mutagen versions); a failure is reported, not fatal.
if (Has(prm, "ltex_overrides"))
{
    int nLtex = 0;
    foreach (var lo in prm.GetProperty("ltex_overrides").EnumerateArray())
    {
        var fk = new FormKey(sfEsm, lo.GetProperty("form_id").GetUInt32());
        var src = sf.LandscapeTextures.FirstOrDefault(l => l.FormKey == fk);
        if (src == null) { Console.WriteLine($"  LTEX {fk} not in Starfield.esm: skipped"); continue; }
        var lt = (LandscapeTexture)src.DeepCopy();
        var matPath = lo.GetProperty("material").GetString()!;
        var prop = typeof(LandscapeTexture).GetProperty("MaterialPath")!;
        var t = Nullable.GetUnderlyingType(prop.PropertyType) ?? prop.PropertyType;
        try
        {
            object? link = t == typeof(string) ? matPath : System.Activator.CreateInstance(t, matPath);
            prop.SetValue(lt, link);
        }
        catch (Exception e)
        {
            Console.WriteLine($"  LTEX {fk}: could not set MaterialPath ({t.Name}): {e.GetType().Name} {e.Message}");
            continue;
        }
        mod.LandscapeTextures.Add(lt);
        nLtex++;
    }
    Console.WriteLine($"{nLtex} Starfield LTEX overridden with Skyrim ground materials");
}

mod.ModHeader.Stats.NextFormID = next;
var path = Path.Combine(outDir, modKey.FileName);
mod.BeginWrite.ToPath(path).WithLoadOrderFromHeaderMasters().WithDataFolder(sfData)
    .WithKnownMasters(new KeyedMasterStyle(sfEsm, MasterStyle.Full)).Write();
Console.WriteLine($"wrote {path} ({new FileInfo(path).Length:N0} bytes): {worlds.Count} overlays, next FormID 0x{next:X}" +
                  (Has(prm, "objects") ? $"; objects: {nStat} STAT, {nDoor} DOOR, {nRef} REFR ({nDisabled} initially disabled)" : ""));

if (Has(prm, "mars"))
{
    var m = prm.GetProperty("mars");
    var marsKey = ModKey.FromNameAndExtension(m.GetProperty("plugin").GetString()!);
    var mars = new StarfieldMod(marsKey, release);
    mars.ModHeader.Flags |= StarfieldModHeader.HeaderFlag.Master;
    var planetEdid = m.TryGetProperty("planet", out var pe) ? pe.GetString()! : "MarsPlanetData";
    var planet = (Planet)sf.Planets.First(pl => pl.EditorID == planetEdid).DeepCopy();   // same FormKey = override
    mars.Planets.Add(planet);
    foreach (var (w, o) in worlds)
        planet.MasterWorldspaces!.Add(new MasterWorldspace
        {
            Worldspace = new FormLink<IWorldspaceGetter>(w.FormKey),
            Longitude = o.GetProperty("latitude").GetDouble(),     // first f64 of the entry = latitude
            Latitude = o.GetProperty("longitude").GetDouble(),     // second f64 = longitude
        });
    mars.ModHeader.Stats.NextFormID = 0x800;
    var marsPath = Path.Combine(outDir, marsKey.FileName);
    mars.BeginWrite.ToPath(marsPath).WithLoadOrder(sfEsm, modKey)
        .WithKnownMasters(new KeyedMasterStyle(sfEsm, MasterStyle.Full), new KeyedMasterStyle(modKey, MasterStyle.Full)).Write();
    Console.WriteLine($"wrote {marsPath} ({new FileInfo(marsPath).Length:N0} bytes); {planetEdid} master worldspaces now {planet.MasterWorldspaces!.Count}");
}
