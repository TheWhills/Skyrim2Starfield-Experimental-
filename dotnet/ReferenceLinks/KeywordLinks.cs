using System.Drawing;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Mutagen.Bethesda.Plugins;
using Mutagen.Bethesda.Starfield;

public static class KeywordLinks
{
    public static Dictionary<string, Keyword> Create(StarfieldMod mod, Dictionary<string, uint> ids,
        IEnumerable<JsonElement> exports, HashSet<string> used, HashSet<uint> occupied, ref uint next, LinkReport report)
    {
        var targets = new Dictionary<string, Keyword>(StringComparer.OrdinalIgnoreCase);
        var definitions = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var export in exports)
        {
            if (!export.TryGetProperty("referenced_keywords", out var keywords)) continue;
            foreach (var source in keywords.EnumerateArray())
            {
                var key = source.GetProperty("formkey").GetString()!;
                if (!used.Contains(key)) continue;
                var editorId = source.GetProperty("editor_id").GetString();
                var type = source.GetProperty("type").GetString();
                var typeValue = source.GetProperty("type_value").ValueKind == JsonValueKind.Null ? (int?)null
                    : source.GetProperty("type_value").GetInt32();
                var flags = source.GetProperty("record_flags").GetInt32();
                var attraction = source.GetProperty("attraction_rule").GetString();
                var name = source.TryGetProperty("name", out var sourceName) ? sourceName.GetString() : null;
                var notes = source.TryGetProperty("notes", out var sourceNotes) ? sourceNotes.GetString() : null;
                var color = source.GetProperty("color").ValueKind == JsonValueKind.Null ? null
                    : source.GetProperty("color").EnumerateArray().Select(x => x.GetInt32()).ToArray();
                var definition = JsonSerializer.Serialize(new { editorId, type, typeValue, flags, attraction, color, name, notes });
                if (definitions.TryGetValue(key, out var prior))
                {
                    if (prior != definition) throw new InvalidOperationException($"conflicting source keyword definitions for {key}");
                    continue;
                }
                definitions.Add(key, definition);
                if ((type == null ? typeValue != null : type != "None" || typeValue != 0) || flags != 0 || attraction != null ||
                    (color != null && (color.Length != 3 || color.Any(x => x < 0 || x > 255))))
                {
                    report.Issues.Add(new(key, "keyword", null, "non-generic keyword semantics/flags or invalid color require a translator"));
                    continue;
                }
                var identity = "KYWD:" + key;
                Keyword? target = null;
                if (ids.TryGetValue(identity, out var id))
                {
                    target = mod.Keywords.FirstOrDefault(k => k.FormKey == new FormKey(mod.ModKey, id));
                    if (target == null && occupied.Contains(id)) throw new InvalidOperationException($"keyword ID for {key} occupies another record type");
                }
                else
                {
                    if (next >= 0x1000000) throw new InvalidOperationException("full plugin FormID space exhausted");
                    id = next++; ids.Add(identity, id);
                }
                if (target == null)
                {
                    var stem = Regex.Replace(editorId ?? "LinkedKeyword", "[^A-Za-z0-9_]", "_");
                    var salt = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(key.ToLowerInvariant())))[..16];
                    target = new Keyword(new FormKey(mod.ModKey, id), StarfieldRelease.Starfield)
                    { EditorID = $"FO4Port_{stem}_{salt}", Type = type == null ? null : Keyword.TypeEnum.None };
                    if (color != null) target.Color = Color.FromArgb(color[0], color[1], color[2]);
                    mod.Keywords.Add(target); report.CreatedKeywords++;
                }
                target.Type = type == null ? null : Keyword.TypeEnum.None;
                target.Color = color == null ? null : Color.FromArgb(color[0], color[1], color[2]);
                target.Name = name;
                target.Notes = notes;
                targets.Add(key, target);
            }
        }
        return targets;
    }
}
