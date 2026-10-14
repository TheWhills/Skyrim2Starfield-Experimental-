using Mutagen.Bethesda.Fallout4;

public static class KeywordExport
{
    public static object Build(IKeywordGetter keyword) => new
    {
        formkey = keyword.FormKey.ToString(), editor_id = keyword.EditorID,
        record_flags = keyword.MajorRecordFlagsRaw,
        name = keyword.Name?.String, notes = keyword.Notes, display_name = keyword.DisplayName,
        type = keyword.Type?.ToString(), type_value = keyword.Type == null ? (int?)null : (int)keyword.Type.Value,
        color = keyword.Color == null ? null : new[] { (int)keyword.Color.Value.R, keyword.Color.Value.G, keyword.Color.Value.B },
        attraction_rule = keyword.AttractionRule.IsNull ? null : keyword.AttractionRule.FormKey.ToString(),
    };
}
