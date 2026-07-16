from rich_text_support import extract_plain_text


def filter_static_snippets(snippets, query):
    lowered = query.strip().lower()
    visible = {
        key: value
        for key, value in snippets.items()
        if (not key.startswith("_")) and (not callable(value))
    }
    if not lowered:
        return visible
    return {
        key: value
        for key, value in visible.items()
        if lowered in key.lower() or lowered in extract_plain_text(value).lower()
    }


def iter_filtered_mapping_items(mapping, query):
    lowered = query.strip().lower()
    if not isinstance(mapping, dict):
        return []
    items = []
    for key in sorted(mapping.keys()):
        if key == "__prefix__":
            continue
        value = extract_plain_text(mapping.get(key, ""))
        if lowered and lowered not in key.lower() and lowered not in value.lower():
            continue
        items.append(key)
    return items


def center_dialog(dialog, root):
    dialog.update_idletasks()
    width = dialog.winfo_reqwidth()
    height = dialog.winfo_reqheight()
    x = root.winfo_rootx() + (root.winfo_width() - width) // 2
    y = root.winfo_rooty() + (root.winfo_height() - height) // 2
    dialog.geometry(f"{width}x{height}+{x}+{y}")
