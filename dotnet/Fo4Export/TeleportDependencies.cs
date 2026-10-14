using Mutagen.Bethesda.Fallout4;

/// <summary>Resolve destination locations from actual cell membership, not editor-ID guesses.</summary>
public static class TeleportDependencies
{
    public sealed record Location(string formkey, string? editor_id, string? worldspace);
    public sealed record Dependency(string source, string? door, Location? destination_cell,
        string? destination_base, string? transition_interior, Location? transition_cell);

    public static Dependency[] Build(IEnumerable<IPlacedObjectGetter> sources,
        IEnumerable<(ICellGetter Cell, string? Worldspace)> cells)
    {
        var teleports = sources.Where(r => r.TeleportDestination != null).ToArray();
        if (teleports.Length == 0) return Array.Empty<Dependency>();
        var wantedDoors = teleports.Select(r => r.TeleportDestination!.Door.FormKey.ToString()).ToHashSet();
        var wantedCells = teleports.Where(r => !r.TeleportDestination!.TransitionInterior.IsNull)
            .Select(r => r.TeleportDestination!.TransitionInterior.FormKey.ToString()).ToHashSet();
        var doors = new Dictionary<string, (Location Cell, string? Base)>();
        var transitions = new Dictionary<string, Location>();
        foreach (var (cell, worldspace) in cells)
        {
            var location = new Location(cell.FormKey.ToString(), cell.EditorID, worldspace);
            if (wantedCells.Contains(location.formkey)) transitions.Add(location.formkey, location);
            foreach (var r in cell.Temporary.Concat(cell.Persistent).OfType<IPlacedObjectGetter>())
                if (wantedDoors.Contains(r.FormKey.ToString()))
                    doors.Add(r.FormKey.ToString(), (location, r.Base.IsNull ? null : r.Base.FormKey.ToString()));
        }
        return teleports.Select(r =>
        {
            var t = r.TeleportDestination!;
            var door = t.Door.IsNull ? null : t.Door.FormKey.ToString();
            var transition = t.TransitionInterior.IsNull ? null : t.TransitionInterior.FormKey.ToString();
            var destination = door != null && doors.TryGetValue(door, out var found) ? found : default;
            return new Dependency(r.FormKey.ToString(), door, destination.Cell, destination.Base,
                transition, transition != null && transitions.TryGetValue(transition, out var c) ? c : null);
        }).ToArray();
    }
}
