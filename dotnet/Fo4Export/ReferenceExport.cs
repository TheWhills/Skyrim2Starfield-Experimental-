using Mutagen.Bethesda.Fallout4;

/// <summary>Loss-conscious placement JSON; relationships are retained for later translators.</summary>
public static class ReferenceExport
{
    public static object Build(IPlacedObjectGetter r, string type, string baseEditorId, string model, bool persistent)
    {
        var parent = r.EnableParent;
        var teleport = r.TeleportDestination;
        return new
        {
            formkey = r.FormKey.ToString(), type, base_editor_id = baseEditorId, model,
            base_formkey = r.Base.IsNull ? null : r.Base.FormKey.ToString(),
            pos = new[] { r.Position.X, r.Position.Y, r.Position.Z },
            rot = new[] { r.Rotation.X, r.Rotation.Y, r.Rotation.Z },
            scale = r.Scale ?? 1.0f,
            disabled = r.MajorRecordFlagsRaw & 0x800,
            record_flags = r.MajorRecordFlagsRaw,
            persistent,
            bound_half_extents = r.BoundHalfExtents is {} bounds ? new[] { bounds.X, bounds.Y, bounds.Z } : null,
            primitive = r.Primitive == null ? null : new
            {
                bounds = new[] { r.Primitive.Bounds.X, r.Primitive.Bounds.Y, r.Primitive.Bounds.Z },
                color = new[] { (int)r.Primitive.Color.R, (int)r.Primitive.Color.G, (int)r.Primitive.Color.B, (int)r.Primitive.Color.A },
                unknown = r.Primitive.Unknown,
                type = r.Primitive.Type.ToString(), type_value = (int)r.Primitive.Type,
            },
            open_by_default = r.OpenByDefault,
            ownership = r.Ownership == null ? null : new
            {
                owner = r.Ownership.Owner.IsNull ? null : r.Ownership.Owner.FormKey.ToString(),
                no_crime = r.Ownership.NoCrime, unknown = r.Ownership.Unknown,
            },
            faction_rank = r.FactionRank,
            lock_data = r.Lock == null ? null : new
            {
                level = (int)r.Lock.Level,
                key = r.Lock.Key.IsNull ? null : r.Lock.Key.FormKey.ToString(),
                flags = (uint)r.Lock.Flags, unused = r.Lock.Unused,
            },
            enable_parent = parent == null ? null : new
            {
                reference = parent.Reference.IsNull ? null : parent.Reference.FormKey.ToString(),
                flags = (uint)parent.Flags,
            },
            linked_references = r.LinkedReferences.Select(link => new
            {
                keyword_or_reference = link.KeywordOrReference.IsNull ? null : link.KeywordOrReference.FormKey.ToString(),
                reference = link.Reference.IsNull ? null : link.Reference.FormKey.ToString(),
            }).ToArray(),
            teleport_destination = teleport == null ? null : new
            {
                door = teleport.Door.IsNull ? null : teleport.Door.FormKey.ToString(),
                pos = new[] { teleport.Position.X, teleport.Position.Y, teleport.Position.Z },
                rot = new[] { teleport.Rotation.X, teleport.Rotation.Y, teleport.Rotation.Z },
                flags = (uint)teleport.Flags,
                transition_interior = teleport.TransitionInterior.IsNull ? null : teleport.TransitionInterior.FormKey.ToString(),
            },
        };
    }

    public static object BuildActor(IPlacedNpcGetter r, bool persistent) => new
    {
        formkey = r.FormKey.ToString(), type = "PlacedNpc",
        reason = "actor_translation_not_implemented",
        base_formkey = r.Base.IsNull ? null : r.Base.FormKey.ToString(),
        pos = new[] { r.Position.X, r.Position.Y, r.Position.Z },
        rot = new[] { r.Rotation.X, r.Rotation.Y, r.Rotation.Z },
        scale = r.Scale ?? 1.0f, record_flags = r.MajorRecordFlagsRaw,
        disabled = r.MajorRecordFlagsRaw & 0x800, persistent,
        enable_parent = r.EnableParent == null ? null : new
        {
            reference = r.EnableParent.Reference.IsNull ? null : r.EnableParent.Reference.FormKey.ToString(),
            flags = (uint)r.EnableParent.Flags,
        },
        linked_references = r.LinkedReferences.Select(link => new
        {
            keyword_or_reference = link.KeywordOrReference.IsNull ? null : link.KeywordOrReference.FormKey.ToString(),
            reference = link.Reference.IsNull ? null : link.Reference.FormKey.ToString(),
        }).ToArray(),
        ownership = r.Ownership == null ? null : new
        {
            owner = r.Ownership.Owner.IsNull ? null : r.Ownership.Owner.FormKey.ToString(),
            no_crime = r.Ownership.NoCrime, unknown = r.Ownership.Unknown,
        },
        faction_rank = r.FactionRank,
    };
}
