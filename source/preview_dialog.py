"""Read-only Tk preview rendering for the snippet manager.

Resolution belongs to :mod:`preview_support`; this module only turns its
result into a small view model or a read-only window.  It never resolves a
provider, reads the clipboard, invokes the inserter, or records workflow
state.
"""

from dataclasses import dataclass
import tkinter as tk

import ui_theme
from i18n import N_, _
from preview_support import (
    CLIPBOARD_PLACEHOLDER,
    DYNAMIC_PLACEHOLDER_TEMPLATE,
    PreviewResult,
)
from rich_text_support import (
    MAX_STYLE_MASK,
    STYLE_BITS,
    configure_rich_text_widget,
    is_rich_text_payload,
    normalize_style_spans,
)


UNAVAILABLE_TAG = "preview_unavailable"


@dataclass(frozen=True)
class PreviewModel:
    """Tk-free representation of a resolved preview."""

    text: str
    spans: tuple
    unavailable: tuple = ()

    @property
    def status_text(self):
        if not self.unavailable:
            return ""
        names = ", ".join(self.unavailable)
        return _("Indisponível na prévia: {names}").format(names=names)


def build_preview_model(result):
    """Extract plain text, normalized rich spans, and unavailable names.

    Accepting either ``PreviewResult`` or its payload keeps this seam useful
    in headless tests and for callers that already separated result state.
    """
    if isinstance(result, PreviewResult):
        payload = result.payload
        unavailable = tuple(dict.fromkeys(result.unavailable or ()))
    else:
        payload = result
        unavailable = ()
    if is_rich_text_payload(payload):
        text = payload["text"]
        spans = tuple(normalize_style_spans(payload.get("spans"), len(text)))
    else:
        text = "" if payload is None else str(payload)
        spans = ()
    return PreviewModel(text, spans, unavailable)


def style_masks(model):
    """Return the effective style bit mask for each character in ``model``."""
    if not isinstance(model, PreviewModel):
        model = build_preview_model(model)
    masks = [0] * len(model.text)
    for span in model.spans:
        bit = STYLE_BITS[span["tag"]]
        for offset in range(span["start"], min(span["end"], len(masks))):
            masks[offset] |= bit
    return tuple(masks)


def unavailable_ranges(model):
    """Return ``(start, end, name)`` ranges for visible unavailable tokens."""
    if not isinstance(model, PreviewModel):
        model = build_preview_model(model)
    ranges = []
    for name in model.unavailable:
        token = (
            CLIPBOARD_PLACEHOLDER
            if name == "clipboard-paste"
            else DYNAMIC_PLACEHOLDER_TEMPLATE.format(name=name)
        )
        start = 0
        while True:
            start = model.text.find(token, start)
            if start < 0:
                break
            end = start + len(token)
            ranges.append((start, end, name))
            start = end
    return tuple(ranges)


def _offset_index(offset):
    return f"1.0+{offset}c"


def _configure_unavailable_tag(text_widget, theme):
    text_widget.tag_configure(
        UNAVAILABLE_TAG,
        foreground=theme.warning,
        underline=1,
    )


def _apply_style_masks(text_widget, masks):
    if not masks:
        return
    run_start = 0
    current = masks[0]
    for offset in range(1, len(masks) + 1):
        next_mask = masks[offset] if offset < len(masks) else None
        if next_mask == current:
            continue
        text_widget.tag_add(
            f"fmt_{current}",
            _offset_index(run_start),
            _offset_index(offset),
        )
        run_start = offset
        current = next_mask


def _clear_preview_tags(text_widget):
    """Remove tags from a previous model before reusing the Text widget."""
    for mask in range(MAX_STYLE_MASK + 1):
        text_widget.tag_remove(f"fmt_{mask}", "1.0", "end")
    text_widget.tag_remove(UNAVAILABLE_TAG, "1.0", "end")


def apply_preview_model(text_widget, model, *, theme=None, configure_styles=True):
    """Populate ``text_widget`` and leave it disabled/read-only.

    ``configure_styles=False`` is a deliberate headless-test seam; production
    callers keep the default so rich-text tags use the project's existing font
    conventions from :func:`rich_text_support.configure_rich_text_widget`.
    """
    if not isinstance(model, PreviewModel):
        model = build_preview_model(model)
    theme = theme or ui_theme.theme()
    text_widget.configure(state="normal")
    text_widget.delete("1.0", "end")
    text_widget.insert("1.0", model.text)
    _clear_preview_tags(text_widget)
    if configure_styles and model.spans:
        configure_rich_text_widget(text_widget)
    _apply_style_masks(text_widget, style_masks(model))
    _configure_unavailable_tag(text_widget, theme)
    for start, end, _name in unavailable_ranges(model):
        text_widget.tag_add(
            UNAVAILABLE_TAG,
            _offset_index(start),
            _offset_index(end),
        )
    text_widget.configure(state="disabled")
    return model


class PreviewDialogController:
    """Own one reusable preview ``Toplevel`` attached to a shared root."""

    def __init__(
        self,
        shared_root,
        *,
        theme=None,
        window_factory=None,
        widget_builder=None,
        configure_styles=True,
    ):
        self.shared_root = shared_root
        self.theme = theme or ui_theme.theme()
        self.window_factory = window_factory or tk.Toplevel
        self.widget_builder = widget_builder or self._build_widgets
        self.configure_styles = configure_styles
        self._window = None
        self._text_widget = None
        self._status_widget = None
        self._model = None

    @property
    def window(self):
        return self._window

    @property
    def model(self):
        return self._model

    def _window_exists(self):
        if self._window is None:
            return False
        try:
            return bool(self._window.winfo_exists())
        except (AttributeError, tk.TclError):
            return False

    def _build_widgets(self, window, _controller):
        frame = tk.Frame(window, bg=self.theme.card)
        frame.pack(fill="both", expand=True, padx=self.theme.space_lg, pady=self.theme.space_lg)
        text_widget = tk.Text(
            frame,
            wrap="word",
            width=80,
            height=20,
            font=self.theme.font(10),
            padx=self.theme.space_sm,
            pady=self.theme.space_sm,
            **self.theme.text_colors(),
            **self.theme.field_chrome(),
        )
        text_widget.pack(fill="both", expand=True)
        status = tk.Label(
            frame,
            text="",
            anchor="w",
            bg=self.theme.card,
            fg=self.theme.warning,
            font=self.theme.font(8),
        )
        status.pack(fill="x", pady=(self.theme.space_sm, 0))
        close = tk.Button(
            frame,
            text=_("Fechar"),
            command=self.close,
            **self.theme.button_chrome(compact=True),
            **self.theme.button_colors(),
        )
        close.pack(anchor="e", pady=(self.theme.space_sm, 0))
        return text_widget, status

    def show(self, result, *, title=N_("Prévia")):
        """Show or refresh the one preview window and return its Toplevel."""
        model = build_preview_model(result)
        if not self._window_exists():
            self._window = self.window_factory(self.shared_root)
            self._text_widget, self._status_widget = self.widget_builder(self._window, self)
            self._window.protocol("WM_DELETE_WINDOW", self.close)
            self._window.transient(self.shared_root)
        self._model = model
        apply_preview_model(
            self._text_widget,
            model,
            theme=self.theme,
            configure_styles=self.configure_styles,
        )
        self._status_widget.configure(text=model.status_text)
        self._window.title(_(title))
        self._window.deiconify()
        self._window.lift()
        return self._window

    def close(self):
        """Hide the reusable window without destroying or changing state."""
        if self._window_exists():
            self._window.withdraw()


__all__ = [
    "PreviewDialogController",
    "PreviewModel",
    "UNAVAILABLE_TAG",
    "apply_preview_model",
    "build_preview_model",
    "style_masks",
    "unavailable_ranges",
]
