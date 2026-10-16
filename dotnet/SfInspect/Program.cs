// Inspect Starfield.esm: interior cells and their lighting templates, light records.
//   dotnet run -- <Starfield.esm> cells <substr>     interior cells (EditorID contains substr) + lighting template
//   dotnet run -- <Starfield.esm> lights <substr>    LIGH records (EditorID contains substr) + radius/colour
//   dotnet run -- <Starfield.esm> templates          lighting templates in use by interior cells (most used first)
// Terrain (read-only, docs/terrain/architecture.md):
//   wrld [substr]            every WRLD with terrain/planet/parent fields      sfbk [substr]   every SurfaceBlock (BTD path, sizes)
//   planetworlds             planets registering master worldspaces            wcells <WRLD> [out.tsv]   cells + ref positions
//   form <hex>... | form type:<TypePrefix> <EditorID substr>   one-level dump of any record      landcount
//   list <TypePrefix> [EditorID substr]   FormKey + EditorID of every matching record (e.g. list Water)
// Note: opening a plugin other than Starfield.esm needs a master flag lookup (not implemented).
using Mutagen.Bethesda.Plugins.Cache;
using Mutagen.Bethesda.Starfield;

if (args.Length > 0 && args[0] == "reflect")
{
    foreach (var asm in AppDomain.CurrentDomain.GetAssemblies().Concat(new[] { typeof(Mutagen.Bethesda.Plugins.ModKey).Assembly, typeof(StarfieldMod).Assembly }).Distinct())
        foreach (var ty in asm.GetTypes().Where(x => x.Name.Contains(args[1])))
            Console.WriteLine(ty.FullName);
    return;
}
using var mod = StarfieldMod.CreateFromBinaryOverlay(args[0], StarfieldRelease.Starfield);
var cells = mod.Cells.Records.SelectMany(b => b.SubBlocks).SelectMany(s => s.Cells).ToList();
var cache = mod.ToImmutableLinkCache();
string Name(Mutagen.Bethesda.Plugins.FormKey fk) =>
    cache.TryResolve<ILightingTemplateGetter>(fk, out var t) ? (t.EditorID ?? "") : "";

switch (args[1])
{
    case "cells":
        foreach (var c in cells.Where(c => (c.EditorID ?? "").Contains(args[2], StringComparison.OrdinalIgnoreCase)).Take(40))
            Console.WriteLine($"{c.EditorID}  {c.FormKey}  template={c.LightingTemplate.FormKey} {Name(c.LightingTemplate.FormKey)}  refs={c.Temporary.Count}");
        break;
    case "templates":
        foreach (var g in cells.Where(c => !c.LightingTemplate.IsNull).GroupBy(c => c.LightingTemplate.FormKey)
                     .OrderByDescending(g => g.Count()).Take(25))
            Console.WriteLine($"{g.Count(),5}  {g.Key}  {Name(g.Key)}  e.g. {g.First().EditorID}");
        break;
    case "statics":
        foreach (var s in mod.Statics.Where(s => (s.EditorID ?? "").Contains(args[2], StringComparison.OrdinalIgnoreCase)).Take(30))
            Console.WriteLine($"{s.EditorID}  {s.FormKey}  model={s.Model?.File}");
        break;
    case "doors":
        foreach (var d in mod.Doors.Where(d => (d.Model?.File?.ToString() ?? "").Contains(args[2], StringComparison.OrdinalIgnoreCase)).Take(3))
        {
            Console.WriteLine($"== {d.EditorID} {d.FormKey} model={d.Model?.File}");
            foreach (var p in d.GetType().GetProperties())
            {
                object? v; try { v = p.GetValue(d); } catch { continue; }
                var s = v switch { null => "null", string str => str, System.Collections.IEnumerable e and not string => "[" + string.Join(", ", e.Cast<object>().Take(6)) + "]", _ => v.ToString() };
                if (s != null && s.Length > 160) s = s.Substring(0, 160);
                Console.WriteLine($"   {p.Name} = {s}");
            }
        }
        break;
    case "agc":
        foreach (var d in mod.Doors.Where(d => (d.EditorID ?? "").Contains(args[2], StringComparison.OrdinalIgnoreCase)).Take(int.Parse(args.Length > 3 ? args[3] : "3")))
        {
            Console.WriteLine($"== {d.EditorID} {d.FormKey} model={d.Model?.File} flags={d.Flags}");
            foreach (var c in d.Components)
                foreach (var p in c.GetType().GetProperties())
                {
                    object? v; try { v = p.GetValue(c); } catch { continue; }
                    Console.WriteLine($"   {c.GetType().Name.Replace("BinaryOverlay","")}.{p.Name} = {v}");
                }
        }
        break;
    case "celldump":
        foreach (var c in cells.Where(c => string.Equals(c.EditorID, args[2], StringComparison.OrdinalIgnoreCase)).Take(1))
            foreach (var p in c.GetType().GetProperties())
            {
                object? v; try { v = p.GetValue(c); } catch { continue; }
                if (v == null || p.Name is "Temporary" or "Persistent" or "NavigationMeshes") continue;
                var s = v.ToString() ?? ""; if (s.Length > 140) s = s.Substring(0, 140);
                Console.WriteLine($"   {p.Name} = {s}");
            }
        break;
    case "graphs":   // every DOOR grouped by animation graph (ANAM) + skeleton: which vanilla doors slide, swing, lift
        foreach (var g in mod.Doors.Select(d => (d, agc: d.Components.OfType<IAnimationGraphComponentGetter>().FirstOrDefault()))
                     .Where(x => x.agc != null).GroupBy(x => x.agc!.ANAM ?? "").OrderByDescending(g => g.Count()))
        {
            Console.WriteLine($"{g.Count(),5}  {g.Key}");
            foreach (var x in g.Take(4))
                Console.WriteLine($"         {x.d.EditorID}  {x.d.FormKey}  {x.d.Model?.File}  rig={x.agc!.BNAM}");
        }
        break;
    case "doorprops":
        foreach (var p in typeof(Mutagen.Bethesda.Starfield.Door).GetProperties()) Console.WriteLine($"{p.PropertyType} {p.Name}");
        break;
    case "imgs":
        {
            var useCount = cells.Where(c => !c.ImageSpace.IsNull).GroupBy(c => c.ImageSpace.FormKey).ToDictionary(g => g.Key, g => g.Count());
            foreach (var i in mod.ImageSpaces.OrderByDescending(i => useCount.GetValueOrDefault(i.FormKey)).Take(30))
                Console.WriteLine($"{useCount.GetValueOrDefault(i.FormKey),5}  {i.FormKey}  {i.EditorID}");
        }
        break;
    case "wrld":     // read-only: every WRLD with its terrain/planet/parent fields (reflection dump; [substr] filters EditorID)
        {
            var filter = args.Length > 2 ? args[2] : "";
            var skip = new HashSet<string> { "TopCell", "SubCells", "LargeReferences", "Version2", "VersionControl", "FormVersion", "IsCompressed", "IsDeleted", "MajorFlags", "MajorRecordFlagsRaw", "SubCellsTimestamp", "SubCellsUnknown", "TopCellTimestamp", "Timestamp" };
            Console.WriteLine($"# WRLD count={mod.Worldspaces.Count}");
            foreach (var w in mod.Worldspaces.Where(w => (w.EditorID ?? "").Contains(filter, StringComparison.OrdinalIgnoreCase)))
            {
                var nCells = w.SubCells.SelectMany(b => b.Items).SelectMany(s => s.Items).Count();
                Console.WriteLine($"== {w.EditorID} {w.FormKey} subcells={nCells} topcell={(w.TopCell != null)}");
                foreach (var p in w.GetType().GetProperties())
                {
                    if (skip.Contains(p.Name) || p.GetIndexParameters().Length > 0) continue;
                    object? v; try { v = p.GetValue(w); } catch (Exception e) { v = "ERR " + e.GetType().Name; }
                    if (v == null) continue;
                    var s = v switch { string str => str, System.Collections.IEnumerable e and not string => "[" + string.Join(", ", e.Cast<object>().Take(8)) + "]", _ => v.ToString() ?? "" };
                    if (s.Length == 0 || s == "[]" || s == "Null" || s.EndsWith(":Null")) continue;
                    if (p.Name == "Name") s = s.Split(',').Skip(2).FirstOrDefault()?.Trim(' ', ']') ?? s;   // English name only
                    if (s.Length > 200) s = s.Substring(0, 200) + "...";
                    Console.WriteLine($"   {p.Name} = {s.Replace("\n", " ").Replace("\r", "")}");
                    // one level deeper for nested overlay structs (LandDefaults, MapData, Parent, Components, ...)
                    var nested = v is System.Collections.IEnumerable en && v is not string ? en.Cast<object>().Where(o => o.GetType().Namespace?.StartsWith("Mutagen") == true).ToList()
                               : (v.GetType().Namespace?.StartsWith("Mutagen.Bethesda.Starfield") == true ? new List<object> { v } : new List<object>());
                    foreach (var o in nested)
                        foreach (var q in o.GetType().GetProperties())
                        {
                            if (q.GetIndexParameters().Length > 0 || q.Name is "StaticRegistration" or "Registration") continue;
                            object? qv; try { qv = q.GetValue(o); } catch (Exception e) { qv = "ERR " + e.GetType().Name; }
                            if (qv == null) continue;
                            var qs = qv is System.Collections.IEnumerable qe && qv is not string ? "[" + string.Join(", ", qe.Cast<object>().Take(12)) + "]" : qv.ToString() ?? "";
                            if (qs.Length > 160) qs = qs.Substring(0, 160) + "...";
                            Console.WriteLine($"      {o.GetType().Name.Replace("BinaryOverlay", "")}.{q.Name} = {qs}");
                        }
                }
            }
        }
        break;
    case "list":     // read-only: list <TypePrefix> [EditorID substr] -> FormKey + EditorID of every match (max 500)
        {
            var tp = args[2]; var sub = args.Length > 3 ? args[3] : "";
            int n = 0;
            foreach (var r in mod.EnumerateMajorRecords().Where(r => r.GetType().Name.StartsWith(tp)
                         && (r.EditorID ?? "").Contains(sub, StringComparison.OrdinalIgnoreCase)))
            {
                if (n++ >= 500) { Console.WriteLine("... (more)"); break; }
                Console.WriteLine($"{r.FormKey}  {r.EditorID}");
            }
            Console.WriteLine($"{Math.Min(n, 500)} {tp} records");
        }
        break;
    case "form":     // read-only: form <hexid>... -> record type, EditorID and a one-level property dump
        {
            // form <hex>...           by FormID
            // form type:<TypePrefix> <EditorID substr>   e.g. form type:Planet Jemison
            Func<Mutagen.Bethesda.Plugins.Records.IMajorRecordGetter, bool> pick;
            if (args[2].StartsWith("type:"))
            {
                var tp = args[2].Substring(5); var sub = args.Length > 3 ? args[3] : "";
                pick = r => r.GetType().Name.StartsWith(tp) && (r.EditorID ?? "").Contains(sub, StringComparison.OrdinalIgnoreCase);
            }
            else
            {
                var want = args.Skip(2).Select(a => Convert.ToUInt32(a, 16) & 0xFFFFFF).ToHashSet();
                pick = r => want.Contains(r.FormKey.ID);
            }
            foreach (var r in mod.EnumerateMajorRecords().Where(pick).Take(12))
            {
                Console.WriteLine($"== {r.FormKey} {r.GetType().Name.Replace("BinaryOverlay", "")} {r.EditorID}");
                if (r is ICellGetter or IWorldspaceGetter) continue;   // use celldump / wrld for those
                foreach (var p in r.GetType().GetProperties())
                {
                    if (p.GetIndexParameters().Length > 0 || p.Name is "StaticRegistration" or "Registration") continue;
                    object? v; try { v = p.GetValue(r); } catch (Exception e) { v = "ERR " + e.GetType().Name; }
                    if (v == null) continue;
                    var s = v is System.Collections.IEnumerable en && v is not string ? "[" + string.Join(", ", en.Cast<object>().Take(16)) + "]" : v.ToString() ?? "";
                    if (s.Length == 0 || s == "[]") continue;
                    if (s.Length > 240) s = s.Substring(0, 240) + "...";
                    Console.WriteLine($"   {p.Name} = {s}");
                    if (v is System.Collections.IEnumerable en2 && v is not string)
                        foreach (var o in en2.Cast<object>().Where(o => o.GetType().Namespace?.StartsWith("Mutagen.Bethesda.Starfield") == true).Take(6))
                            foreach (var q in o.GetType().GetProperties().Where(q => q.GetIndexParameters().Length == 0 && q.Name != "StaticRegistration"))
                            {
                                object? qv; try { qv = q.GetValue(o); } catch { continue; }
                                if (qv == null) continue;
                                var qs = qv is System.Collections.IEnumerable qe && qv is not string ? "[" + string.Join(", ", qe.Cast<object>().Take(12)) + "]" : qv.ToString() ?? "";
                                if (qs.Length > 160) qs = qs.Substring(0, 160) + "...";
                                Console.WriteLine($"      {o.GetType().Name.Replace("BinaryOverlay", "")}.{q.Name} = {qs}");
                            }
                }
            }
        }
        break;
    case "sfbk":     // read-only: every SurfaceBlock (SFBK): BTD path (ANAM), category (NAM1), water height, nested DNAM/ENAM items
        {
            string Flat(object? o)
            {
                if (o == null) return "null";
                if (o is string s0) return s0;
                if (o is System.Collections.IEnumerable e && o is not string) return "[" + string.Join(",", e.Cast<object>().Take(16)) + "]";
                if (o.GetType().Namespace?.StartsWith("Mutagen.Bethesda.Starfield") == true)
                    return "{" + string.Join(" ", o.GetType().GetProperties().Where(q => q.GetIndexParameters().Length == 0 && q.Name != "StaticRegistration")
                        .Select(q => { object? v = null; try { v = q.GetValue(o); } catch { } return $"{q.Name}={(v is System.Collections.IEnumerable ve && v is not string ? "[" + string.Join(",", ve.Cast<object>().Take(16)) + "]" : v)}"; })) + "}";
                return o.ToString() ?? "";
            }
            var filter = args.Length > 2 ? args[2] : "";
            var blocks = mod.EnumerateMajorRecords().Where(r => r.GetType().Name.StartsWith("SurfaceBlock") && (r.EditorID ?? "").Contains(filter, StringComparison.OrdinalIgnoreCase)).ToList();
            Console.WriteLine($"# SFBK count={blocks.Count}");
            foreach (var b in blocks)
            {
                var t = b.GetType();
                string P(string n) { var p = t.GetProperty(n); object? v = null; try { v = p?.GetValue(b); } catch { } return Flat(v); }
                var meta = b.GetType().GetProperty("Components")?.GetValue(b) is System.Collections.IEnumerable comps ? string.Join(" ", comps.Cast<object>().Select(Flat)) : "";
                Console.WriteLine($"{b.FormKey}\t{b.EditorID}\tANAM={P("ANAM")}\tNAM1={P("NAM1")}\tWHGT={P("WHGT")}\tHNAM={P("HNAM")}\tINAM={P("INAM")}\tNAM5={P("NAM5")}\tDNAM={P("DNAM")}\tENAM={P("ENAM")}\tNAM3={P("NAM3")}\tNAM4={P("NAM4")}\tFNAM={P("FNAM")}\tMETA={meta}");
            }
        }
        break;
    case "wcells":   // read-only: wcells <WRLD EditorID> [out.tsv] -> per exterior cell: grid and ref position ranges; optional per-ref TSV
        {
            var w = mod.Worldspaces.First(x => string.Equals(x.EditorID, args[2], StringComparison.OrdinalIgnoreCase));
            var sub = w.SubCells.SelectMany(b => b.Items).SelectMany(s => s.Items).ToList();
            using var tsv = args.Length > 3 ? new StreamWriter(args[3]) : null;
            tsv?.WriteLine("cellx\tcelly\tref\tbase\tbasetype\tbaseedid\tx\ty\tz");
            var all = sub.Concat(w.TopCell != null ? new[] { w.TopCell } : Array.Empty<ICellGetter>());
            foreach (var c in all)
            {
                var refs = c.Temporary.Concat(c.Persistent).OfType<IPlacedObjectGetter>().ToList();
                var g = c.Grid?.Point;
                if (refs.Count > 0)
                    Console.WriteLine($"{c.FormKey} grid={g} flags={c.Flags} refs={refs.Count} x=[{refs.Min(r => r.Position.X):F1},{refs.Max(r => r.Position.X):F1}] y=[{refs.Min(r => r.Position.Y):F1},{refs.Max(r => r.Position.Y):F1}] z=[{refs.Min(r => r.Position.Z):F1},{refs.Max(r => r.Position.Z):F1}]");
                if (tsv != null)
                    foreach (var r in refs)
                    {
                        var bt = cache.TryResolve(r.Base.FormKey, out var baseRec) ? baseRec : null;
                        tsv.WriteLine($"{g?.X}\t{g?.Y}\t{r.FormKey}\t{r.Base.FormKey}\t{bt?.GetType().Name.Replace("BinaryOverlay", "")}\t{bt?.EditorID}\t{r.Position.X}\t{r.Position.Y}\t{r.Position.Z}");
                    }
            }
        }
        break;
    case "planetworlds": // read-only: planets (PNDT) that register master worldspaces (lat/long) + their surface tree
        {
            var wr = mod.Worldspaces.ToDictionary(w => w.FormKey, w => w.EditorID);
            var planets = mod.Planets.ToList();
            Console.WriteLine($"# PNDT count={planets.Count} with SurfaceTree={planets.Count(p => !p.SurfaceTree.IsNull)} with MasterWorldspaces={planets.Count(p => p.MasterWorldspaces.Count > 0)}");
            foreach (var p in planets.Where(p => p.MasterWorldspaces.Count > 0))
                foreach (var m in p.MasterWorldspaces)
                    Console.WriteLine($"{p.EditorID}\t{p.Name}\t{m.Worldspace.FormKey}\t{wr.GetValueOrDefault(m.Worldspace.FormKey)}\tlat={m.Latitude:F4}\tlon={m.Longitude:F4}\tsurfaceTree={p.SurfaceTree.FormKey}");
            var registered = planets.SelectMany(p => p.MasterWorldspaces.Select(m => m.Worldspace.FormKey)).ToHashSet();
            Console.WriteLine($"# worldspaces registered as master: {registered.Count} of {wr.Count}");
        }
        break;
    case "landcount": // read-only: count LAND records anywhere in the worldspace cells (FORMAT-GAP says 0)
        {
            int land = 0, ext = 0;
            foreach (var w in mod.Worldspaces)
                foreach (var c in w.SubCells.SelectMany(b => b.Items).SelectMany(s => s.Items).Concat(w.TopCell != null ? new[] { w.TopCell } : Array.Empty<ICellGetter>()))
                {
                    ext++;
                    var lp = c.GetType().GetProperty("Landscape");
                    if (lp != null && lp.GetValue(c) != null) land++;
                }
            Console.WriteLine($"exterior cells={ext} cells with Landscape={land} (Landscape property on cell type: {typeof(ICellGetter).GetProperty("Landscape") != null})");
        }
        break;
    case "lights":
        foreach (var l in mod.Lights.Where(l => (l.EditorID ?? "").Contains(args[2], StringComparison.OrdinalIgnoreCase)).Take(40))
            Console.WriteLine($"{l.EditorID}  {l.FormKey}  radius={l.Radius}  color={l.Color}  model={l.Model?.File}");
        break;
}
