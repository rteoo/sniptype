from rich_text_support import extract_plain_text, is_rich_text_payload
from variable_support import find_variable_names

PREVIEW_CHARS = 60


def snippet_row_values(key, value, preview_chars=PREVIEW_CHARS):
    """Return ``(trigger, preview, markers)`` for one Treeview row.

    Read-only: snippet values are user data and are never mutated here.
    """
    plain = extract_plain_text(value)
    preview = " ".join(plain.split())
    if len(preview) > preview_chars:
        preview = preview[: preview_chars - 1].rstrip() + "…"

    markers = []
    if is_rich_text_payload(value):
        markers.append("RT")
    if find_variable_names(plain):
        markers.append("%%")
    return key, preview, " ".join(markers)


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


def center_on_screen(dialog, vertical_divisor=2):
    """Center a dialog on the screen.

    Used by dialogs whose parent is the hidden shared root, which has no
    meaningful geometry to center against.
    """
    dialog.update_idletasks()
    width = dialog.winfo_reqwidth()
    height = dialog.winfo_reqheight()
    x = (dialog.winfo_screenwidth() - width) // 2
    y = (dialog.winfo_screenheight() - height) // vertical_divisor
    dialog.geometry(f"{width}x{height}+{x}+{y}")


def center_dialog(dialog, root):
    dialog.update_idletasks()
    width = dialog.winfo_reqwidth()
    height = dialog.winfo_reqheight()
    x = root.winfo_rootx() + (root.winfo_width() - width) // 2
    y = root.winfo_rooty() + (root.winfo_height() - height) // 2
    dialog.geometry(f"{width}x{height}+{x}+{y}")
