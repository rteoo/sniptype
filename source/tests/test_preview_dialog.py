import unittest

from preview_dialog import (
    PreviewDialogController,
    apply_preview_model,
    build_preview_model,
    style_masks,
)
from preview_support import PreviewResult


class FakeText:
    def __init__(self):
        self.value = ""
        self.options = {"state": "normal", "font": "TkDefaultFont"}
        self.configured_tags = {}
        self.added_tags = []

    def cget(self, key):
        return self.options[key]

    def configure(self, **options):
        self.options.update(options)

    config = configure

    def delete(self, *_args):
        self.value = ""

    def insert(self, _index, value):
        self.value += value

    def tag_configure(self, name, **options):
        self.configured_tags[name] = options

    def tag_remove(self, *_args):
        return None

    def tag_add(self, name, start, end):
        self.added_tags.append((name, start, end))


class FakeStatus:
    def __init__(self):
        self.options = {}

    def configure(self, **options):
        self.options.update(options)

    config = configure


class FakeWindow:
    def __init__(self):
        self.calls = []
        self.exists = True

    def title(self, value):
        self.calls.append(("title", value))

    def protocol(self, name, callback):
        self.calls.append(("protocol", name, callback))

    def transient(self, root):
        self.calls.append(("transient", root))

    def lift(self):
        self.calls.append(("lift",))

    def deiconify(self):
        self.calls.append(("deiconify",))

    def withdraw(self):
        self.calls.append(("withdraw",))

    def winfo_exists(self):
        return self.exists


class PreviewDialogTests(unittest.TestCase):
    def test_model_is_tk_free_and_preserves_unresolved_placeholders(self):
        result = PreviewResult("Hi ‹clipboard› / ‹dynamic:xrate›", ("clipboard-paste", "xrate"))

        model = build_preview_model(result)

        self.assertEqual("Hi ‹clipboard› / ‹dynamic:xrate›", model.text)
        self.assertEqual((), model.spans)
        self.assertEqual(("clipboard-paste", "xrate"), model.unavailable)
        self.assertIn("clipboard-paste", model.status_text)

    def test_rich_spans_become_combined_masks(self):
        result = PreviewResult({
            "__kind__": "rich_text",
            "text": "abcd",
            "spans": [
                {"tag": "bold", "start": 0, "end": 3},
                {"tag": "italic", "start": 1, "end": 4},
            ],
        })

        model = build_preview_model(result)

        self.assertEqual((1, 3, 3, 2), style_masks(model))

    def test_apply_renders_read_only_text_and_marks_unavailable_ranges(self):
        widget = FakeText()
        result = PreviewResult("Hi ‹clipboard›", ("clipboard-paste",))

        apply_preview_model(widget, build_preview_model(result), configure_styles=False)

        self.assertEqual("Hi ‹clipboard›", widget.value)
        self.assertEqual("disabled", widget.options["state"])
        self.assertTrue(any(tag[0] == "preview_unavailable" for tag in widget.added_tags))

    def test_controller_reuses_one_toplevel_and_has_headless_builder_seam(self):
        windows = []
        text = FakeText()
        status = FakeStatus()

        def make_window(_root):
            window = FakeWindow()
            windows.append(window)
            return window

        def build_widgets(_window, _controller):
            return text, status

        controller = PreviewDialogController(
            object(), window_factory=make_window, widget_builder=build_widgets
        )
        first = controller.show(PreviewResult("first"))
        second = controller.show(PreviewResult("second"))

        self.assertIs(first, second)
        self.assertEqual(1, len(windows))
        self.assertEqual("second", text.value)
        self.assertEqual("disabled", text.options["state"])
        controller.close()
        self.assertIn(("withdraw",), windows[0].calls)


if __name__ == "__main__":
    unittest.main()
