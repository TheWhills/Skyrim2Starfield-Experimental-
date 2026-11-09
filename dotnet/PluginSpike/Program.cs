// Plugin writer for converted assets (S2 -> WP-08 / WP-10).
//   dotnet run -- <output dir> <manifest.json> [cell.json ... | @cells.txt (one cell.json path per line)]
// Creates FO4Port.esm with one STAT per converted item and, for each cell export from dotnet/Fo4Export, an interior cell
// "FO4Port_<cell>" holding every reference whose model was converted, placed at the Fallout 4 position / 70 (metres), same rotation
// (radians) and scale. Initially-disabled FO4 references stay initially disabled.
//
// FormIDs are STABLE: <output dir>/formids.json maps an identity key to its FormID and is reused on every run, so adding or
// removing assets never renumbers existing records (saves and cross-references keep working). Keys:
//   STAT:<editor id>   CELL:<cell name>   REFR:<cell name>:<source FO4 FormKey>   (lights and COC markers use their source ref)
//   LOADDOOR:<editor id> (a converted model used by a linked load door)   NAVM:<cell name>:<source navmesh>
// <output dir>/source_map.json: source form key (Skyrim / FO4 reference, cell, navmesh) -> new FormKey, for the later steps
// (NPCs, packages, furniture) that refer to the source game's records.
using System.Text.Json;
using System.Globalization;
using Mutagen.Bethesda.Plugins;
using Mutagen.Bethesda.Plugins.Binary.Parameters;
using Mutagen.Bethesda.Plugins.Cache;
using Mutagen.Bethesda.Plugins.Records;
using Mutagen.Bethesda.Starfield;
using Noggog;

const float UnitsPerMetre = 70f;
const uint FirstId = 0x800;
var outDir = args[0];
Directory.CreateDirectory(outDir);

var modKey = ModKey.FromNameAndExtension("FO4Port.esm");
var sfEsm = ModKey.FromNameAndExtension("Starfield.esm");
var release = StarfieldRelease.Starfield;
var mod = new StarfieldMod(modKey, release);
mod.ModHeader.Flags |= StarfieldModHeader.HeaderFlag.Master;

// ---- stable FormID map ------------------------------------------------------------------------------------------------
var mapPath = Path.Combine(outDir, "formids.json");
var ids = File.Exists(mapPath)
    ? JsonSerializer.Deserialize<Dictionary<string, uint>>(File.ReadAllText(mapPath))!
    : new Dictionary<string, uint>();
var next = ids.Count == 0 ? FirstId : ids.Values.Max() + 1;
var usedThisRun = new HashSet<string>();
var sourceMap = new SortedDictionary<string, string>();      // source form key -> new FormKey (source_map.json)
// every navmesh written (interiors and exterior), for the NAVI entries and the load doors' XNDP: its key, geometry and
// parent (world + grid, or cell)
var navInfos = new List<(FormKey nav, NavmeshGeometry geo, FormKey? world, short gx, short gy, FormKey? cell)>();
FormKey Id(string key)
{
    if (!usedThisRun.Add(key)) throw new InvalidOperationException($"duplicate identity key {key}");
    if (!ids.TryGetValue(key, out var v)) { v = next++; ids[key] = v; }
    return new FormKey(modKey, v);
}

// ---- statics ----------------------------------------------------------------------------------------------------------
var items = new List<(string editorId, string model, string source, JsonElement? door)>();
using var manifestDoc = JsonDocument.Parse(File.ReadAllText(args[1]));
foreach (var it in manifestDoc.RootElement.GetProperty("items").EnumerateArray())
    items.Add((it.GetProperty("editor_id").GetString()!, it.GetProperty("model").GetString()!, it.GetProperty("source").GetString()!,
               it.TryGetProperty("door", out var dj) ? dj : null));

// source FO4 model -> (base record, origin offset in metres). Hinged doors become DOOR records animated by a vanilla door's
// graph / skeleton / animations; their NIF origin sits at a different point, so references are shifted by origin_offset.
var bySource = new Dictionary<string, (FormKey key, P3Float offset)>(StringComparer.OrdinalIgnoreCase);
var itemBySource = items.ToDictionary(i => i.source.Replace('/', '\\'), i => i, StringComparer.OrdinalIgnoreCase);
int doors = 0;
foreach (var (editorId, model, source, door) in items)
{
    if (door is JsonElement d)
    {
        var rec = new Door(Id("DOOR:" + editorId), release)
        {
            // FO4PORT_DOOR_MODEL (test hook): use this model for every door, e.g. the vanilla template door's own NIF
            EditorID = editorId, Model = new Model { File = Environment.GetEnvironmentVariable("FO4PORT_DOOR_MODEL") ?? model },
            Name = "Door",
            SoundLevel = SoundLevel.Normal,                                     // DEVT 1, as vanilla doors
            FacingAxisOverride = Door.FacingAxisOverrideEnum.BasedOnBounds,     // trailing ANAM, as vanilla doors
        };
        if (d.TryGetProperty("bounds", out var bj))                            // vanilla doors have real bounds
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
        var o = d.GetProperty("origin_offset");
        bySource[source.Replace('/', '\\')] = (rec.FormKey, new P3Float(o[0].GetSingle(), o[1].GetSingle(), o[2].GetSingle()));
        if (Environment.GetEnvironmentVariable("FO4PORT_DOOR_BASE") is string vb)   // test hook: place a vanilla DOOR instead
            bySource[source.Replace('/', '\\')] = (new FormKey(sfEsm, Convert.ToUInt32(vb, 16)), new P3Float(0, 0, 0));
        doors++;
        continue;
    }
    var stat = new Static(Id("STAT:" + editorId), release) { EditorID = editorId, Model = new Model { File = model } };
    mod.Statics.Add(stat);
    bySource[source.Replace('/', '\\')] = (stat.FormKey, new P3Float(0, 0, 0));
}
Console.WriteLine($"{items.Count - doors} statics, {doors} doors");

// FO4 / Starfield reference rotation (radians): Bethesda angles turn CLOCKWISE seen from the positive axis, so the matrix
// uses the negated angles; applied X, then Y, then Z. Rotates a door-local offset into the cell. (0 / 180 degree doors are
// the same either way; the 135 / 225 degree double doors in Parsons looked misplaced with the counter-clockwise version.
// To verify in game.)
static P3Float RotateOffset(P3Float v, P3Float r, float scale)
{
    double cx = Math.Cos(-r.X), sx = Math.Sin(-r.X), cy = Math.Cos(-r.Y), sy = Math.Sin(-r.Y), cz = Math.Cos(-r.Z), sz = Math.Sin(-r.Z);
    double x = v.X * scale, y = v.Y * scale, z = v.Z * scale;
    double y1 = y * cx - z * sx, z1 = y * sx + z * cx;           // about X
    double x2 = x * cy + z1 * sy, z2 = -x * sy + z1 * cy;          // about Y
    double x3 = x2 * cz - y1 * sz, y3 = x2 * sz + y1 * cz;         // about Z
    return new P3Float((float)x3, (float)y3, (float)z2);
}

// Optional per-cell lighting overrides: <output dir>/lighting.json = { "<cell>": { "LIGHTING_TEMPLATE": "06BCF8", ... },
// "*": { ...defaults for every cell... } }. Keys: LIGHTING_TEMPLATE, IMAGE_SPACE, OMNI_LIGHT, LIGHT_MERGE_M; for cells
// exported from Skyrim also SKYRIM_LIGHTS (0 = the plain omni), LIGHT_POWER, LIGHT_RADIUS_SCALE, LIGHT_TEMPERATURE
// (skyrim | keep), CELL_AMBIENT (template | skyrim), AMBIENT_SCALE (see "Skyrim lights" below).
// Lookup order: cell entry, "*" entry, environment variable, built-in default.
var lightCfgPath = Path.Combine(outDir, "lighting.json");
var lightCfg = File.Exists(lightCfgPath)
    ? JsonSerializer.Deserialize<Dictionary<string, Dictionary<string, string>>>(File.ReadAllText(lightCfgPath))!
    : new Dictionary<string, Dictionary<string, string>>();
string Setting(string cell, string key, string fallback) =>
    lightCfg.TryGetValue(cell, out var c) && c.TryGetValue(key, out var v) ? v
    : lightCfg.TryGetValue("*", out var d) && d.TryGetValue(key, out var w) ? w
    : Environment.GetEnvironmentVariable(key) ?? fallback;

// ---- Skyrim lights (cell refs carrying a "light" object, from scripts/interior/make_skyrim_interior.py) -----------------
// One Starfield LIGH per distinct Skyrim light: a copy of the cell's OMNI_LIGHT base with the Skyrim radius (units / 70 =
// metres, x LIGHT_RADIUS_SCALE), colour, flicker, a colour temperature estimated from the colour (LIGHT_TEMPERATURE=keep
// leaves the template's) and luminous power = template lumens x LIGHT_POWER x max(fade, 1) x max(1, (radius / template
// radius)^2), clamped to 1x..16x of the template's (owner's first run: scaling below the template made the inn darker). Field names follow Mutagen's Starfield Light (DAT2: Radius, Color,
// FlickerPeriod, FlickerIntensityAmplitude, FlickerMovementAmplitude, PbrLightTemperatureK, PbrLuminousPowerLm); they are
// set by reflection so a renamed field is reported (lightNotes) instead of breaking the build.
// CELL_AMBIENT=skyrim (opt-in): the cell gets its own XCLL, copied field by field from its lighting template, with the
// Skyrim cell's ambient / directional colours (x AMBIENT_SCALE).
var sfData0 = Environment.GetEnvironmentVariable("STARFIELD_DATA");
IStarfieldModGetter? sfMod = null;          // Starfield.esm, read lazily (only when a Skyrim light or CELL_AMBIENT needs it)
ILinkCache? sfCache = null;
ILinkCache SfCache()
{
    if (sfCache != null) return sfCache;
    var esm = Path.Combine(sfData0 ?? throw new InvalidOperationException("set STARFIELD_DATA to the Starfield Data folder"), "Starfield.esm");
    var overlay = StarfieldMod.CreateFromBinaryOverlay(esm, release);    // as dotnet/SfInspect
    sfMod = overlay;
    return sfCache = overlay.ToImmutableLinkCache();
}
var lightNotes = new SortedSet<string>();
var lightBases = new Dictionary<string, FormKey>();
object? GetProp(object o, string name) => o.GetType().GetProperty(name)?.GetValue(o);
void SetProp(object o, string name, object value)
{
    var p = o.GetType().GetProperty(name);
    if (p == null || !p.CanWrite) { lightNotes.Add($"{o.GetType().Name}.{name}: no writable property, not set"); return; }
    var t = Nullable.GetUnderlyingType(p.PropertyType) ?? p.PropertyType;
    try
    {
        p.SetValue(o, t.IsInstanceOfType(value) ? value : Convert.ChangeType(value, t, CultureInfo.InvariantCulture));
    }
    catch (Exception e) { lightNotes.Add($"{o.GetType().Name}.{name} ({t.Name}): {e.GetType().Name}, not set"); }
}
double ToDouble(object? v) => v == null ? 0 : Convert.ToDouble(v, CultureInfo.InvariantCulture);
// McCamy's approximation: sRGB colour -> correlated colour temperature (K), clamped to 1000..10000
static uint ColourTemperature(int r8, int g8, int b8)
{
    static double Lin(int c) { var v = c / 255.0; return v <= 0.04045 ? v / 12.92 : Math.Pow((v + 0.055) / 1.055, 2.4); }
    double r = Lin(r8), g = Lin(g8), b = Lin(b8);
    double X = 0.4124 * r + 0.3576 * g + 0.1805 * b, Y = 0.2126 * r + 0.7152 * g + 0.0722 * b, Z = 0.0193 * r + 0.1192 * g + 0.9505 * b;
    var sum = X + Y + Z;
    if (sum <= 1e-9) return 6500;
    double x = X / sum, y = Y / sum, n = (x - 0.3320) / (0.1858 - y);
    return (uint)Math.Clamp(449 * n * n * n + 3525 * n * n + 6823.3 * n + 5520.33, 1000, 10000);
}
FormKey SkyrimLight(string cell, JsonElement L, FormKey template)
{
    float F(string k, float d) => L.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetSingle() : d;
    var c = L.GetProperty("color");
    int cr = c[0].GetInt32(), cg = c[1].GetInt32(), cb = c[2].GetInt32();
    float power = float.Parse(Setting(cell, "LIGHT_POWER", "1"), CultureInfo.InvariantCulture);
    float rscale = float.Parse(Setting(cell, "LIGHT_RADIUS_SCALE", "1"), CultureInfo.InvariantCulture);
    var temperature = Setting(cell, "LIGHT_TEMPERATURE", "skyrim");
    float radius = Math.Max(F("radius", 300f) / UnitsPerMetre, 1f) * rscale, fade = Math.Max(F("fade", 1f), 0.05f);
    bool flicker = L.TryGetProperty("flicker", out var fl) && fl.ValueKind == JsonValueKind.True;
    var key = string.Create(CultureInfo.InvariantCulture,
        $"LIGH:{template.ID:X6}:{radius:0.00}:{cr},{cg},{cb}:{fade:0.###}:{power:0.###}:{temperature}:{(flicker ? 1 : 0)}");
    if (lightBases.TryGetValue(key, out var have)) return have;
    if (!SfCache().TryResolve<ILightGetter>(template, out var tpl))
        throw new InvalidOperationException($"OMNI_LIGHT {template} is not a LIGH in Starfield.esm");
    var nl = (Light)tpl.Duplicate(Id(key));
    nl.EditorID = $"FO4Port_SkyLight_{lightBases.Count:D3}";
    double tplRadius = ToDouble(GetProp(nl, "Radius")), tplLm = ToDouble(GetProp(nl, "PbrLuminousPowerLm"));
    SetProp(nl, "Radius", radius);
    var oldColour = GetProp(nl, "Color") is System.Drawing.Color oc ? oc : System.Drawing.Color.White;
    SetProp(nl, "Color", System.Drawing.Color.FromArgb(oldColour.A, cr, cg, cb));
    if (temperature != "keep") SetProp(nl, "PbrLightTemperatureK", ColourTemperature(cr, cg, cb));
    if (tplLm > 0)
    {
        // bigger than the template: more lumens to reach as far; smaller: the template's (scaling down made the inn darker)
        var area = tplRadius > 0 ? Math.Max(1.0, Math.Pow(radius / tplRadius, 2)) : 1.0;
        var lm = tplLm * Math.Clamp(power * Math.Max(fade, 1f) * area, 1.0, 16.0);
        SetProp(nl, "PbrLuminousPowerLm", (uint)Math.Round(lm));
    }
    else lightNotes.Add($"template {template} has no PbrLuminousPowerLm: power not scaled");
    if (flicker)
    {
        SetProp(nl, "FlickerPeriod", F("flicker_period", 0.2f));
        SetProp(nl, "FlickerIntensityAmplitude", F("flicker_intensity", 0.2f));
        SetProp(nl, "FlickerMovementAmplitude", F("flicker_movement", 0f));
    }
    mod.Lights.Add(nl);
    lightBases[key] = nl.FormKey;
    if (lightBases.Count <= 12)
        Console.WriteLine(string.Create(CultureInfo.InvariantCulture,
            $"  light {nl.EditorID}: radius {tplRadius:0.##} -> {GetProp(nl, "Radius")} m, lumens {tplLm:0} -> {GetProp(nl, "PbrLuminousPowerLm")}, " +
            $"colour {cr},{cg},{cb}, {GetProp(nl, "PbrLightTemperatureK")} K{(flicker ? ", flicker" : "")}"));
    return nl.FormKey;
}
void SkyrimAmbient(Cell cell, string src4, JsonElement sl, FormKey templateKey)
{
    if (!SfCache().TryResolve<ILightingTemplateGetter>(templateKey, out var tpl))
    {
        lightNotes.Add($"lighting template {templateKey} not found: CELL_AMBIENT ignored");
        return;
    }
    var cl = new CellLighting();
    foreach (var p in typeof(CellLighting).GetProperties().Where(p => p.CanWrite))
    {
        var name = p.Name switch { "LightFadeBegin" => "LightFadeStartDistance", "LightFadeEnd" => "LightFadeEndDistance", var n => n };
        var v = GetProp(tpl, name);
        if (v != null && (Nullable.GetUnderlyingType(p.PropertyType) ?? p.PropertyType).IsInstanceOfType(v)) p.SetValue(cl, v);
    }
    var scale = float.Parse(Setting(src4, "AMBIENT_SCALE", "1"), CultureInfo.InvariantCulture);
    System.Drawing.Color Col(JsonElement a, object? old) => System.Drawing.Color.FromArgb(old is System.Drawing.Color o ? o.A : 0,
        (int)Math.Clamp(a[0].GetInt32() * scale, 0, 255), (int)Math.Clamp(a[1].GetInt32() * scale, 0, 255), (int)Math.Clamp(a[2].GetInt32() * scale, 0, 255));
    if (sl.TryGetProperty("ambient", out var amb)) SetProp(cl, "AmbientColor", Col(amb, GetProp(cl, "AmbientColor")));
    if (sl.TryGetProperty("directional", out var dir)) SetProp(cl, "DirectionalColor", Col(dir, GetProp(cl, "DirectionalColor")));
    cell.Lighting = cl;
    Console.WriteLine($"  cell lighting: template {templateKey} values + Skyrim ambient {amb} x{scale}");
}

// ---- navmeshes ----------------------------------------------------------------------------------------------------------
// cell.json "navmeshes": Skyrim navmeshes already translated to Starfield's layout (src/fo4sf/skyrimnavmesh.py: version 17,
// Skyrim units, Skyrim form keys, links leaving the cell cut). Here: positions / grid to metres, the parent = this cell,
// edge links -> this cell's new navmeshes, door links -> the converted door references (a door that was not placed loses
// its link; the triangles stay). Mutagen's Starfield NavmeshGeometry: names and layout checked against Mutagen's dev source
// (Oct 2026; alpha.67 has no tag): NavmeshGeometry.xml / NavmeshTriangle.cs / TeleportDestination.cs / Door.xml.
string WriteNavmeshes(Cell cell, string cellName, JsonElement root, Dictionary<string, FormKey> placedBySource)
{
    if (!root.TryGetProperty("navmeshes", out var navs) || navs.ValueKind != JsonValueKind.Array) return "";
    var keys = new Dictionary<string, FormKey>();
    foreach (var n in navs.EnumerateArray())
    {
        var nk = n.GetProperty("formkey").GetString()!;
        keys[nk] = Id($"NAVM:{cellName}:{nk}");
        sourceMap[nk] = keys[nk].ToString();
    }
    int written = 0, triangles = 0, doorsKept = 0, doorsLost = 0;
    foreach (var n in navs.EnumerateArray())
    {
        var src = n.GetProperty("formkey").GetString()!;
        var (geo, t, dk, dl) = NavGeometry(n.GetProperty("geometry"),
            new CellNavmeshParent { Parent = new FormLink<ICellGetter>(cell.FormKey) }, keys,
            door => placedBySource.TryGetValue(door, out var placedDoor) ? placedDoor : null);
        triangles += t; doorsKept += dk; doorsLost += dl;
        cell.NavigationMeshes.Add(new NavigationMesh(keys[src], release) { NavmeshGeometry = geo });
        navInfos.Add((keys[src], geo, null, 0, 0, cell.FormKey));
        written++;
    }
    return written == 0 ? "" : $"; navmeshes {written} ({triangles} triangles, door links {doorsKept} kept / {doorsLost} to doors not placed)";
}

// One navmesh's geometry from its JSON (positions in Skyrim units -> metres, links -> `keys`, doors -> doorOf or lost).
// Shared by the interiors (cell parent) and the exterior (world + grid parent, EXTERIOR_NAVMESH).
(NavmeshGeometry geo, int triangles, int doorsKept, int doorsLost) NavGeometry(JsonElement g, ANavmeshParent parent,
    Dictionary<string, FormKey> keys, Func<string, FormKey?> doorOf)
{
    int triangles = 0, doorsKept = 0, doorsLost = 0;
    var geo = new NavmeshGeometry
    {
        NavmeshVersion = 17,
        CrcHash = 0xA5E9A03C,                                                      // PathingCell
        Parent = parent,
    };
    foreach (var v in g.GetProperty("vertices").EnumerateArray())
        geo.Vertices.Add(new NavmeshVertex
        {
            Point = new P3Float(v[0].GetSingle() / UnitsPerMetre, v[1].GetSingle() / UnitsPerMetre, v[2].GetSingle() / UnitsPerMetre),
            Unknown = unchecked((int)v[3].GetUInt32()),
        });
    foreach (var t in g.GetProperty("triangles").EnumerateArray())
    {
        var tv = t.GetProperty("v"); var te = t.GetProperty("e");
        geo.Triangles.Add(new NavmeshTriangle
        {
            Vertices = new P3Int16(unchecked((short)tv[0].GetUInt16()), unchecked((short)tv[1].GetUInt16()), unchecked((short)tv[2].GetUInt16())),
            EdgeLink_0_1 = unchecked((short)te[0].GetUInt16()),
            EdgeLink_1_2 = unchecked((short)te[1].GetUInt16()),
            EdgeLink_2_0 = unchecked((short)te[2].GetUInt16()),
            Height = t.GetProperty("height").GetSingle(),
            Unknown = t.GetProperty("unknown").GetByte(),
            Flags = (NavmeshTriangle.Flag)t.GetProperty("flags").GetInt32(),
            CoverFlags = t.GetProperty("cover").GetUInt16(),
        });
        triangles++;
    }
    foreach (var l in g.GetProperty("edge_links").EnumerateArray())
        geo.EdgeLinks.Add(new EdgeLink
        {
            Unknown = l.GetProperty("type").GetInt32(),
            Mesh = new FormLink<INavigationMeshGetter>(keys[l.GetProperty("navmesh").GetString()!]),
            TriangleIndex = l.GetProperty("triangle").GetInt16(),
            Unknown2 = (sbyte)l.GetProperty("edge").GetInt32(),
        });
    foreach (var d in g.GetProperty("door_links").EnumerateArray())
    {
        var door = d.GetProperty("door").GetString() ?? "";
        if (doorOf(door) is not FormKey doorKey) { doorsLost++; continue; }
        geo.DoorTriangles.Add(new DoorTriangle
        {
            TriangleBeforeDoor = d.GetProperty("triangle").GetInt16(),
            Unknown = unchecked((int)0xE48B73F3),                                      // PathingDoor
            Door = new FormLink<IPlacedObjectGetter>(doorKey),
        });
        doorsKept++;
    }
    var grid = g.GetProperty("grid");
    geo.GridSize = grid.GetProperty("divisor").GetUInt32();
    var size = grid.GetProperty("size"); var b = grid.GetProperty("bounds");
    geo.GridMaxDistance = new P2Float(size[0].GetSingle() / UnitsPerMetre, size[1].GetSingle() / UnitsPerMetre);
    geo.GridMin = new P3Float(b[0].GetSingle() / UnitsPerMetre, b[1].GetSingle() / UnitsPerMetre, b[2].GetSingle() / UnitsPerMetre);
    // FLT_MAX (vanilla exterior grids' top, "nothing above") stays FLT_MAX instead of being scaled
    float M(float v) => v >= 3.0e38f ? float.MaxValue : v / UnitsPerMetre;
    geo.GridMax = new P3Float(M(b[3].GetSingle()), M(b[4].GetSingle()), M(b[5].GetSingle()));
    // Mutagen's Starfield GridArrays is not per cell: one flat Int16 run (each cell's u32 count as two Int16, then its
    // triangles) read to the end, then Int32 Unknown3. cell.json carries that run ("grid_raw", skyrimnavmesh.grid_shorts).
    var gridRun = new NavmeshGridArray();
    foreach (var x in g.GetProperty("grid_raw").EnumerateArray()) gridRun.GridCell.Add(x.GetInt16());
    geo.GridArrays.Add(gridRun);
    geo.Unknown3 = g.GetProperty("tail_int32").GetInt32();
    return (geo, triangles, doorsKept, doorsLost);
}

// ---- load doors -------------------------------------------------------------------------------------------------------
// cell.json refs with "teleport" {door, cell, pos, rot, flags} (make_skyrim_interior.py batch: Skyrim load doors whose
// destination door is in another cell of the batch). Their base must be a DOOR, so a converted static model used by a load
// door also gets a DOOR record (no animation graph: Skyrim load doors do not open, they load). LOADDOOR_TEMPLATE=<hex>:
// copy that vanilla Starfield DOOR instead (sounds, keywords) with the model swapped and its animation graph removed.
// The teleport itself is set after every cell is placed (the destination may come later), as XTEL: destination door,
// position / 70, rotation, flags. Mutagen's Starfield TeleportDestination as in its Skyrim one; unverified until built.
var loadDoorBases = new Dictionary<string, FormKey>(StringComparer.OrdinalIgnoreCase);
FormKey LoadDoorBase(string source, FormKey fallback)
{
    if (loadDoorBases.TryGetValue(source, out var have)) return have;
    if (!itemBySource.TryGetValue(source, out var it) || it.door != null) return loadDoorBases[source] = fallback;  // rigged: already a DOOR
    Door rec;
    if (Environment.GetEnvironmentVariable("LOADDOOR_TEMPLATE") is string tplHex)
    {
        if (!SfCache().TryResolve<IDoorGetter>(new FormKey(sfEsm, Convert.ToUInt32(tplHex, 16)), out var tpl))
            throw new InvalidOperationException($"LOADDOOR_TEMPLATE {tplHex} is not a DOOR in Starfield.esm");
        rec = (Door)tpl.Duplicate(Id("LOADDOOR:" + it.editorId));
        for (int i = rec.Components.Count - 1; i >= 0; i--)
            if (rec.Components[i] is AnimationGraphComponent) rec.Components.RemoveAt(i);
    }
    else rec = new Door(Id("LOADDOOR:" + it.editorId), release) { Name = "Door", SoundLevel = SoundLevel.Normal };
    rec.EditorID = "LD_" + it.editorId;
    rec.Model = new Model { File = it.model };
    mod.Doors.Add(rec);
    return loadDoorBases[source] = rec.FormKey;
}
var placedAll = new Dictionary<string, PlacedObject>();                     // every placed reference by source form key
var pendingTeleports = new List<(PlacedObject obj, JsonElement teleport)>();

// ---- cells ------------------------------------------------------------------------------------------------------------
static bool tele0(JsonElement r) => r.TryGetProperty("teleport", out var t) && t.ValueKind == JsonValueKind.Object;
P3Float Pos(JsonElement p) => new(p[0].GetSingle() / UnitsPerMetre, p[1].GetSingle() / UnitsPerMetre, p[2].GetSingle() / UnitsPerMetre);
P3Float Rot(JsonElement o) => new(o[0].GetSingle(), o[1].GetSingle(), o[2].GetSingle());

// ---- NPCs with their schedules (2026-11-08, owner: "try an NPC with their schedule"; docs/npc/schedules.md) -----------
// ACTORS = scripts/npc/make_schedule.py's actors.json: per NPC a vanilla Starfield NPC to copy (face_fit's template for
// it), the Skyrim cell and spot, and its packages translated to Starfield templates. Each package is a copy of a vanilla
// package that uses the same template (so every input the template has keeps a valid vanilla value), with the Skyrim
// schedule and speed and the translated inputs (by UNAM index). The NPC copy gets those packages only (AI-package template
// flag cleared, its scripts dropped) and is placed in the cell as a persistent ACHR.
var actorsPath = Environment.GetEnvironmentVariable("ACTORS");
JsonElement? actorsRoot = actorsPath == null ? null : JsonDocument.Parse(File.ReadAllText(actorsPath)).RootElement.Clone();
var sfActors = actorsPath == null ? null : StarfieldMod.CreateFromBinaryOverlay(
    Path.Combine(sfData0 ?? throw new InvalidOperationException("ACTORS needs STARFIELD_DATA"), "Starfield.esm"), release);
// package template -> a vanilla package using it to copy: one without an owner quest, scripts or conditions, and with no
// input that names a quest alias (2026-11-08: the first build copied the first user of each template; in game all three
// NPCs wandered the room instead of following their packages, as an NPC does when none of its packages can run)
var vanillaPackage = new Dictionary<FormKey, IPackageGetter>();
bool CleanPackage(IPackageGetter vp)
{
    if (!vp.OwnerQuest.IsNull || vp.VirtualMachineAdapter != null || vp.Conditions.Count > 0) return false;
    foreach (var d in vp.Data.Values)
    {
        if (d is IPackageDataTargetGetter t && t.Target is IPackageTargetAliasGetter) return false;
        if (d is IPackageDataLocationGetter l && l.Location.Target is ILocationFallbackGetter fb
            && fb.Type is LocationTargetRadius.LocationType.AliasForReference or LocationTargetRadius.LocationType.AliasForLocation
                or LocationTargetRadius.LocationType.AliasForCollection) return false;
    }
    return true;
}
if (sfActors != null)
{
    var fallback = new Dictionary<FormKey, IPackageGetter>();
    foreach (var vp in sfActors.Packages)
    {
        if (vp.Type != Package.Types.Package || vp.PackageTemplate.IsNull) continue;
        var tk = vp.PackageTemplate.FormKey;
        fallback.TryAdd(tk, vp);
        if (!vanillaPackage.ContainsKey(tk) && CleanPackage(vp)) vanillaPackage[tk] = vp;
    }
    foreach (var (tk, vp) in fallback)
        if (vanillaPackage.TryAdd(tk, vp)) Console.WriteLine($"package template {tk}: no clean vanilla package; copying {vp.EditorID}");
}
// XMarker: make_schedule.py looks it up in Starfield.esm ("xmarker" in actors.json); 0x3B as Skyrim's / FO4's otherwise
var xMarker = new FormKey(sfEsm, actorsRoot is JsonElement axr && axr.TryGetProperty("xmarker", out var xmj) && xmj.ValueKind == JsonValueKind.String
    ? Convert.ToUInt32(xmj.GetString(), 16) & 0xFFFFFF : 0x00003B);

void PlaceActor(Cell cell, string cellName, JsonElement ac, Dictionary<string, FormKey> placedBySource)
{
    var sk = ac.GetProperty("skyrim").GetString()!;
    var tplKey = new FormKey(sfEsm, Convert.ToUInt32(ac.GetProperty("template_npc").GetString(), 16) & 0xFFFFFF);
    var vnpc = sfActors!.Npcs.FirstOrDefault(n => n.FormKey == tplKey);
    if (vnpc == null) { Console.WriteLine($"actor {sk}: template NPC {tplKey} not in Starfield.esm; not placed"); return; }
    var npc = (Npc)vnpc.Duplicate(Id("NPC_:" + sk));
    npc.EditorID = "S2S_" + sk;
    npc.Name = ac.GetProperty("name").GetString();
    npc.VirtualMachineAdapter = null;
    npc.UseTemplateActors &= ~Npc.TemplateActorType.AiPackages;
    npc.Packages.Clear();
    var notes = new List<string>();
    foreach (var pj in ac.GetProperty("packages").EnumerateArray())
    {
        var edid = pj.GetProperty("edid").GetString()!;
        var tkey = new FormKey(sfEsm, Convert.ToUInt32(pj.GetProperty("sf_template_form").GetString(), 16) & 0xFFFFFF);
        if (!vanillaPackage.TryGetValue(tkey, out var vp)) { notes.Add($"{edid}: no vanilla package uses template {tkey}"); continue; }
        var pk = (Package)vp.Duplicate(Id("PACK:" + edid));
        pk.EditorID = edid;
        pk.VirtualMachineAdapter = null;
        pk.OwnerQuest.SetToNull();
        pk.Conditions.Clear();
        var sch = pj.GetProperty("schedule");
        pk.ScheduleMonth = (sbyte)sch.GetProperty("month").GetInt32();
        pk.ScheduleDayOfWeek = (Package.DayOfWeek)sch.GetProperty("day_of_week").GetInt32();
        pk.ScheduleDate = (byte)sch.GetProperty("date").GetInt32();
        pk.ScheduleHour = (sbyte)sch.GetProperty("hour").GetInt32();
        pk.ScheduleMinute = (sbyte)sch.GetProperty("minute").GetInt32();
        pk.ScheduleDurationInMinutes = sch.GetProperty("duration_min").GetInt32();
        pk.PreferredSpeed = (Package.Speed)pj.GetProperty("speed").GetInt32();
        foreach (var ip in pj.GetProperty("inputs").EnumerateObject())
        {
            var idx = sbyte.Parse(ip.Name);
            var v = ip.Value;
            if (!pk.Data.TryGetValue(idx, out var d)) { notes.Add($"{edid}: input {idx} not in the vanilla package"); continue; }
            switch (v.GetProperty("kind").GetString())
            {
                case "bool" when d is PackageDataBool b: b.Data = v.GetProperty("value").GetBoolean(); break;
                case "float" when d is PackageDataFloat f: f.Data = v.GetProperty("value").GetSingle(); break;
                case "int" when d is PackageDataInt i: i.Data = (uint)v.GetProperty("value").GetInt32(); break;
                case "location" when d is PackageDataLocation l:
                {
                    var old = l.Location.Radius;
                    ALocationTarget target;
                    switch (v.GetProperty("type").GetString())
                    {
                        case "near_reference":
                            var srcRef = v.GetProperty("source").GetString()!;
                            if (!placedBySource.TryGetValue(srcRef, out var refKey))
                            {
                                // not placed by us (an editor marker): a Starfield XMarker at its spot, persistent as package targets are
                                var m = new PlacedObject(Id($"REFR:{cellName}:{srcRef}:marker"), release)
                                    { Base = new FormLinkNullable<IPlaceableObjectGetter>(xMarker), Position = Pos(v.GetProperty("pos")), Rotation = Rot(v.GetProperty("rot")) };
                                m.MajorRecordFlagsRaw |= 0x400;
                                cell.Persistent.Add(m);
                                placedBySource[srcRef] = refKey = m.FormKey;
                                sourceMap[srcRef] = m.FormKey.ToString();
                            }
                            target = new LocationTarget { Link = new FormLink<IPlacedGetter>(refKey) };
                            break;
                        case "in_cell": target = new LocationCell { Link = new FormLink<ICellGetter>(cell.FormKey) }; break;
                        case "near_package_start": target = new LocationFallback { Type = LocationTargetRadius.LocationType.NearPackageStart }; break;
                        case "near_editor_location": target = new LocationFallback { Type = LocationTargetRadius.LocationType.NearEditorLocation }; break;
                        case "near_self": target = new LocationFallback { Type = LocationTargetRadius.LocationType.NearSelf }; break;
                        default: notes.Add($"{edid}: location {v.GetProperty("type").GetString()} not handled"); continue;
                    }
                    // Starfield's PLDT radius is a float (xEdit SF1); Mutagen keeps the raw u32
                    var r = v.GetProperty("radius_m").GetSingle();
                    notes.Add($"{edid}: location radius {r} m (the vanilla value's raw bits {old:X8} = {BitConverter.UInt32BitsToSingle(old)} as a float)");
                    l.Location = new LocationTargetRadius { Target = target, Radius = BitConverter.SingleToUInt32Bits(r), CollectionIndex = l.Location.CollectionIndex };
                    break;
                }
                default: notes.Add($"{edid}: input {idx} is {d.GetType().Name}, not {v.GetProperty("kind").GetString()}; vanilla kept"); break;
            }
        }
        mod.Packages.Add(pk);
        npc.Packages.Add(new FormLink<IPackageGetter>(pk.FormKey));
        notes.Add($"{edid} {pk.FormKey} (copy of vanilla {vp.EditorID} {vp.FormKey})");
        sourceMap["PACK:" + edid] = pk.FormKey.ToString();
    }
    mod.Npcs.Add(npc);
    var achr = new PlacedNpc(Id($"ACHR:{cellName}:{sk}"), release)
        { Base = new FormLinkNullable<INpcGetter>(npc.FormKey), Position = Pos(ac.GetProperty("pos")), Rotation = Rot(ac.GetProperty("rot")) };
    achr.MajorRecordFlagsRaw |= 0x400;
    cell.Persistent.Add(achr);
    sourceMap[ac.GetProperty("source").GetString()!] = achr.FormKey.ToString();
    sourceMap["NPC_:" + sk] = npc.FormKey.ToString();
    Console.WriteLine($"actor {sk}: NPC {npc.FormKey} (copy of {vnpc.EditorID} {tplKey}), {npc.Packages.Count} packages, placed {achr.FormKey} in {cellName}");
    foreach (var n in notes) Console.WriteLine("  " + n);
}

var cellPaths = args.Skip(2).SelectMany(a => a.StartsWith('@')
    ? File.ReadAllLines(a[1..]).Select(l => l.Trim()).Where(l => l.Length > 0)
    : new[] { a }).ToList();
foreach (var cellPath in cellPaths)
{
    using var cdoc = JsonDocument.Parse(File.ReadAllText(cellPath));
    var root = cdoc.RootElement;
    var src4 = root.GetProperty("cell").GetString()!;
    var cellName = "FO4Port_" + src4;
    var cell = new Cell(Id("CELL:" + cellName), release) { EditorID = cellName, Flags = Cell.Flag.IsInteriorCell };
    var ltHex = Setting(src4, "LIGHTING_TEMPLATE", "06BCF8");   // KreetBase01LGTtemplate (underground); ShipInteriorLT 006658 is brighter
    cell.LightingTemplate.SetTo(new FormKey(sfEsm, Convert.ToUInt32(ltHex, 16)));
    // exposure + reflections like the vanilla underground interior DR017UndergroundInterior (25CAA7): without these the cell
    // reflects a bright default sky and auto-exposure washes everything out
    cell.ImageSpace.SetTo(new FormKey(sfEsm, Convert.ToUInt32(Setting(src4, "IMAGE_SPACE", "122393"), 16)));
    cell.EnvironmentMap = Environment.GetEnvironmentVariable("ENV_MAP") ?? "Data\\Textures\\cubemaps\\blackcube.dds";
    var cocMarker = new FormKey(sfEsm, 0x000032);                                        // COCMarkerHeading
    var omni = new FormKey(sfEsm, Convert.ToUInt32(Setting(src4, "OMNI_LIGHT", "03D38C"), 16)); // LGT_ShipInterior_Omni_NS_Neutral_2k
    var merge = float.Parse(Setting(src4, "LIGHT_MERGE_M", "3"), System.Globalization.CultureInfo.InvariantCulture);
    if (root.TryGetProperty("skyrim_lighting", out var skyLighting) && skyLighting.ValueKind == JsonValueKind.Object
        && Setting(src4, "CELL_AMBIENT", "template") == "skyrim")
        SkyrimAmbient(cell, src4, skyLighting, new FormKey(sfEsm, Convert.ToUInt32(ltHex, 16)));
    var lit = new List<P3Float>();
    var placedBySource = new Dictionary<string, FormKey>();               // Skyrim / FO4 ref -> its new reference
    int lights = 0, placed = 0, skipped = 0, disabled = 0, innerDoors = 0;
    foreach (var r in root.GetProperty("refs").EnumerateArray())
    {
        var src = r.GetProperty("formkey").GetString()!;
        var model = r.GetProperty("model").GetString() ?? "";
        PlacedObject? obj = null;
        if (r.GetProperty("base_editor_id").GetString() == "COCMarkerHeading")            // arrival point for `coc`
        {
            obj = new PlacedObject(Id($"REFR:{cellName}:{src}"), release)
                { Base = new FormLinkNullable<IPlaceableObjectGetter>(cocMarker), Position = Pos(r.GetProperty("pos")), Rotation = Rot(r.GetProperty("rot")) };
        }
        else if (r.GetProperty("type").GetString() == "Light")
        {
            if (Environment.GetEnvironmentVariable("FO4PORT_NO_LIGHTS") == "1") continue;
            var pos = Pos(r.GetProperty("pos"));
            if (lit.Any(q => Math.Abs(q.X - pos.X) < merge && Math.Abs(q.Y - pos.Y) < merge && Math.Abs(q.Z - pos.Z) < merge)) continue;
            lit.Add(pos);
            var lightBase = r.TryGetProperty("light", out var lj) && lj.ValueKind == JsonValueKind.Object
                            && Setting(src4, "SKYRIM_LIGHTS", "1") != "0" ? SkyrimLight(src4, lj, omni) : omni;
            obj = new PlacedObject(Id($"REFR:{cellName}:{src}"), release) { Base = new FormLinkNullable<IPlaceableObjectGetter>(lightBase), Position = pos };
            lights++;
        }
        else
        {
            var srcModel = "meshes\\" + model.TrimStart('\\');
            if (model.Length == 0 || !bySource.TryGetValue(srcModel, out var bas)) { skipped++; continue; }
            var tele = r.TryGetProperty("teleport", out var tj) && tj.ValueKind == JsonValueKind.Object;
            // a Skyrim door that is not a load door (room doors) would be a solid static here: it cannot open, and NPCs
            // walk into it, the navmesh passing through (owner 2026-11-08, Sleeping Giant Inn). Left out: an open
            // doorway, until doors that open are converted. INNER_DOORS=static keeps them.
            if (!tele && r.GetProperty("type").GetString() == "Door" && Setting(src4, "INNER_DOORS", "open") != "static")
            { innerDoors++; continue; }
            if (tele) bas = (LoadDoorBase(srcModel, bas.key), bas.offset);
            var scale = r.GetProperty("scale").GetSingle();
            var rot = Rot(r.GetProperty("rot"));
            var pos = Pos(r.GetProperty("pos"));
            var off = RotateOffset(bas.offset, rot, scale);
            obj = new PlacedObject(Id($"REFR:{cellName}:{src}"), release)
            {
                Base = new FormLinkNullable<IPlaceableObjectGetter>(bas.key),
                Position = new P3Float(pos.X + off.X, pos.Y + off.Y, pos.Z + off.Z),
                Rotation = rot,
            };
            if (Math.Abs(scale - 1f) > 1e-4) obj.Scale = scale;
            if (tele) pendingTeleports.Add((obj, tj.Clone()));
            placed++;
        }
        if (r.TryGetProperty("disabled", out var dis) && dis.GetInt32() != 0)
        {
            obj.MajorRecordFlagsRaw |= 0x800;                                              // Initially Disabled, as in FO4
            disabled++;
        }
        // load doors are persistent, as in Skyrim: in the cell's persistent group AND with the record's Persistent flag
        // (0x400). Mutagen sets the group only; the flag-less doors of the owner's Oct 2026 run teleported once, then lost
        // their prompt until a reload and sent the return trip to the wrong end (scripts/interior/door_survey.py).
        if (tele0(r)) { obj.MajorRecordFlagsRaw |= 0x400; cell.Persistent.Add(obj); } else cell.Temporary.Add(obj);
        placedBySource[src] = obj.FormKey;
        placedAll[src] = obj;
        sourceMap[src] = obj.FormKey.ToString();
    }
    if (root.TryGetProperty("cell_formkey", out var cfk) && cfk.ValueKind == JsonValueKind.String)
        sourceMap[cfk.GetString()!] = cell.FormKey.ToString();
    var navNote = WriteNavmeshes(cell, cellName, root, placedBySource);
    if (actorsRoot is JsonElement ar)
        foreach (var ac in ar.GetProperty("actors").EnumerateArray())
            if (ac.GetProperty("cell").GetString() == src4) PlaceActor(cell, cellName, ac, placedBySource);
    var cid = cell.FormKey.ID;
    var block = new CellBlock { BlockNumber = (int)(cid % 10), GroupType = GroupTypeEnum.InteriorCellBlock };
    var sub = new CellSubBlock { BlockNumber = (int)((cid / 10) % 10), GroupType = GroupTypeEnum.InteriorCellSubBlock };
    sub.Cells.Add(cell);
    block.SubBlocks.Add(sub);
    mod.Cells.Records.Add(block);
    Console.WriteLine($"cell {cellName} {cell.FormKey}: placed {placed} references + {lights} lights ({disabled} initially disabled), skipped {skipped}"
        + (innerDoors > 0 ? $", {innerDoors} room doors left out (open doorways)" : "") + navNote);
}

// ---- exterior load doors (2026-11-08, owner: "get the Riverwood inn connected to Riverwood") -------------------------
// EXTERIOR_DIR: the staged exterior that is installed (owner: C:\Modding\staging\skyrim_all): formids.json (Skyrim ref ->
// our FormID in the exterior plugin, the world), overlays_params.json (the overlay frame, the planet plugin) and the
// plugins themselves. EXTERIOR_DOORS: make_skyrim_interior.py batch --exterior's exterior_doors.json.
// No exterior rebuild: FO4Port.esm (mastering the exterior and planet plugins) overrides the world, its persistent cell
// and the cells of the doors: the exterior's static door reference is disabled (an override with Initially Disabled)
// and a persistent load door of ours (a DOOR with the static's model, at its place) is added to the persistent cell
// with XTEL to our interior door; our interior door gets XTEL back to it, its landing point converted to the overlay
// frame as make_skyrim_objects.py to_local does (Skyrim units / 70 - origin_cw_m, z + height_offset_m). If the exterior
// was staged with --interiors (already a persistent load door there), that reference is overridden with the XTEL instead.
// Written without a compiler (no NuGet in the cloud workspace); Mutagen names as used elsewhere in this file and in
// dotnet/TerrainOverlays.
var extDir = Environment.GetEnvironmentVariable("EXTERIOR_DIR");
var extDoorsPath = Environment.GetEnvironmentVariable("EXTERIOR_DOORS");
var extNavPath = Environment.GetEnvironmentVariable("EXTERIOR_NAVMESH");   // make_skyrim_navmesh.py export's exterior_navmesh.json
JsonElement extIds = default;
ModKey? extKey = null, planetKey = null;
float extOx = 0, extOy = 0, extOz = 0;
var extDoorFor = new Dictionary<string, FormKey>();          // Skyrim exterior door ref -> the load door the interior uses
var extLoadDoors = new List<PlacedObject>();                  // those load doors (for XNDP)
if (extDir != null)
{
    extIds = JsonDocument.Parse(File.ReadAllText(Path.Combine(extDir, "formids.json"))).RootElement.Clone();
    extKey = ModKey.FromNameAndExtension(extIds.GetProperty("plugin").GetString()!);
    var prmRoot = JsonDocument.Parse(File.ReadAllText(Path.Combine(extDir, "overlays_params.json"))).RootElement.Clone();
    var ovp = prmRoot.GetProperty("overlays")[0];
    extOx = ovp.GetProperty("origin_cw_m")[0].GetSingle();
    extOy = ovp.GetProperty("origin_cw_m")[1].GetSingle();
    extOz = ovp.TryGetProperty("height_offset_m", out var hoj) && hoj.ValueKind == JsonValueKind.Number ? hoj.GetSingle() : 0f;
    if (prmRoot.TryGetProperty("mars", out var mj) && mj.ValueKind == JsonValueKind.Object
        && File.Exists(Path.Combine(extDir, mj.GetProperty("plugin").GetString()!)))
        planetKey = ModKey.FromNameAndExtension(mj.GetProperty("plugin").GetString()!);
}
P3Float ExtPos(JsonElement p) => new(p[0].GetSingle() / UnitsPerMetre - extOx, p[1].GetSingle() / UnitsPerMetre - extOy,
                                     p[2].GetSingle() / UnitsPerMetre + extOz);
int extIn = 0, extInLost = 0;
if (extDir != null && (extDoorsPath != null || extNavPath != null))
{
    // their masters' styles (Mutagen needs them to read a plugin with masters; as dotnet/ReferenceLinks/PluginReader.cs):
    // Starfield.esm, and for the planet plugin the exterior plugin; both full masters (TerrainOverlays sets the flag)
    var extMasters = new Cache<IModMasterStyledGetter, ModKey>(x => x.ModKey);
    extMasters.Set(new KeyedMasterStyle(sfEsm, MasterStyle.Full));
    extMasters.Set(new KeyedMasterStyle(extKey!.Value, MasterStyle.Full));
    var readParams = new BinaryReadParameters { MasterFlagsLookup = extMasters };
    using var ext = StarfieldMod.CreateFromBinaryOverlay(Path.Combine(extDir, extKey.Value.FileName), release, readParams);
    using var planet = planetKey == null ? null
        : StarfieldMod.CreateFromBinaryOverlay(Path.Combine(extDir, planetKey.Value.FileName), release, readParams);
    var worldEdid = extIds.GetProperty("world").GetString();
    var wg = ext.Worldspaces.First(w => w.EditorID == worldEdid);
    // the world record and its persistent cell from the last plugin that has them (the planet plugin overrides the
    // persistent cell: landing pad, map marker), copied without cells / references: an override replaces the record,
    // other plugins' references stay. OFST / CLSZ index the exterior file's own layout: left out of the override.
    var wLast = (IWorldspaceGetter?)planet?.Worldspaces.FirstOrDefault(w => w.FormKey == wg.FormKey) ?? wg;
    var wo = wLast.DeepCopy(new Worldspace.TranslationMask(defaultOn: true) { SubCells = false, TopCell = false });
    wo.OffsetData = null;
    wo.CellSizeData = null;
    var topLast = wLast.TopCell ?? wg.TopCell!;
    var tco = topLast.DeepCopy(new Cell.TranslationMask(defaultOn: true) { Persistent = false, Temporary = false });
    wo.TopCell = tco;
    var cellMask = new Cell.TranslationMask(defaultOn: true) { Persistent = false, Temporary = false, NavigationMeshes = false };
    var want = new Dictionary<FormKey, (string src, JsonElement tele)>();
    if (extDoorsPath != null)
    foreach (var d in JsonDocument.Parse(File.ReadAllText(extDoorsPath)).RootElement.Clone().GetProperty("doors").EnumerateArray())
    {
        var src = d.GetProperty("src").GetString()!;
        if (extIds.GetProperty("refs").TryGetProperty(src, out var v))
            want[new FormKey(extKey.Value, Convert.ToUInt32(v.GetString(), 16))] = (src, d.GetProperty("teleport"));
        else extInLost++;                                        // not placed out there (outside the region / not converted)
    }
    var cellOverrides = new Dictionary<FormKey, Cell>();
    var blocksO = new Dictionary<(int, int), WorldspaceBlock>();
    var subsO = new Dictionary<(int, int), WorldspaceSubBlock>();
    var newDoorBases = new Dictionary<string, FormKey>(StringComparer.OrdinalIgnoreCase);
    // an override of an exterior cell (without its references / navmeshes: ours are added to it), in override copies of
    // its block and sub-block; one per cell, shared by the doors and the navmeshes
    Cell CellOverride(IWorldspaceBlockGetter blk, IWorldspaceSubBlockGetter sb, ICellGetter c)
    {
        if (cellOverrides.TryGetValue(c.FormKey, out var co)) return co;
        if (!blocksO.TryGetValue((blk.BlockNumberX, blk.BlockNumberY), out var bo))
        {
            bo = new WorldspaceBlock { BlockNumberX = blk.BlockNumberX, BlockNumberY = blk.BlockNumberY, GroupType = GroupTypeEnum.ExteriorCellBlock };
            blocksO[(blk.BlockNumberX, blk.BlockNumberY)] = bo;
            wo.SubCells.Add(bo);
        }
        if (!subsO.TryGetValue((sb.BlockNumberX, sb.BlockNumberY), out var so_))
        {
            so_ = new WorldspaceSubBlock { BlockNumberX = sb.BlockNumberX, BlockNumberY = sb.BlockNumberY, GroupType = GroupTypeEnum.ExteriorCellSubBlock };
            subsO[(sb.BlockNumberX, sb.BlockNumberY)] = so_;
            bo.Items.Add(so_);
        }
        co = c.DeepCopy(cellMask);
        so_.Items.Add(co);
        cellOverrides[c.FormKey] = co;
        return co;
    }
    void Link(PlacedObject o, JsonElement t)
    {
        o.TeleportDestination = new TeleportDestination
        {
            Door = new FormLink<IPlacedObjectGetter>(placedAll[t.GetProperty("door").GetString()!].FormKey),
            Position = Pos(t.GetProperty("pos")),            // the landing point inside: interior units / 70
            Rotation = Rot(t.GetProperty("rot")),
            Flags = (TeleportDestination.Flag)t.GetProperty("flags").GetInt32(),
        };
    }
    // already a persistent load door out there (exterior staged with --interiors): override it with the teleport
    foreach (var r in wg.TopCell!.Persistent)
        if (want.TryGetValue(r.FormKey, out var w1) && r is IPlacedObjectGetter pg && placedAll.ContainsKey(w1.tele.GetProperty("door").GetString()!))
        {
            var o = (PlacedObject)pg.DeepCopy();
            o.MajorRecordFlagsRaw |= 0x400;
            Link(o, w1.tele);
            tco.Persistent.Add(o);
            extDoorFor[w1.src] = o.FormKey;
            extLoadDoors.Add(o);
            want.Remove(r.FormKey);
            extIn++;
        }
    // a static door in an exterior cell: disabled, and our persistent load door put in its place
    foreach (var blk in wg.SubCells)
        foreach (var sb in blk.Items)
            foreach (var c in sb.Items)
                foreach (var r in c.Temporary)
                {
                    if (!want.TryGetValue(r.FormKey, out var w2) || r is not IPlacedObjectGetter sg) continue;
                    if (!placedAll.ContainsKey(w2.tele.GetProperty("door").GetString()!)) { extInLost++; continue; }
                    FormKey dkey;
                    if (ext.Doors.Any(x => x.FormKey == sg.Base.FormKey)) dkey = sg.Base.FormKey;   // already a DOOR there
                    else
                    {
                        var stat = ext.Statics.FirstOrDefault(x => x.FormKey == sg.Base.FormKey);
                        var model = stat?.Model?.File?.ToString();
                        if (stat == null || model == null) { extInLost++; continue; }   // not one of our bases
                        if (!newDoorBases.TryGetValue(model, out dkey))
                        {
                            var drec = new Door(Id("EXTDOOR:" + model), release)
                            {
                                EditorID = "LD_Ext_" + (stat.EditorID ?? "Door"),
                                Model = new Model { File = model }, Name = "Door", SoundLevel = SoundLevel.Normal,
                            };
                            if (stat.ObjectBounds != null) drec.ObjectBounds = stat.ObjectBounds.DeepCopy();
                            mod.Doors.Add(drec);
                            newDoorBases[model] = dkey = drec.FormKey;
                        }
                    }
                    var nd = new PlacedObject(Id("EXTREF:" + w2.src), release)
                    {
                        Base = new FormLinkNullable<IPlaceableObjectGetter>(dkey),
                        Position = sg.Position, Rotation = sg.Rotation,
                    };
                    if (sg.Scale is float sc && Math.Abs(sc - 1f) > 1e-4) nd.Scale = sc;
                    nd.MajorRecordFlagsRaw |= 0x400;                        // persistent, as every vanilla load door
                    Link(nd, w2.tele);
                    tco.Persistent.Add(nd);
                    extDoorFor[w2.src] = nd.FormKey;
                    extLoadDoors.Add(nd);
                    // the exterior's static copy of it: Initially Disabled, in an override of its cell
                    var co = CellOverride(blk, sb, c);
                    var off = (PlacedObject)sg.DeepCopy();
                    off.MajorRecordFlagsRaw |= 0x800;                         // Initially Disabled
                    co.Temporary.Add(off);
                    want.Remove(r.FormKey);
                    extIn++;
                }
    extInLost += want.Count;                                         // listed, placed, but not found in the world
    if (extDoorsPath != null)
        Console.WriteLine($"exterior doors into the interiors: {extIn} made load doors (override of {wg.EditorID}), {extInLost} not");

    // ---- exterior navmeshes (2026-11-08, owner: "convert the exterior mesh"; docs/terrain/exterior-navmesh.md) -------
    // make_skyrim_navmesh.py export: Skyrim's navmeshes around a place, in the overlay frame (Skyrim units), split at the
    // 100 m Starfield cells, each piece with its Starfield cell. Each goes into an override of that exterior cell, parent
    // = the world + the cell's grid. NVNM stores the grid as Y then X (xEdit wbDefinitionsSF1 / TES5: 'Grid Y', 'Grid X')
    // and Mutagen's P2Int16 Coordinates reads the first short as X, so Coordinates = (Y, X) to write the bytes as the
    // game does (supported; make_skyrim_navmesh.py compare checks the written bytes against the cell's XCLC, and
    // navmesh_survey.py --exterior checks the order on vanilla navmeshes). Door links -> the load doors made above.
    if (extNavPath != null)
    {
        var cellAt = new Dictionary<(int, int), (IWorldspaceBlockGetter blk, IWorldspaceSubBlockGetter sb, ICellGetter c)>();
        foreach (var blk in wg.SubCells)
            foreach (var sb in blk.Items)
                foreach (var c in sb.Items)
                    if (c.Grid != null) cellAt[(c.Grid.Point.X, c.Grid.Point.Y)] = (blk, sb, c);
        var navRoot = JsonDocument.Parse(File.ReadAllText(extNavPath)).RootElement.Clone();
        var navKeys = new Dictionary<string, FormKey>();
        foreach (var n in navRoot.GetProperty("navmeshes").EnumerateArray())
        {
            var k = n.GetProperty("key").GetString()!;
            navKeys[k] = Id("EXTNAVM:" + k);
            sourceMap[k] = navKeys[k].ToString();
        }
        int navWritten = 0, navTris = 0, navNoCell = 0, navDoorsKept = 0, navDoorsLost = 0;
        var navCells = new HashSet<(int, int)>();
        foreach (var n in navRoot.GetProperty("navmeshes").EnumerateArray())
        {
            var k = n.GetProperty("key").GetString()!;
            var cxy = n.GetProperty("cell");
            int cx = cxy[0].GetInt32(), cy = cxy[1].GetInt32();
            if (!cellAt.TryGetValue((cx, cy), out var at)) { navNoCell++; continue; }   // outside the exterior's cells
            var parent = new WorldspaceNavmeshParent
            {
                Parent = new FormLink<IWorldspaceGetter>(wg.FormKey),
                Coordinates = new P2Int16((short)cy, (short)cx),
            };
            var (geo, t, dk, dl) = NavGeometry(n.GetProperty("geometry"), parent, navKeys,
                door => extDoorFor.TryGetValue(door, out var ourDoor) ? ourDoor : null);
            CellOverride(at.blk, at.sb, at.c).NavigationMeshes.Add(new NavigationMesh(navKeys[k], release) { NavmeshGeometry = geo });
            navInfos.Add((navKeys[k], geo, wg.FormKey, (short)cx, (short)cy, null));
            navWritten++; navTris += t; navDoorsKept += dk; navDoorsLost += dl;
            navCells.Add((cx, cy));
        }
        Console.WriteLine($"exterior navmeshes: {navWritten} in {navCells.Count} cells ({navTris} triangles; door links {navDoorsKept} " +
                          $"to our load doors, {navDoorsLost} to other doors dropped), {navNoCell} outside the exterior's cells");
    }
    mod.Worldspaces.Add(wo);
}

int teleLinked = 0, teleLost = 0, teleOut = 0, teleOutLost = 0;
foreach (var (obj, t) in pendingTeleports)
{
    if (t.TryGetProperty("cell", out var tc) && tc.GetString() == "exterior")
    {
        if (!extDoorFor.TryGetValue(t.GetProperty("door").GetString()!, out var outDoor)) { teleOutLost++; continue; }
        obj.TeleportDestination = new TeleportDestination
        {
            Door = new FormLink<IPlacedObjectGetter>(outDoor),
            Position = ExtPos(t.GetProperty("pos")),
            Rotation = Rot(t.GetProperty("rot")),
            Flags = (TeleportDestination.Flag)t.GetProperty("flags").GetInt32(),
        };
        teleOut++;
        continue;
    }
    if (!placedAll.TryGetValue(t.GetProperty("door").GetString()!, out var dest)) { teleLost++; continue; }   // its model failed
    obj.TeleportDestination = new TeleportDestination
    {
        Door = new FormLink<IPlacedObjectGetter>(dest.FormKey),
        Position = Pos(t.GetProperty("pos")),
        Rotation = Rot(t.GetProperty("rot")),
        Flags = (TeleportDestination.Flag)t.GetProperty("flags").GetInt32(),
    };
    teleLinked++;
}
if (teleOut + teleOutLost > 0)
    Console.WriteLine($"doors out to the exterior: {teleOut} linked, {teleOutLost} not (" +
                      (extDir == null ? "no EXTERIOR_DIR / EXTERIOR_DOORS" : "its exterior door was not made a load door") + ")");
if (pendingTeleports.Count > 0)
    Console.WriteLine($"load doors: {teleLinked} linked, {teleLost} lost (destination door not placed); {loadDoorBases.Count} door models");

// ---- door test cell (FO4PORT_DOORTEST=<door editor id>) ------------------------------------------------------------------
// One 8x8 m vanilla platform, the converted door at the origin (facing +X like an FO4 door with no rotation), the vanilla
// Akila door 0AA24A 3 m to the side for comparison, and a COC marker 1.5 m in front of the converted door, facing it.
if (Environment.GetEnvironmentVariable("FO4PORT_DOORTEST") is string testDoor)
{
    var cell = new Cell(Id("CELL:FO4Port_DoorTest"), release) { EditorID = "FO4Port_DoorTest", Flags = Cell.Flag.IsInteriorCell };
    cell.LightingTemplate.SetTo(new FormKey(sfEsm, 0x006658));
    cell.ImageSpace.SetTo(new FormKey(sfEsm, 0x122393));
    cell.EnvironmentMap = "Data\\Textures\\cubemaps\\blackcube.dds";
    var entry = items.First(i => i.editorId == testDoor);
    var (doorKey, doorOff) = bySource[entry.source.Replace('/', '\\')];
    PlacedObject P(string key, FormKey b, P3Float pos, P3Float rot) =>
        new(Id("REFR:FO4Port_DoorTest:" + key), release) { Base = new FormLinkNullable<IPlaceableObjectGetter>(b), Position = pos, Rotation = rot };
    var zero = new P3Float(0, 0, 0);
    cell.Temporary.Add(P("floor", new FormKey(sfEsm, 0x050776), new P3Float(-2, 0, 0), zero));  // NA_Transit_PlatformA_Str08x08_01: x -2..6, top z 0
    cell.Temporary.Add(P("door", doorKey, doorOff, zero));
    cell.Temporary.Add(P("vanilla", new FormKey(sfEsm, 0x0AA24A), new P3Float(0, 3, 0), zero));
    cell.Temporary.Add(P("coc", new FormKey(sfEsm, 0x000032), new P3Float(-1.5f, 0, 0.1f), new P3Float(0, 0, (float)(Math.PI / 2))));
    cell.Temporary.Add(P("light", new FormKey(sfEsm, 0x03D38C), new P3Float(-1, 1.5f, 3), zero));
    var cid = cell.FormKey.ID;
    var block = new CellBlock { BlockNumber = (int)(cid % 10), GroupType = GroupTypeEnum.InteriorCellBlock };
    var sub = new CellSubBlock { BlockNumber = (int)((cid / 10) % 10), GroupType = GroupTypeEnum.InteriorCellSubBlock };
    sub.Cells.Add(cell);
    block.SubBlocks.Add(sub);
    mod.Cells.Records.Add(block);
    Console.WriteLine($"door test cell {cell.FormKey} with {testDoor}");
}

if (lightBases.Count > 0) Console.WriteLine($"{lightBases.Count} Starfield lights made from Skyrim lights");
foreach (var note in lightNotes) Console.WriteLine($"  light note: {note}");

// ---- pathing registration (2026-11-08; method from tes4skyrim's Skyrim findings, docs/terrain/exterior-navmesh.md) --------
// Skyrim's pathfinder only uses a navmesh that is also listed in the Navmesh Info Map (NAVI, one record in the master,
// which every plugin overrides with entries for its own navmeshes; the game merges the overrides), and a load door is
// a pathing node only with XNDP (door -> the navmesh triangle in front of it). Starfield has both (xEdit SF1; door_survey:
// 576 of 619 vanilla load doors carry XNDP). Assumed to work the same in Starfield (supported); NAVI=off skips it.
// XNDP: each load door of ours that a navmesh's door triangle names.
var doorTri = new Dictionary<FormKey, (FormKey nav, short tri)>();
foreach (var ni in navInfos)
    foreach (var dt in ni.geo.DoorTriangles)
        doorTri.TryAdd(dt.Door.FormKey, (ni.nav, dt.TriangleBeforeDoor));
int xndp = 0;
foreach (var o in placedAll.Values.Concat(extLoadDoors))
    if (o.TeleportDestination != null && doorTri.TryGetValue(o.FormKey, out var nt))
    {
        o.NavigationDoorLink = new NavigationDoorLink { NavMesh = new FormLink<INavigationMeshGetter>(nt.nav), TeleportMarkerTriangle = nt.tri };
        xndp++;
    }
if (navInfos.Count > 0) Console.WriteLine($"XNDP (door -> navmesh) on {xndp} load doors");
// NAVI: an override of Starfield.esm's NAVI (its version and precomputed pathing NVPP kept) holding one NVMI per navmesh
// of ours: flags 0, approx location = the vertices' mean, edge links = the other navmeshes its edge links name, door
// links = its door triangles' doors, no traversals / island, the pathing cell, then the unknown tail Starfield's own
// entries end with most often (navmesh_survey.py). Mutagen keeps the part after the door links as raw bytes, so the
// pathing cell's FormIDs are written by hand with the master index of the written file (second pass below).
NavigationMeshInfoMap? naviO = null;
var naviBody = new List<(NavigationMapInfo info, (FormKey nav, NavmeshGeometry geo, FormKey? world, short gx, short gy, FormKey? cell) ni)>();
byte[] naviTail = new byte[] { 0, 0, 0, 0, 0 };
if (navInfos.Count > 0 && Environment.GetEnvironmentVariable("NAVI") != "off" && sfData0 != null)
{
    using var sfm = StarfieldMod.CreateFromBinaryOverlay(Path.Combine(sfData0, "Starfield.esm"), release);
    var vn = sfm.NavigationMeshInfoMaps.FirstOrDefault();
    if (vn == null) Console.WriteLine("NAVI: Starfield.esm has none; not written");
    else
    {
        // tail after the pathing cell: navmesh_survey.py --exterior parsed Starfield.esm's 56,631 NVMI (xEdit layout):
        // 44,710 end 00 00000000 (unknown byte 0, empty array); ShatteredSpace.esm the same (22,249 of 29,270).
        // (Reading it here from Mutagen's raw Unknown matched the layout in only 748 of 20,000 and gave 0F00000000.)
        Console.WriteLine($"NAVI: vanilla {vn.FormKey} ({vn.MapInfos.Count} entries); ours end {Convert.ToHexString(naviTail)}");
        naviO = (NavigationMeshInfoMap)vn.DeepCopy();
        naviO.MapInfos.Clear();                                       // ours only: the game merges the overrides
        foreach (var ni in navInfos)
        {
            float sx = 0, sy = 0, sz = 0;
            foreach (var v in ni.geo.Vertices) { sx += v.Point.X; sy += v.Point.Y; sz += v.Point.Z; }
            int nv = Math.Max(1, ni.geo.Vertices.Count);
            var data = new byte[20];
            BitConverter.GetBytes(sx / nv).CopyTo(data, 4);
            BitConverter.GetBytes(sy / nv).CopyTo(data, 8);
            BitConverter.GetBytes(sz / nv).CopyTo(data, 12);
            var info = new NavigationMapInfo { NavigationMesh = new FormLink<INavigationMeshGetter>(ni.nav), Data = data };
            foreach (var m in ni.geo.EdgeLinks.Select(l => l.Mesh.FormKey).Where(m => m != ni.nav).Distinct().OrderBy(m => m.ID))
                info.MergedTo.Add(new FormLink<INavigationMeshGetter>(m));
            foreach (var d in ni.geo.DoorTriangles.Select(dt => dt.Door.FormKey).Distinct().OrderBy(d => d.ID))
                info.LinkedDoors.Add(new LinkedDoor { Type = 0xE48B73F3, Door = new FormLink<IPlacedObjectGetter>(d) });
            naviO.MapInfos.Add(info);
            naviBody.Add((info, ni));
        }
        mod.NavigationMeshInfoMaps.Add(naviO);
    }
}
// the raw part of each NVMI: no traversals, no island, pathing cell (FormIDs with the written file's master indices)
void FillNavi(IReadOnlyList<ModKey> masters)
{
    uint Raw(FormKey k)
    {
        int idx = k.ModKey == modKey ? masters.Count : masters.ToList().IndexOf(k.ModKey);
        if (idx < 0) throw new InvalidOperationException($"NAVI: {k.ModKey} is not a master of {modKey}");
        return ((uint)idx << 24) | (k.ID & 0xFFFFFF);
    }
    foreach (var (info, ni) in naviBody)
    {
        var u = new List<byte>();
        u.AddRange(BitConverter.GetBytes(0u));                    // traversals
        u.Add(0);                                                 // no island data
        u.AddRange(BitConverter.GetBytes(0xA5E9A03Cu));           // PathingCell
        if (ni.world is FormKey w)
        {
            u.AddRange(BitConverter.GetBytes(Raw(w)));
            u.AddRange(BitConverter.GetBytes(ni.gy));             // grid Y, then X (as in NVNM)
            u.AddRange(BitConverter.GetBytes(ni.gx));
        }
        else
        {
            u.AddRange(BitConverter.GetBytes(0u));
            u.AddRange(BitConverter.GetBytes(Raw(ni.cell!.Value)));
        }
        u.AddRange(naviTail);
        info.Unknown = u.ToArray();
    }
}
// MAST entries of a written plugin, in order (its TES4 header's subrecords)
List<ModKey> MastersOf(string file)
{
    var b = File.ReadAllBytes(file);
    var res = new List<ModKey>();
    int size = BitConverter.ToInt32(b, 4), p = 24, end = 24 + size;
    while (p + 6 <= end)
    {
        var sig = System.Text.Encoding.ASCII.GetString(b, p, 4);
        int len = BitConverter.ToUInt16(b, p + 4);
        if (sig == "MAST") res.Add(ModKey.FromNameAndExtension(System.Text.Encoding.UTF8.GetString(b, p + 6, len).TrimEnd('\0')));
        p += 6 + len;
    }
    return res;
}
if (naviO != null) FillNavi(new[] { sfEsm, extKey, planetKey }.Where(k => k != null).Select(k => k!.Value).ToList());

mod.ModHeader.Stats.NextFormID = next;
var path = Path.Combine(outDir, modKey.FileName);
var sfData = Environment.GetEnvironmentVariable("STARFIELD_DATA") ?? throw new InvalidOperationException("set STARFIELD_DATA to the Starfield Data folder");
var knownMasters = new[] { (ModKey?)sfEsm, extKey, planetKey }.Where(k => k != null)
    .Select(k => new KeyedMasterStyle(k!.Value, MasterStyle.Full)).ToArray();
void WriteMod()
{
    if (extKey == null)
        mod.BeginWrite.ToPath(path).WithLoadOrderFromHeaderMasters().WithDataFolder(sfData)
            .WithKnownMasters(knownMasters).Write();
    else
        // with the exterior overrides: the masters' load order given (as TerrainOverlays writes its planet plugin); the
        // header-master route only knew Starfield.esm and threw on the exterior plugin's records
        mod.BeginWrite.ToPath(path).WithLoadOrder(new[] { (ModKey?)sfEsm, extKey, planetKey }.Where(k => k != null)
                .Select(k => k!.Value).ToArray())
            .WithKnownMasters(knownMasters).Write();
}
WriteMod();
if (naviO != null)
{
    // second pass: the NVMI pathing cells with the master indices the written file really has
    var written = MastersOf(path);
    FillNavi(written);
    WriteMod();
    Console.WriteLine($"NAVI override: {naviBody.Count} navmeshes registered (masters {string.Join(", ", written)})");
}
File.WriteAllText(mapPath, JsonSerializer.Serialize(ids.OrderBy(kv => kv.Value).ToDictionary(kv => kv.Key, kv => kv.Value),
    new JsonSerializerOptions { WriteIndented = true }));
File.WriteAllText(Path.Combine(outDir, "source_map.json"), JsonSerializer.Serialize(sourceMap, new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine($"wrote {path} ({new FileInfo(path).Length:N0} bytes); {ids.Count} stable FormIDs in {mapPath}; source_map.json");
