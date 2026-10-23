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
        var g = n.GetProperty("geometry");
        var geo = new NavmeshGeometry
        {
            NavmeshVersion = 17,
            CrcHash = 0xA5E9A03C,                                                      // PathingCell
            Parent = new CellNavmeshParent { Parent = new FormLink<ICellGetter>(cell.FormKey) },
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
            if (!placedBySource.TryGetValue(door, out var doorKey)) { doorsLost++; continue; }
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
        geo.GridMax = new P3Float(b[3].GetSingle() / UnitsPerMetre, b[4].GetSingle() / UnitsPerMetre, b[5].GetSingle() / UnitsPerMetre);
        // Mutagen's Starfield GridArrays is not per cell: one flat Int16 run (each cell's u32 count as two Int16, then its
        // triangles) read to the end, then Int32 Unknown3. cell.json carries that run ("grid_raw", skyrimnavmesh.grid_shorts).
        var gridRun = new NavmeshGridArray();
        foreach (var x in g.GetProperty("grid_raw").EnumerateArray()) gridRun.GridCell.Add(x.GetInt16());
        geo.GridArrays.Add(gridRun);
        geo.Unknown3 = g.GetProperty("tail_int32").GetInt32();
        cell.NavigationMeshes.Add(new NavigationMesh(keys[src], release) { NavmeshGeometry = geo });
        written++;
    }
    return written == 0 ? "" : $"; navmeshes {written} ({triangles} triangles, door links {doorsKept} kept / {doorsLost} to doors not placed)";
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
    int lights = 0, placed = 0, skipped = 0, disabled = 0;
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
    var cid = cell.FormKey.ID;
    var block = new CellBlock { BlockNumber = (int)(cid % 10), GroupType = GroupTypeEnum.InteriorCellBlock };
    var sub = new CellSubBlock { BlockNumber = (int)((cid / 10) % 10), GroupType = GroupTypeEnum.InteriorCellSubBlock };
    sub.Cells.Add(cell);
    block.SubBlocks.Add(sub);
    mod.Cells.Records.Add(block);
    Console.WriteLine($"cell {cellName} {cell.FormKey}: placed {placed} references + {lights} lights ({disabled} initially disabled), skipped {skipped}{navNote}");
}

int teleLinked = 0, teleLost = 0;
foreach (var (obj, t) in pendingTeleports)
{
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

mod.ModHeader.Stats.NextFormID = next;
var path = Path.Combine(outDir, modKey.FileName);
var sfData = Environment.GetEnvironmentVariable("STARFIELD_DATA") ?? throw new InvalidOperationException("set STARFIELD_DATA to the Starfield Data folder");
mod.BeginWrite.ToPath(path).WithLoadOrderFromHeaderMasters().WithDataFolder(sfData)
    .WithKnownMasters(new KeyedMasterStyle(sfEsm, MasterStyle.Full))
    .Write();
File.WriteAllText(mapPath, JsonSerializer.Serialize(ids.OrderBy(kv => kv.Value).ToDictionary(kv => kv.Key, kv => kv.Value),
    new JsonSerializerOptions { WriteIndented = true }));
File.WriteAllText(Path.Combine(outDir, "source_map.json"), JsonSerializer.Serialize(sourceMap, new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine($"wrote {path} ({new FileInfo(path).Length:N0} bytes); {ids.Count} stable FormIDs in {mapPath}; source_map.json");
