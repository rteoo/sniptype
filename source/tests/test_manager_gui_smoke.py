"""GUI construction smoke test.

Builds every manager tab and the notification window on the app's shared Tk
root, driven through the GUI thread exactly the way the app drives it. Catches
widget-wiring bugs that the headless unit tests miss. Skipped automatically
where Tk cannot open a display (e.g. headless CI), and on macOS, where the
app's worker-thread Tk root is not something AppKit permits at all.
"""

import json
import logging
import os
import shutil
import sys
import gc
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_module import sniptype as tx  # .pyw is not importable off Windows
from gui_thread import GuiThread
from library_metadata import LibraryMetadata
import manager_actions
from platform_support import IS_MAC
from runtime_support import LOGGER_NAME
from workflow_support import SnippetRef
import ui_widgets

TK_AVAILABLE = False
TK_SKIP_REASON = "Tk display not available"

if IS_MAC:
    # The app owns its Tk root on a dedicated worker thread (see gui_thread).
    # macOS AppKit refuses to build an NSWindow off the main thread and aborts
    # the process ("NSWindow should only be instantiated on the main thread!")
    # instead of raising, so this has to be decided *before* the probe below:
    # the probe would take the whole suite down with it rather than fail over.
    # The app resolves this by moving the root to the main thread
    # there (``GuiThread`` main-thread mode); these smoke tests still drive the
    # worker-thread mode, which macOS does not permit, so they stay skipped.
    TK_SKIP_REASON = "macOS requires AppKit on the main thread; these tests drive the worker-thread root"
else:
    try:
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import ttk
        # One root for the whole module, like the app, which builds exactly
        # one per process. On Windows, creating a fresh Tk interpreter on a
        # new thread over and over eventually wedges one of those threads'
        # event loop (reproduced with plain tkinter, no app code, after ~100-
        # 400 interpreters), so a root per test made the suite hang at random.
        # The probe's root is that shared root.
        _SHARED_GUI = GuiThread(main_thread=False)
        _SHARED_GUI.ensure_started()
        TK_AVAILABLE = True
        # The Fluent theme builds ttk controls; macOS keeps the classic ones.
        BUTTONS = (tk.Button, ttk.Button)
        CHECKBOXES = (tk.Checkbutton, ttk.Checkbutton)
    except Exception:
        pass


def tearDownModule():
    if TK_AVAILABLE:
        _SHARED_GUI.stop()


def _reset_shared_root(app):
    """Destroy every window a test left on the shared root."""
    def cleanup(root):
        app._release_manager_ui_refs()
        for child in list(root.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        # Tk variables must be collected on the thread that owns the root.
        gc.collect()

    app.gui.call(cleanup, timeout=10)


def _make_app(base_dir):
    with open(os.path.join(base_dir, "snippets.json"), "w", encoding="utf-8") as handle:
        handle.write('{"xhi": "hello"}')
    previous_home = os.environ.get("SNIPTYPE_HOME")
    os.environ["SNIPTYPE_HOME"] = base_dir
    try:
        with mock.patch.object(tx, "get_runtime_base_dir", return_value=base_dir), \
                mock.patch.object(tx, "get_runtime_resource_dir",
                                  return_value=os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))):
            app = tx.Sniptype()
    finally:
        if previous_home is None:
            os.environ.pop("SNIPTYPE_HOME", None)
        else:
            os.environ["SNIPTYPE_HOME"] = previous_home
    if TK_AVAILABLE:
        app.gui = _SHARED_GUI
    return app


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _is_text_entry(widget):
    # ttk.Combobox subclasses tk.Entry; only typed fields count here.
    return isinstance(widget, tk.Entry) and not isinstance(widget, ttk.Combobox)


@unittest.skipUnless(TK_AVAILABLE, TK_SKIP_REASON)
class ManagerGuiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.app = _make_app(tempfile.mkdtemp())
        self.app.gui.ensure_started()

    def tearDown(self):
        _reset_shared_root(self.app)

    def _on_gui(self, func):
        """Run func(root) on the GUI thread, propagating assertion failures."""
        return self.app.gui.call(func, timeout=30)

    def test_library_selection_pill_moves_and_focus_preserves_its_neutral_fill(self):
        self.app.snippets["xother"] = "Synthetic second response"

        def run(root):
            self.app._build_manager_window(root)
            window = self.app.manager_window
            window.update()
            tab = self.app._manager_notebook.nametowidget(self.app._manager_notebook.tabs()[0])
            tree = next(w for w in _descendants(tab) if isinstance(w, ttk.Treeview))
            tree.selection_set("xhi")
            window.update()
            self.assertTrue(tree.item("xhi", "image"))
            tree.selection_set("xother")
            tree.focus_force()
            window.update()
            self.assertFalse(tree.item("xhi", "image"))
            self.assertTrue(tree.item("xother", "image"))
            ui = tx.ui_theme.theme()
            self.assertEqual((ui.px(3), ui.px(16)),
                             (tree.selection_pill.width(), tree.selection_pill.height()))
            self.assertEqual(ui.px(6), tree.column("#0", "width"))
            style = ttk.Style(tree)
            self.assertEqual(ui.select_bg, style.lookup("Manager.Treeview", "background", ("selected", "focus")))
            self.assertEqual(ui.surface_alt, style.lookup("Manager.Treeview", "background", ("selected", "!focus")))
            text = next(w for w in _descendants(tab) if isinstance(w, tk.Text))
            text.focus_force()
            window.update()
            self.assertTrue(tree.item("xother", "image"), "losing focus keeps the selection marker")

        self._on_gui(run)

    def test_disabled_filter_shows_only_disabled_group_rows_and_written_state(self):
        self.app.snippets.update({"xoff": "Synthetic disabled response", "xon": "Synthetic active response"})
        self.app.library_metadata = LibraryMetadata({
            "groups": {"off": {"label": "Disabled", "enabled": False}},
            "items": {"static": {"xoff": {"group_id": "off"}}},
        })

        def run(root):
            self.app._build_manager_window(root)
            window = self.app.manager_window
            window.update()
            tab = self.app._manager_notebook.nametowidget(self.app._manager_notebook.tabs()[0])
            next(w for w in _descendants(tab) if isinstance(w, BUTTONS)
                 and w.cget("text") == "Desativados").invoke()
            window.update()
            tree = next(w for w in _descendants(tab) if isinstance(w, ttk.Treeview))
            self.assertEqual(("xoff",), tree.get_children())
            self.assertIn("Desativado (grupo)", tree.item("xoff", "values")[1])
            self.assertIn("unavailable", tree.item("xoff", "tags"))
            self.assertEqual("Textos (3)", self.app._manager_notebook.tab(tab, "text"))

        self._on_gui(run)

    @unittest.skipUnless(tx.IS_WINDOWS, "Windows compact density")
    def test_minimum_library_shows_sixteen_complete_rows_and_one_primary(self):
        self.app.snippets.update({f"xsynth{i:02}": "Synthetic response" for i in range(40)})

        def run(root):
            self.app._build_manager_window(root)
            window = self.app.manager_window
            window.geometry("1180x760")
            window.update()
            tab = self.app._manager_notebook.nametowidget(self.app._manager_notebook.tabs()[0])
            tree = next(w for w in _descendants(tab) if isinstance(w, ttk.Treeview))
            visible = [tree.bbox(item) for item in tree.get_children() if tree.bbox(item)]
            complete = [box for box in visible if box[1] + box[3] <= tree.winfo_height()]
            self.assertGreaterEqual(len(complete), 16)
            buttons = [w for w in _descendants(tab) if isinstance(w, ttk.Button) and w.winfo_ismapped()]
            primaries = lambda: [w for w in buttons if str(w["style"]).endswith("Accent.TButton")]
            self.assertEqual(["Novo snippet"], [str(w["text"]) for w in primaries()])
            tree.selection_set("xhi")
            window.update()
            text = next(w for w in _descendants(tab) if isinstance(w, tk.Text))
            text.insert("end", " Synthetic edit")
            window.update()
            self.assertEqual(["Salvar"], [str(w["text"]) for w in primaries()])
            delete = next(w for w in buttons if w["text"] == "Excluir")
            save = next(w for w in buttons if w["text"] == "Salvar")
            self.assertGreaterEqual(save.winfo_rootx() - delete.winfo_rootx() - delete.winfo_width()
                                    + 2 * tx.ui_theme.theme().px(3), tx.ui_theme.theme().space_lg)

        self._on_gui(run)

    def test_empty_library_and_no_results_have_distinct_recovery_actions(self):
        def run(root):
            self.app._build_manager_window(root)
            window = self.app.manager_window
            window.update()
            tab = self.app._manager_notebook.nametowidget(self.app._manager_notebook.tabs()[0])
            search = self.app._manager_search_entries[str(tab)]
            clear = next(w for w in _descendants(tab) if isinstance(w, BUTTONS) and w.cget("text") == "Limpar busca")
            self.assertFalse(clear.winfo_ismapped(), "healthy rows must unmap empty-state actions")
            search.insert(0, "synthetic-no-match")
            window.update()
            visible_text = lambda: [str(w.cget("text")) for w in _descendants(tab)
                                    if isinstance(w, (tk.Label, *BUTTONS)) and w.winfo_ismapped()]
            self.assertIn("Nenhum snippet corresponde à busca ou aos filtros.", visible_text())
            self.assertTrue(clear.winfo_ismapped())
            clear.invoke()
            self.assertEqual("", search.get())
            window.update()
            self.assertFalse(clear.winfo_ismapped())
            self.app.snippets.clear()
            self.app.shadowed_static_snippets.clear()
            self.app._refresh_manager_lists()
            window.update()
            self.assertIn("Sua biblioteca está vazia.", visible_text())
            self.assertIn("Importar…", visible_text())
            self.assertNotIn("Limpar busca", visible_text())

        self._on_gui(run)

    def test_form_fields_use_the_shared_tree_and_keep_each_field_draft(self):
        from form_editor_dialog import FormEditor

        def run(root):
            dialog = FormEditor(root, {"fields": [
                {"name": "first", "type": "text", "default": "Synthetic first"},
                {"name": "second", "type": "text", "default": "Synthetic second"},
            ]})
            try:
                dialog.window.update()
                self.assertIsInstance(dialog._field_list, ttk.Treeview)
                self.assertEqual("Manager.Treeview", dialog._field_list["style"])
                dialog.default_var.set("Synthetic changed")
                dialog._field_list.selection_set("1")
                dialog.window.update()
                self.assertEqual("second", dialog.name_var.get())
                self.assertTrue(dialog._field_list.item("1", "image"))
                self.assertFalse(dialog._field_list.item("0", "image"))
                self.assertEqual("Synthetic changed", dialog.controller.fields[0]["default"])
                dialog._field_list.selection_set("0")
                dialog.window.update()
                self.assertEqual("Synthetic changed", dialog.default_var.get())
            finally:
                dialog.cancel()

        self._on_gui(run)

    def _shadowed_library(self):
        provider = mock.Mock(return_value="Synthetic dynamic output")
        self.app.snippets["xshadow"] = provider
        self.app.shadowed_static_snippets["xshadow"] = "Synthetic preserved static"
        self.app.library_metadata = LibraryMetadata({
            "items": {"static": {"xshadow": {"favorite": True}}},
        })
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        return provider

    def test_shadowed_static_discard_cancel_and_rename_keep_the_live_provider(self):
        provider = self._shadowed_library()

        def run(root):
            self.app._build_manager_window(root)
            window = self.app.manager_window
            window.update()
            tab = self.app._manager_notebook.nametowidget(self.app._manager_notebook.tabs()[0])
            tree = next(w for w in _descendants(tab) if isinstance(w, ttk.Treeview))
            tree.selection_set("xshadow")
            window.update()
            text = next(w for w in _descendants(tab) if isinstance(w, tk.Text))
            self.assertEqual("Synthetic preserved static", text.get("1.0", "end-1c"))
            for label in ("Duplicar", "Renomear", "Excluir", "Formulário", "Prévia"):
                self.assertFalse(_buttons(tab)[label].instate(["disabled"]))
            text.insert("end", " dirty")
            window.update()
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=None):
                tree.selection_set("xhi")
                window.update()
            self.assertEqual(("xshadow",), tree.selection())
            self.assertEqual("Synthetic preserved static dirty", text.get("1.0", "end-1c"))
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=tx.ui_widgets.EXTRA):
                tree.selection_set("xhi")
                window.update()
            tree.selection_set("xshadow")
            window.update()
            self.assertEqual("Synthetic preserved static", text.get("1.0", "end-1c"))
            with mock.patch.object(tx.ui_widgets, "ask_text", return_value="xresolved"), \
                    mock.patch.object(tx.ui_widgets, "confirm", return_value=True):
                _buttons(tab)["Renomear"].invoke()
            window.update()
            self.assertIs(provider, self.app.snippets["xshadow"])
            self.assertNotIn("xshadow", self.app.shadowed_static_snippets)
            self.assertEqual("Synthetic preserved static", self.app.snippets["xresolved"])
            self.assertEqual(("xresolved",), tree.selection())

        self._on_gui(run)
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            document = json.load(handle)
        self.assertNotIn("xshadow", document)
        self.assertEqual("Synthetic preserved static", document["xresolved"])
        self.assertTrue(document["__sniptype__"]["items"]["static"]["xresolved"]["favorite"])
        provider.assert_not_called()

    def test_shadowed_static_delete_and_undo_change_only_the_persisted_static(self):
        provider = self._shadowed_library()

        def run(root):
            self.app._build_manager_window(root)
            window = self.app.manager_window
            window.update()
            tab = self.app._manager_notebook.nametowidget(self.app._manager_notebook.tabs()[0])
            tree = next(w for w in _descendants(tab) if isinstance(w, ttk.Treeview))
            tree.selection_set("xshadow")
            window.update()
            _buttons(tab)["Excluir"].invoke()
            window.update()
            self.assertIs(provider, self.app.snippets["xshadow"])
            self.assertNotIn("xshadow", self.app.shadowed_static_snippets)
            with open(self.app.snippets_file, encoding="utf-8") as handle:
                self.assertNotIn("xshadow", json.load(handle))
            self.app._manager_receipts[str(tab)].action.invoke()
            window.update()
            self.assertIs(provider, self.app.snippets["xshadow"])
            self.assertEqual("Synthetic preserved static", self.app.shadowed_static_snippets["xshadow"])
            self.assertEqual(("xshadow",), tree.selection())

        self._on_gui(run)
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual("Synthetic preserved static", json.load(handle)["xshadow"])
        provider.assert_not_called()

    def test_shadowed_static_failed_rename_and_delete_roll_back_both_maps(self):
        provider = self._shadowed_library()

        def run(root):
            self.app._build_manager_window(root)
            window = self.app.manager_window
            window.update()
            tab = self.app._manager_notebook.nametowidget(self.app._manager_notebook.tabs()[0])
            tree = next(w for w in _descendants(tab) if isinstance(w, ttk.Treeview))
            tree.selection_set("xshadow")
            window.update()
            with mock.patch.object(self.app, "save_snippets", return_value=False), \
                    mock.patch.object(tx.ui_widgets, "alert"), \
                    mock.patch.object(tx.ui_widgets, "ask_text", return_value="xresolved"), \
                    mock.patch.object(tx.ui_widgets, "confirm", return_value=True):
                _buttons(tab)["Renomear"].invoke()
                window.update()
                self.assertIs(provider, self.app.snippets["xshadow"])
                self.assertNotIn("xresolved", self.app.snippets)
                self.assertEqual("Synthetic preserved static", self.app.shadowed_static_snippets["xshadow"])
                _buttons(tab)["Excluir"].invoke()
                window.update()
                self.assertIs(provider, self.app.snippets["xshadow"])
                self.assertEqual("Synthetic preserved static", self.app.shadowed_static_snippets["xshadow"])
            self.assertEqual(("xshadow",), tree.selection())

        self._on_gui(run)
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual("Synthetic preserved static", json.load(handle)["xshadow"])
        provider.assert_not_called()

    @unittest.skipUnless(tx.IS_WINDOWS, "the Segoe faces are Windows-only")
    def test_every_windows_text_face_is_the_face_tk_renders(self):
        # Regression: Tk silently substitutes Arial for a family it does not
        # know, so the requested spec proves nothing; ask Tk what it used.
        def probe(shared_root):
            ui = tx.ui_theme.bind(shared_root)
            specs = [ui.font(size, weight)
                     for size, weight in ((10, None), (10, "bold"), (16, None), (16, "bold"))]
            # Cascadia Mono where installed, else Consolas: either way, real.
            specs.append(ui.mono_font())
            for spec in specs:
                rendered = tkfont.Font(root=shared_root, font=spec).actual("family")
                self.assertEqual(rendered, spec[0], spec)

        self._on_gui(probe)

    def test_manager_minimum_size_keeps_editor_controls_and_mapping_columns_visible(self):
        """The smallest supported manager window must not clip its controls."""
        self.app.snippets["_cpf_numbers"] = {"__prefix__": "cpf", "synthetic": "Synthetic mapping value"}
        def build(shared_root):
            self.app._build_manager_window(shared_root)
            window = self.app.manager_window
            self.assertIsNotNone(window)
            _, min_width, min_height = tx.ui_theme.theme().manager_window_size
            window.geometry(f"{min_width}x{min_height}")
            window.deiconify()
            window.update()

            notebook = self.app._manager_notebook
            tab_ids = notebook.tabs()

            def is_descendant(widget, ancestor):
                while widget is not ancestor:
                    widget = widget.master
                    if widget is None:
                        return False
                return True

            for tab_id, expected_labels in (
                (tab_ids[0], {"Novo", "Salvar", "Duplicar", "Renomear", "Excluir", "Formulário", "Prévia"}),
                (tab_ids[1], {"Novo", "Salvar", "Excluir", "Formulário", "Prévia"}),
            ):
                notebook.select(tab_id)
                window.update()
                tab = notebook.nametowidget(tab_id)
                editor_label = next(
                    widget for widget in _descendants(tab)
                    if isinstance(widget, tk.Label) and widget.cget("text") in ("Trigger armazenado", "Identificador")
                )
                editor_pane = editor_label.master
                buttons = {
                    str(widget.cget("text")): widget
                    for widget in _descendants(editor_pane)
                    if isinstance(widget, BUTTONS)
                    and is_descendant(widget, editor_pane)
                }
                self.assertTrue(expected_labels <= buttons.keys())
                if tx.IS_WINDOWS and tab_id == tab_ids[0]:
                    self.assertEqual(
                        buttons["Novo"].winfo_rooty(),
                        buttons["Salvar"].winfo_rooty(),
                        "the text editor actions should fit on one row at minimum width",
                    )
                pane_right = editor_pane.winfo_rootx() + editor_pane.winfo_width()
                pane_bottom = editor_pane.winfo_rooty() + editor_pane.winfo_height()
                favorite = next(
                    widget for widget in _descendants(editor_pane)
                    if isinstance(widget, CHECKBOXES)
                    and widget.cget("text") == "Favorito"
                )
                for label, widget in [*((l, buttons[l]) for l in expected_labels),
                                      ("Favorito", favorite)]:
                    self.assertEqual(1, widget.winfo_ismapped(), label)
                    self.assertLessEqual(
                        widget.winfo_rootx() + widget.winfo_width(),
                        pane_right + 1,
                        f"{label} extends past the editor pane",
                    )
                    self.assertLessEqual(
                        widget.winfo_rooty() + widget.winfo_height(),
                        pane_bottom + 1,
                        f"{label} is cut off below the editor pane",
                    )
                content = next(
                    widget for widget in _descendants(editor_pane)
                    if isinstance(widget, tk.Text)
                )
                self.assertGreaterEqual(
                    content.winfo_height(), 60, "the content box collapsed"
                )
                format_label = next(widget for widget in _descendants(editor_pane)
                                    if isinstance(widget, tk.Label)
                                    and str(widget.cget("textvariable"))
                                    and str(widget.getvar(widget.cget("textvariable"))).startswith("Formato:"))
                self.assertGreaterEqual(format_label.winfo_width(), format_label.winfo_reqwidth())

            notebook.select(tab_ids[1])
            window.update()
            mapping_tab = notebook.nametowidget(tab_ids[1])
            tree = next(widget for widget in _descendants(mapping_tab)
                        if isinstance(widget, ttk.Treeview) and "trigger" in widget["columns"])
            configured_width = sum(tree.column(column, "width") for column in tree["columns"])
            self.assertLessEqual(
                configured_width,
                tree.winfo_width(),
                "mapping columns extend beyond the visible tree",
            )

        self._on_gui(build)

    def test_manager_sidebar_navigates_pages_and_mirrors_counts(self):
        def exercise(shared_root):
            self.app._build_manager_window(shared_root)
            window = self.app.manager_window
            window.update()
            notebook = self.app._manager_notebook
            self.assertEqual(str(notebook.cget("style")), "Pages.TNotebook")
            brand = next(
                widget for widget in _descendants(window)
                if isinstance(widget, tk.Label) and widget.cget("text") == tx.PRODUCT_NAME
            )
            # The app icon sits beside the title.
            self.assertTrue(str(brand.cget("image")))
            self.assertEqual(str(brand.cget("compound")), "left")
            titles = [notebook.tab(tab_id, "text") for tab_id in notebook.tabs()]
            nav = [
                widget for widget in _descendants(window)
                if isinstance(widget, BUTTONS) and widget.cget("text") in titles
            ]
            # One button per page, in tab order, carrying the page counts.
            self.assertEqual([button.cget("text") for button in nav], titles)
            self.assertEqual(titles[0], "Textos (1)")
            nav[1].invoke()
            window.update()
            self.assertEqual(notebook.select(), notebook.tabs()[1])
            self.assertTrue(nav[1].instate(["selected"]))
            self.assertFalse(nav[0].instate(["selected"]))

        self._on_gui(exercise)

    def test_manager_keyboard_shortcuts_switch_views_and_focus_search(self):
        def exercise(shared_root):
            self.app._build_manager_window(shared_root)
            window = self.app.manager_window
            window.deiconify()
            window.focus_force()
            window.update()
            notebook = self.app._manager_notebook
            tabs = notebook.tabs()

            for index in (2, 1):
                window.event_generate(f"<Control-Key-{index}>")
                window.update()
                self.assertEqual(notebook.select(), tabs[index - 1])
                window.event_generate("<Control-f>")
                window.update()
                self.assertEqual(
                    window.focus_get(), self.app._manager_search_entries[tabs[index - 1]]
                )

        self._on_gui(exercise)

    def test_dynamic_mappings_tab_lists_custom_types(self):
        self.app.snippets["_mail_codes"] = {"__prefix__": "mail", "team": "team@x.com"}

        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_dynamic_mappings_tab(frame, root)
            root.update_idletasks()
            listboxes = [w for w in _descendants(frame) if isinstance(w, ttk.Treeview) and not w["columns"]]
            self.assertTrue(listboxes, "expected the shared types Treeview")
            return [listboxes[0].item(item, "text") for item in listboxes[0].get_children()]

        labels = self._on_gui(build)
        self.assertIn("MAIL", labels)
        self.assertIn("CPF", labels)

    def _static_rows(self, frame):
        """{trigger: (value cell,)} from the static tab's Treeview."""
        trees = [w for w in _descendants(frame) if isinstance(w, ttk.Treeview)]
        self.assertTrue(trees, "expected a snippet Treeview")
        tree = trees[0]
        return {iid: tree.full_values[iid][1:] for iid in tree.get_children()}

    def test_static_tree_shows_preview_and_markers(self):
        self.app.snippets["xsig"] = {
            "__kind__": "rich_text",
            "text": "Assinatura\nprincipal",
            "spans": [],
        }
        self.app.snippets["xgreet"] = "Olá %%nome%%, tudo bem?"

        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_static_snippets_tab(frame, root)
            root.update_idletasks()
            return self._static_rows(frame)

        rows = self._on_gui(build)
        self.assertEqual(("Assinatura principal", "A", ""), rows["xsig"])
        self.assertEqual(("Olá %%nome%%, tudo bem?", "ƒ", ""), rows["xgreet"])
        self.assertEqual(("hello", "", ""), rows["xhi"])

    def test_selecting_a_tree_row_loads_the_editor(self):
        self.app.snippets["xsig"] = {
            "__kind__": "rich_text", "text": "Assinatura principal", "spans": [],
        }

        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_static_snippets_tab(frame, root)
            root.update_idletasks()

            tree = [w for w in _descendants(frame) if isinstance(w, ttk.Treeview)][0]
            tree.selection_set("xsig")
            root.update()

            # Entry order follows widget creation: search box, then trigger.
            entries = [w for w in _descendants(frame) if _is_text_entry(w)]
            text = [w for w in _descendants(frame) if isinstance(w, tk.Text)][0]
            return entries[1].get(), text.get("1.0", "end-1c")

        trigger, value = self._on_gui(build)
        self.assertEqual("xsig", trigger)
        self.assertEqual("Assinatura principal", value)

    def _save_static_from_editor(self, trigger, value, *, open_item=None):
        """Type trigger/value into the static editor and click Salvar.

        ``open_item`` opens that saved snippet first, so the save edits it
        instead of naming it from a new draft (which asks before replacing).
        """

        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_static_snippets_tab(frame, root)
            root.update_idletasks()

            entries = [w for w in _descendants(frame) if _is_text_entry(w)]
            text = [w for w in _descendants(frame) if isinstance(w, tk.Text)][0]
            if open_item:
                tree = [w for w in _descendants(frame) if isinstance(w, ttk.Treeview)][0]
                tree.selection_set(open_item)
                root.update()
            entries[1].delete(0, tk.END)
            text.delete("1.0", tk.END)
            entries[1].insert(0, trigger)
            text.insert("1.0", value)
            # The edit events make the draft dirty, which enables Salvar.
            root.update()
            button = [w for w in _descendants(frame)
                      if isinstance(w, BUTTONS) and w.cget("text") == "Salvar"][0]
            button.invoke()

        self._on_gui(build)

    def test_saving_a_static_over_a_dynamic_trigger_warns_first(self):
        # Regression: the warning check ran only when the trigger was absent from
        # the merged map, which is exactly False when a dynamic trigger owns the
        # name — so the one collision that needed validation skipped it.
        self.app.snippets["xdyn"] = lambda: "dinâmico"
        self.app.refresh_runtime_indexes()

        with mock.patch.object(tx.ui_widgets, "confirm", return_value=None) as ask:
            self._save_static_from_editor("xdyn", "meu texto")

        ask.assert_called_once()
        self.assertIn("dinâmico", ask.call_args[0][2])
        self.assertTrue(callable(self.app.snippets["xdyn"]), "refused save must not overwrite")

    def test_blank_key_is_not_a_row(self):
        """A blank key cannot be a Treeview iid; hand-edited data must not
        produce a phantom row or skew the tab count."""
        self.app.snippets[""] = "lixo"
        counts = []

        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_static_snippets_tab(frame, root, set_count=counts.append)
            root.update_idletasks()
            return self._static_rows(frame)

        rows = self._on_gui(build)
        self.assertNotIn("", rows)
        self.assertIn("xhi", rows)
        self.assertEqual([1], counts)

    def test_refresh_hook_repopulates_lists_after_library_swap(self):
        """Restore/import rebind self.snippets; registered lists must rebuild."""
        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_static_snippets_tab(frame, root)
            root.update_idletasks()
            return frame

        frame = self._on_gui(build)
        self.assertNotIn("ximported", self._on_gui(lambda _r: self._static_rows(frame)))

        # Stand in for restore_backup/import_library, which rebind the dict.
        self.app.snippets = {"ximported": "from backup"}

        def refresh(_root):
            self.app._refresh_manager_lists()
            return self._static_rows(frame)

        rows = self._on_gui(refresh)
        self.assertEqual({"ximported": ("from backup", "", "")}, rows)

    def _build_mappings_tab(self, shared_root, set_count=None):
        root = tk.Toplevel(shared_root)
        root.withdraw()
        frame = tk.Frame(root)
        self.app._create_dynamic_mappings_tab(frame, root, set_count=set_count)
        root.update_idletasks()
        return frame

    def _tree_rows(self, frame):
        """{key: (value cell,)} from the only Treeview in a tab."""
        trees = [w for w in _descendants(frame) if isinstance(w, ttk.Treeview) and "trigger" in w["columns"]]
        self.assertTrue(trees, "expected a snippet Treeview")
        tree = trees[0]
        return {iid: tree.full_values[iid][1:] for iid in tree.get_children()}

    def _tree_trigger_values(self, frame):
        trees = [w for w in _descendants(frame) if isinstance(w, ttk.Treeview) and "trigger" in w["columns"]]
        self.assertTrue(trees, "expected a snippet Treeview")
        tree = trees[0]
        return {
            iid: tree.full_values[iid][0]
            for iid in tree.get_children()
        }

    def test_mapping_tree_shows_preview_and_markers(self):
        self.app.snippets["_cpf_numbers"] = {
            "__prefix__": "cpf",
            "alice": "123.456.789-00",
            "assinada": {"__kind__": "rich_text", "text": "CPF\noficial", "spans": []},
            "modelo": "CPF de %%titular%%",
        }

        def build(root):
            frame = self._build_mappings_tab(root)
            return self._tree_rows(frame), self._tree_trigger_values(frame)

        rows, triggers = self._on_gui(build)

        self.assertNotIn("__prefix__", rows, "prefix metadata is not an item")
        self.assertEqual(("123.456.789-00", "", ""), rows["alice"])
        self.assertEqual(("CPF oficial", "A", ""), rows["assinada"])
        self.assertEqual(("CPF de %%titular%%", "ƒ", ""), rows["modelo"])
        with self.subTest("test_mapping_tree_shows_stored_and_effective_triggers"):
            self.assertEqual("alice → cpfalice", triggers["alice"])

    def test_refresh_hook_rebuilds_dynamic_registry_rows(self):
        self.app.dynamic_registry = {
            "stable": {
                "provider": "datetime",
                "category": "datetime",
                "description": "Renamed date",
                "trigger": "renamed",
                "enabled": True,
            }
        }

        def labels(frame):
            return [
                widget.cget("text")
                for widget in _descendants(frame)
                if isinstance(widget, tk.Label)
            ]

        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            frame = tk.Frame(root)
            self.app._create_dynamic_snippets_tab(frame, root)
            root.update_idletasks()
            return frame, labels(frame)

        frame, built_labels = self._on_gui(build)
        with self.subTest("test_dynamic_registry_shows_stored_and_effective_triggers"):
            self.assertIn("stable → renamed", built_labels)
        self.app.dynamic_registry["stable"]["trigger"] = "updated"

        def refresh(_root):
            self.app._refresh_manager_lists()
            return labels(frame)

        self.assertIn("stable → updated", self._on_gui(refresh))

    def test_refresh_hook_updates_metadata_controls_and_group_choices(self):
        def build(shared_root):
            root = tk.Toplevel(shared_root)
            root.withdraw()
            static_frame = tk.Frame(root)
            mapping_frame = tk.Frame(root)
            self.app._create_static_snippets_tab(static_frame, root)
            self.app._create_dynamic_mappings_tab(mapping_frame, root)
            root.update_idletasks()
            return static_frame, mapping_frame

        static_frame, mapping_frame = self._on_gui(build)
        self.app.library_metadata = LibraryMetadata(
            {
                "kind": "sniptype_metadata",
                "schema_version": 1,
                "groups": {"work": {"label": "Work"}},
                "items": {"static": {}, "mappings": {}},
            },
            raw_block={"schema_version": 99},
            read_only=True,
            present=True,
        )

        def refresh_and_states(_root):
            self.app._refresh_manager_lists()
            group_filter = next(
                widget for widget in _descendants(static_frame)
                if isinstance(widget, ttk.Combobox)
            )
            group_buttons = [
                widget for widget in group_filter.master.winfo_children()
                if isinstance(widget, BUTTONS)
            ]
            self.assertEqual(1, len(group_buttons), "one group-actions menu button")
            static_controls = group_buttons + [
                widget for widget in _descendants(static_frame)
                if isinstance(widget, BUTTONS + CHECKBOXES)
                and str(widget.cget("text")) in {
                    "Favorito", "Formulário", "Duplicar", "Renomear",
                }
            ]
            mapping_controls = [
                widget
                for widget in _descendants(mapping_frame)
                if isinstance(widget, BUTTONS + CHECKBOXES)
                and str(widget.cget("text")) in {"Favorito", "Formulário"}
            ]
            combos = [
                widget for widget in _descendants(static_frame)
                if isinstance(widget, ttk.Combobox)
            ]
            return (
                [str(widget.cget("state")) for widget in static_controls],
                [str(widget.cget("state")) for widget in mapping_controls],
                tuple(combos[0].cget("values")),
                tuple(combos[1].cget("values")),
                str(combos[0].cget("state")),
            )

        (static_controls, mapping_controls, filter_values, group_values,
         filter_state) = self._on_gui(refresh_and_states)
        self.assertTrue(static_controls)
        self.assertTrue(mapping_controls)
        self.assertEqual({"disabled"}, set(static_controls))
        self.assertEqual({"disabled"}, set(mapping_controls))
        # Filtering only reads, so it stays usable with read-only metadata.
        self.assertEqual("readonly", filter_state)
        self.assertEqual(("Todos os grupos", "Sem grupo", "Work"), filter_values)
        # The editor's picker shows group labels, never their ids.
        self.assertEqual(("Sem grupo", "Work"), group_values)

    def _build_static_tab(self, shared_root):
        root = tk.Toplevel(shared_root)
        root.withdraw()
        # As the app does for every Toplevel; without it the tab depends on an
        # earlier test having installed this palette's theme.
        tx.ui_theme.prepare_window(root, tx.ui_theme.bind(root))
        frame = tk.Frame(root)
        self.app._create_static_snippets_tab(frame, root)
        root.update_idletasks()
        return root, frame

    def _persist(self, result):
        self.assertTrue(self.app._persist_manager_action(result))

    def _saved_static_metadata(self, key):
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            document = json.load(handle)
        return document.get("__sniptype__", {}).get("items", {}).get("static", {}).get(key, {})

    @staticmethod
    def _checked(checkbox):
        return checkbox.tk.getboolean(checkbox.getvar(str(checkbox.cget("variable"))))

    def test_favorite_persists_with_the_bundled_providers_and_new_clears_it(self):
        # Regression: the bundled providers made every metadata action raise
        # TypeError, so the box showed checked while nothing was saved.
        self.assertTrue(callable(self.app.snippets.get("xhoje")))

        def run(shared_root):
            root, frame = self._build_static_tab(shared_root)
            tree = next(w for w in _descendants(frame) if isinstance(w, ttk.Treeview))
            favorite = next(
                w for w in _descendants(frame)
                if isinstance(w, CHECKBOXES) and w.cget("text") == "Favorito"
            )
            tree.selection_set("xhi")
            root.update()
            favorite.invoke()
            root.update()
            after_toggle = self._checked(favorite)
            tree.selection_set("xhi")
            root.update()
            reselected = self._checked(favorite)
            new = next(
                w for w in _descendants(frame)
                if isinstance(w, BUTTONS) and w.cget("text") == "Novo"
            )
            new.invoke()
            root.update()
            return after_toggle, reselected, self._checked(favorite)

        with mock.patch.object(tx.ui_widgets, "alert") as alert:
            after_toggle, reselected, after_new = self._on_gui(run)

        alert.assert_not_called()
        self.assertTrue(self._saved_static_metadata("xhi").get("favorite"))
        self.assertTrue(after_toggle)
        self.assertTrue(reselected)
        self.assertFalse(after_new, "Novo must not carry the previous item's Favorito")

    def test_group_picker_shows_labels_and_assigns_the_group_id(self):
        self._persist(manager_actions.create_group(
            self.app.snippets, self.app.library_metadata,
            group_id="3f2a9c1e-5b7d", label="Trabalho",
        ))

        def run(shared_root):
            root, frame = self._build_static_tab(shared_root)
            tree = next(w for w in _descendants(frame) if isinstance(w, ttk.Treeview))
            picker = [w for w in _descendants(frame) if isinstance(w, ttk.Combobox)][1]
            values = tuple(picker.cget("values"))
            tree.selection_set("xhi")
            root.update()
            before = picker.get()
            picker.set("Trabalho")
            picker.event_generate("<<ComboboxSelected>>")
            root.update()
            assigned = picker.get()
            new = next(
                w for w in _descendants(frame)
                if isinstance(w, BUTTONS) and w.cget("text") == "Novo"
            )
            new.invoke()
            root.update()
            return values, before, assigned, picker.get()

        with mock.patch.object(tx.ui_widgets, "alert") as alert:
            values, before, assigned, after_new = self._on_gui(run)

        alert.assert_not_called()
        self.assertEqual(("Sem grupo", "Trabalho"), values)
        self.assertEqual("Sem grupo", before)
        self.assertEqual("Trabalho", assigned)
        self.assertEqual("3f2a9c1e-5b7d", self._saved_static_metadata("xhi").get("group_id"))
        self.assertEqual("Sem grupo", after_new)

    def test_search_finds_the_effective_trigger_and_ranks_triggers_first(self):
        # Regression: the list showed "sig → assig" but "assig" found nothing.
        self.app.snippets["sig"] = "Atenciosamente"
        self.app.snippets["xnota"] = "use assig no fim"
        self._persist(manager_actions.create_group(
            self.app.snippets, self.app.library_metadata,
            group_id="mail", label="Correio", prefix="as",
        ))
        self._persist(manager_actions.assign_item(
            self.app.snippets, self.app.library_metadata, "sig", "mail",
        ))

        def run(shared_root):
            root, frame = self._build_static_tab(shared_root)
            search = [w for w in _descendants(frame) if _is_text_entry(w)][0]
            search.insert(0, "assig")
            root.update()
            tree = next(w for w in _descendants(frame) if isinstance(w, ttk.Treeview))
            return [(iid, tree.full_values[iid][0]) for iid in tree.get_children()]

        self.assertEqual(
            [("sig", "sig → assig"), ("xnota", "xnota")], self._on_gui(run)
        )

    def test_capture_failure_reads_as_failed_and_cannot_be_resumed(self):
        self.app.enabled = False
        self.app.capture_error = OSError("hook unavailable")

        def run(shared_root):
            self.app._build_manager_window(shared_root)
            self.app.manager_window.update_idletasks()
            button = self.app._manager_toggle_button
            return (
                self.app._manager_status_var.get(),
                str(button.cget("text")),
                str(button.cget("state")),
            )

        status, text, state = self._on_gui(run)
        self.assertEqual("Captura falhou", status)
        self.assertEqual("Reinicie o SnipType", text)
        self.assertEqual("disabled", state)

    def test_mapping_tab_counts_every_type_not_just_the_selected_one(self):
        self.app.snippets["_cpf_numbers"] = {"__prefix__": "cpf", "alice": "1", "bruno": "2"}
        self.app.snippets["_mail_codes"] = {"__prefix__": "mail", "team": "team@x.com"}
        counts = []

        self._on_gui(lambda r: self._build_mappings_tab(r, set_count=counts.append))

        # 2 CPF + 1 mail; CPF is selected but the title reports the library.
        self.assertEqual(3, counts[-1])

    def test_mapping_count_ignores_the_search_filter(self):
        self.app.snippets["_cpf_numbers"] = {"__prefix__": "cpf", "alice": "1", "bruno": "2"}
        counts = []

        def build_and_search(shared_root):
            frame = self._build_mappings_tab(shared_root, set_count=counts.append)
            entries = [w for w in _descendants(frame) if _is_text_entry(w)]
            entries[0].insert(0, "alice")
            frame.winfo_toplevel().update()
            return self._tree_rows(frame)

        rows = self._on_gui(build_and_search)
        self.assertEqual(["alice"], list(rows), "search should still narrow the list")
        self.assertEqual(2, counts[-1], "count reports the library, not the filter")

    def test_mapping_blank_key_is_not_a_row(self):
        self.app.snippets["_cpf_numbers"] = {"__prefix__": "cpf", "": "lixo", "alice": "1"}
        counts = []

        def build(shared_root):
            frame = self._build_mappings_tab(shared_root, set_count=counts.append)
            return self._tree_rows(frame)

        rows = self._on_gui(build)
        self.assertNotIn("", rows)
        self.assertEqual(["alice"], list(rows))
        self.assertEqual(1, counts[-1], "a blank key is not an item")

    def test_mapping_save_rejects_reserved_prefix_metadata(self):
        self.app.snippets["_cpf_numbers"] = {
            "__prefix__": "cpf",
            "alice": "123",
        }

        def build(shared_root):
            frame = self._build_mappings_tab(shared_root)
            entries = [w for w in _descendants(frame) if _is_text_entry(w)]
            text = [w for w in _descendants(frame) if isinstance(w, tk.Text)][0]
            entries[1].insert(0, "__prefix__")
            text.insert("1.0", "must not replace metadata")
            # Shown: Tk drops a generated key aimed at an unmapped window.
            frame.pack(fill=tk.BOTH, expand=True)
            frame.winfo_toplevel().deiconify()
            frame.winfo_toplevel().update()
            button = next(
                widget for widget in _descendants(frame)
                if isinstance(widget, BUTTONS) and str(widget.cget("text")) == "Salvar"
            )
            # Salvar waits for a valid draft and the editor names the problem;
            # Ctrl+S, the same command, says why it does not save.
            state = str(button.cget("state"))
            shown = [str(w.cget("text")) for w in _descendants(frame) if isinstance(w, tk.Label)]
            _press(entries[1], "<Control-s>")
            return state, shown

        with mock.patch.object(tx.ui_widgets, "alert") as warning, \
                mock.patch.object(self.app, "save_snippets", return_value=True) as save:
            state, shown = self._on_gui(build)

        self.assertEqual("disabled", state)
        self.assertIn("'__prefix__' é reservado para o prefixo do tipo de mapeamento.", shown)
        warning.assert_called_once()
        self.assertIn("__prefix__", warning.call_args.args[2])
        save.assert_not_called()
        self.assertEqual(
            {"__prefix__": "cpf", "alice": "123"},
            self.app.snippets["_cpf_numbers"],
        )

    def test_new_mapping_type_rejects_duplicate_effective_prefix_and_preserves_imported_type(self):
        imported = {"__prefix__": "mail", "team": "team@example.test"}
        self.app.snippets["_imported_codes"] = imported

        def build(shared_root):
            frame = self._build_mappings_tab(shared_root)
            new_button = next(
                widget for widget in _descendants(frame)
                if isinstance(widget, BUTTONS) and str(widget.cget("text")) == "Novo tipo"
            )
            new_button.invoke()
            dialog = next(
                child for child in _descendants(shared_root)
                if isinstance(child, tk.Toplevel) and child.title() == "Novo tipo de mapeamento"
            )
            entries = [w for w in _descendants(dialog) if _is_text_entry(w)]
            entries[0].insert(0, "outro")
            entries[1].insert(0, "mail")
            create = next(
                widget for widget in _descendants(dialog)
                if isinstance(widget, BUTTONS) and str(widget.cget("text")) == "Criar tipo"
            )
            create.invoke()
            texts = [str(w.cget("text")) for w in _descendants(dialog) if isinstance(w, tk.Label)]
            dialog.destroy()
            return texts

        with mock.patch.object(tx.ui_widgets, "alert") as alert, \
                mock.patch.object(self.app, "save_snippets", return_value=True) as save:
            texts = self._on_gui(build)

        alert.assert_not_called()
        self.assertTrue(any("mail" in text and "em uso" in text for text in texts), texts)
        save.assert_not_called()
        self.assertEqual(imported, self.app.snippets["_imported_codes"])
        self.assertNotIn("_outro_codes", self.app.snippets)

    def test_mapping_save_rolls_back_the_entire_mapping_on_persistence_failure(self):
        original = {"__prefix__": "cpf", "alice": "old"}
        self.app.snippets["_cpf_numbers"] = dict(original)

        def build(shared_root):
            frame = self._build_mappings_tab(shared_root)
            tree = [w for w in _descendants(frame) if isinstance(w, ttk.Treeview) and "trigger" in w["columns"]][0]
            text = [w for w in _descendants(frame) if isinstance(w, tk.Text)][0]
            # Open alice: naming a saved identifier from a new draft would ask
            # before replacing it.
            tree.selection_set("alice")
            frame.winfo_toplevel().update()
            text.delete("1.0", tk.END)
            text.insert("1.0", "new")
            frame.winfo_toplevel().update()
            button = next(
                widget for widget in _descendants(frame)
                if isinstance(widget, BUTTONS) and str(widget.cget("text")) == "Salvar"
            )
            button.invoke()

        with mock.patch.object(self.app, "save_snippets", return_value=False) as save, \
                mock.patch.object(tx.ui_widgets, "alert") as error:
            self._on_gui(build)

        save.assert_called_once()
        error.assert_called_once()
        self.assertEqual("danger", error.call_args.kwargs["tone"])
        self.assertEqual(original, self.app.snippets["_cpf_numbers"])

    def test_new_mapping_type_rolls_back_on_persistence_failure(self):
        def build(shared_root):
            frame = self._build_mappings_tab(shared_root)
            new_button = next(
                widget for widget in _descendants(frame)
                if isinstance(widget, BUTTONS) and str(widget.cget("text")) == "Novo tipo"
            )
            new_button.invoke()
            dialog = next(
                child for child in _descendants(shared_root)
                if isinstance(child, tk.Toplevel) and child.title() == "Novo tipo de mapeamento"
            )
            entries = [w for w in _descendants(dialog) if _is_text_entry(w)]
            entries[0].insert(0, "outro")
            entries[1].insert(0, "mail")
            create = next(
                widget for widget in _descendants(dialog)
                if isinstance(widget, BUTTONS) and str(widget.cget("text")) == "Criar tipo"
            )
            create.invoke()
            dialog.destroy()

        with mock.patch.object(self.app, "save_snippets", return_value=False) as save, \
                mock.patch.object(tx.ui_widgets, "alert") as error:
            self._on_gui(build)

        save.assert_called_once()
        error.assert_called_once()
        self.assertEqual("danger", error.call_args.kwargs["tone"])
        self.assertNotIn("_outro_codes", self.app.snippets)

    def test_new_static_warns_when_composed_mapping_trigger_collides(self):
        self.app.snippets["_cpf_numbers"] = {
            "__prefix__": "cpf",
            "alice": "mapped",
        }
        self.app.refresh_runtime_indexes()

        with mock.patch.object(tx.ui_widgets, "confirm", return_value=None) as ask:
            self._save_static_from_editor("cpfalice", "static")

        ask.assert_called_once()
        self.assertIn("cpfalice", ask.call_args.args[2])
        self.assertIn("mapeamento dinâmico", ask.call_args.args[2])
        self.assertIn("estático tem prioridade", ask.call_args.args[2])
        self.assertNotIn("cpfalice", self.app.snippets)

    def test_editing_existing_static_composed_collision_does_not_warn_about_itself(self):
        self.app.snippets["_cpf_numbers"] = {
            "__prefix__": "cpf",
            "alice": "mapped",
        }
        self.app.snippets["cpfalice"] = "old static"
        self.app.refresh_runtime_indexes()

        with mock.patch.object(tx.ui_widgets, "confirm", return_value=tx.ui_widgets.PRIMARY) as ask:
            self._save_static_from_editor("cpfalice", "updated static", open_item="cpfalice")

        ask.assert_not_called()
        self.assertEqual("updated static", self.app.snippets["cpfalice"])

    def _settings_widgets(self, cls, predicate=lambda _widget: True):
        tab = self.app._manager_settings_tab
        return [w for w in _descendants(tab) if isinstance(w, cls) and predicate(w)]

    def test_settings_tab_toggles_terminator_mode_and_persists_it(self):
        def run(shared_root):
            self.app._build_manager_window(shared_root)
            self.assertIsNotNone(self.app._manager_settings_tab)
            sections = self.app._manager_settings_sections
            self.assertEqual(list(sections.frames), ["general", "hotkeys", "data"])
            check, = self._settings_widgets(
                CHECKBOXES, lambda w: "modo terminador" in w.cget("text"))
            self.assertFalse(self.app.terminator_mode)
            check.invoke()
            self.assertTrue(self.app.terminator_mode)
            self.assertTrue(self.app.trigger_index["global_terminator_mode"])
            self.assertTrue(tx.load_settings(self.app.settings_file)["terminator_mode"])
            check.invoke()
            self.assertFalse(self.app.terminator_mode)

        self._on_gui(run)

    def test_failed_terminator_save_keeps_the_runtime_unchanged(self):
        def run(shared_root):
            self.app._build_manager_window(shared_root)
            check, = self._settings_widgets(
                CHECKBOXES, lambda w: "modo terminador" in w.cget("text"))
            with mock.patch.object(tx, "save_settings", return_value=False):
                check.invoke()
            self.assertFalse(self.app.terminator_mode)
            self.assertEqual(self.app.settings.get("terminator_mode", False), False)

        self._on_gui(run)

    def test_applying_an_appearance_rebuilds_the_manager_on_the_settings_tab(self):
        self.addCleanup(tx.ui_theme.set_preference, None)

        def run(shared_root):
            self.app._build_manager_window(shared_root)
            first = self.app.manager_window
            # No saved appearance: the manager opens in the Dark default.
            self.assertEqual(ttk.Style(first).theme_use(), "sniptype-fluent-dark")
            combo, = self._settings_widgets(
                ttk.Combobox, lambda w: tx.ui_theme.APPEARANCE_LABELS["light"] in w.cget("values"))
            self.assertEqual(combo.get(), tx.ui_theme.APPEARANCE_LABELS["dark"])
            combo.set(tx.ui_theme.APPEARANCE_LABELS["light"])
            apply, = self._settings_widgets(
                BUTTONS, lambda w: w.cget("text") == "Aplicar aparência")
            # Nothing is unsaved, so nothing asks.
            with mock.patch.object(tx.ui_widgets, "confirm") as confirm:
                apply.invoke()
            confirm.assert_not_called()
            first.update()
            rebuilt = self.app.manager_window
            self.assertIsNot(rebuilt, first)
            self.assertFalse(first.winfo_exists())
            self.assertFalse(tx.ui_theme.theme().is_dark)
            self.assertEqual(tx.load_settings(self.app.settings_file)["appearance"], "light")
            self.assertEqual(
                self.app._manager_notebook.select(), str(self.app._manager_settings_tab))
            self.assertEqual(ttk.Style(rebuilt).theme_use(), "sniptype-fluent-light")

        self._on_gui(run)

    def _start_a_static_draft(self, window):
        """Open xhi in the manager's Textos editor and change it, unsaved."""
        tab = self.app._manager_notebook.nametowidget(self.app._manager_notebook.tabs()[0])
        tree = next(w for w in _descendants(tab) if isinstance(w, ttk.Treeview))
        text = next(w for w in _descendants(tab) if isinstance(w, tk.Text))
        tree.selection_set("xhi")
        window.update()
        text.insert("end", " (rascunho)")
        window.update()
        return text

    def test_declining_the_reload_changes_nothing(self):
        self.addCleanup(tx.ui_theme.set_preference, None)

        def run(shared_root):
            self.app._build_manager_window(shared_root)
            first = self.app.manager_window
            text = self._start_a_static_draft(first)
            combo, = self._settings_widgets(
                ttk.Combobox, lambda w: tx.ui_theme.APPEARANCE_LABELS["light"] in w.cget("values"))
            combo.set(tx.ui_theme.APPEARANCE_LABELS["light"])
            apply, = self._settings_widgets(
                BUTTONS, lambda w: w.cget("text") == "Aplicar aparência")
            # The draft asks Salvar · Descartar · Cancelar; Cancelar keeps everything.
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=None) as confirm:
                apply.invoke()
            self.assertEqual("Alterações não salvas", confirm.call_args.args[1])
            first.update()
            self.assertIs(self.app.manager_window, first)
            self.assertEqual("hello (rascunho)", text.get("1.0", "end-1c"))
            self.assertEqual(tx.ui_theme.preference(), "dark")
            self.assertNotIn("appearance", tx.load_settings(self.app.settings_file))
            self.assertEqual(combo.get(), tx.ui_theme.APPEARANCE_LABELS["dark"])

        self._on_gui(run)

    def test_focus_changes_the_drawn_face_of_every_focusable_control(self):
        """Regression (ST-07): focus was invisible on several controls.

        The combobox had no focus face, and the current nav item matched
        'selected' before 'focus', so it never drew the ring. This resolves
        the image ttk draws for a widget exactly as ttk does (the first state
        spec the widget is in) and reads the drawn pixels: at rest the focus
        margin above the face is clear; focused it holds the ring color.
        """
        self.addCleanup(tx.ui_theme.set_preference, None)

        def drawn(widget, element, ui):
            specs, default = ui_widgets._state(widget, ui).elements[element]
            for state, image in specs:
                if widget.instate(state.split()):
                    return image
            return default

        def ring_pixel(image, element):
            # A point on the straight top edge of the ring: the middle of a
            # face, of the square check box, and inside the switch track.
            if element.endswith(".face"):
                x = image.width() // 2
            elif element == "Fluent.Check.indicator":
                x = image.height() // 2
            else:
                x = image.height()
            return x, 0

        def run(shared_root):
            results = []
            for preference in ("dark", "light"):
                tx.ui_theme.set_preference(preference)
                window = tk.Toplevel(shared_root)
                window.withdraw()
                ui = tx.ui_theme.bind(window)
                tx.ui_theme.prepare_window(window, ui)
                window.configure(bg=ui.surface)
                cases = [("accent", ui_widgets.button(window, text="Save", variant="accent", ui=ui),
                          "Fluent.Accent.face")]
                if preference == "dark":
                    nav = ui_widgets.nav_item(window, "Texts", None, ui=ui)
                    ui_widgets.set_selected(nav, True, ui)
                    cases += [
                        ("combobox", ui_widgets.combobox(window, values=("a",), ui=ui),
                         "Fluent.Combo.face"),
                        ("selected nav", nav, "Fluent.Nav.face"),
                        ("checkbox", ui_widgets.checkbox(window, text="Favorite", ui=ui),
                         "Fluent.Check.indicator"),
                        ("switch", ui_widgets.switch(window, text="Terminator", ui=ui),
                         "Fluent.Switch.indicator"),
                    ]
                ring = tuple(channel >> 8 for channel in window.winfo_rgb(ui.focus_ring))
                for label, widget, element in cases:
                    rest = drawn(widget, element, ui)
                    widget.state(["focus"])
                    focused = drawn(widget, element, ui)
                    x, y = ring_pixel(focused, element)
                    results.append((
                        f"{preference} {label}",
                        rest is not focused,
                        bool(rest.transparency_get(x, y)),
                        bool(focused.transparency_get(x, y)),
                        tuple(focused.get(x, y)) == ring,
                    ))
                    widget.state(["!focus"])
                    self.assertIs(drawn(widget, element, ui), rest, label)
                window.destroy()
            return results

        for label, differs, rest_clear, focus_clear, ring_color in self._on_gui(run):
            with self.subTest(label):
                self.assertTrue(differs, "focus selects the same image as rest")
                self.assertTrue(rest_clear, "the focus margin is painted at rest")
                self.assertFalse(focus_clear, "no ring where the focus margin is")
                self.assertTrue(ring_color, "the ring is not the focus color")

    def test_compact_controls_and_rows_meet_the_density(self):
        """DS 2.7.1 Compact: 32 px faces and list rows at 100% scaling."""
        def run(shared_root):
            self.app._build_manager_window(shared_root)
            window = self.app.manager_window
            ui = tx.ui_theme.theme()
            margin = ui_widgets._state(window, ui).artist.margin
            probe = tk.Frame(window, bg=ui.surface)
            probe.grid(row=1, column=0)
            widgets = {
                "TButton": ui_widgets.button(probe, text="Novo", ui=ui),
                "Accent": ui_widgets.button(probe, text="Salvar", variant="accent", ui=ui),
                "TCombobox": ui_widgets.combobox(probe, values=("a",), ui=ui),
                "TEntry": ui_widgets.entry(probe, ui=ui),
            }
            # Never focusable, so its face reserves no focus margin.
            toolbar = ui_widgets.button(probe, text="B", variant="toolbar", ui=ui)
            for widget in (*widgets.values(), toolbar):
                widget.pack(side=tk.LEFT)
            window.update_idletasks()
            faces = {name: widget.winfo_reqheight() - 2 * margin
                     for name, widget in widgets.items()}
            rowheight = int(ttk.Style(window).lookup("Manager.Treeview", "rowheight"))
            return ui.px(32), faces, rowheight, toolbar.winfo_reqheight()

        compact, faces, rowheight, toolbar_height = self._on_gui(run)
        for name, height in faces.items():
            with self.subTest(name):
                self.assertGreaterEqual(height, compact)
        self.assertEqual(rowheight, compact)
        self.assertEqual(toolbar_height, compact)

    def _displayed_texts(self, window):
        """Every piece of text the manager shows: widgets, headings, rows, tabs, titles."""
        texts = [window.title()]
        for widget in _descendants(window):
            for option in ("text", "textvariable"):
                try:
                    value = widget.cget(option)
                except tk.TclError:
                    continue
                if option == "textvariable" and str(value):
                    value = widget.getvar(str(value))
                texts.append(str(value))
            if isinstance(widget, ttk.Combobox):
                texts.extend(widget.cget("values"))
            if isinstance(widget, ttk.Notebook):
                texts.extend(widget.tab(tab, "text") for tab in widget.tabs())
            if isinstance(widget, ttk.Treeview):
                for column in ("#0",) + tuple(widget.cget("columns")):
                    texts.append(widget.heading(column, "text"))
                for item in widget.get_children(""):
                    texts.extend(str(v) for v in widget.item(item, "values"))
            if isinstance(widget, tk.Listbox):
                texts.extend(widget.get(0, tk.END))
            if isinstance(widget, tk.Toplevel):
                texts.append(widget.title())
        return [text for text in texts if text]

    def test_english_manager_shows_no_portuguese(self):
        import i18n
        from i18n_en_us import EN_US
        from test_i18n import PORTUGUESE

        i18n.set_language("en-US")
        self.addCleanup(i18n.set_language, i18n.DEFAULT_LANGUAGE)

        def run(shared_root):
            self.app._build_manager_window(shared_root)
            window = self.app.manager_window
            self.app._open_notification_history(window)
            shared_root.update_idletasks()
            texts = self._displayed_texts(window)
            for child in window.winfo_children():
                if isinstance(child, tk.Toplevel):
                    texts += self._displayed_texts(child)
            # Deliberate Portuguese: the language picker names each language in
            # itself, and two action descriptions quote the Portuguese output.
            expected = set(i18n.LANGUAGES.values()) | {
                EN_US["Data e hora (DD/MM/AAAA às HH:MM)"],
                EN_US["Data por extenso (ex: segunda-feira, 02 de março de 2026)"],
            }
            english = set(EN_US.values())
            leftovers = sorted({
                text for text in texts
                if text not in expected and text not in english
                and ((text in EN_US and EN_US[text] != text) or PORTUGUESE.search(text))
            })
            self.assertEqual(leftovers, [])
            self.assertIn("Settings", texts)
            self.assertIn("Language", texts)

        self._on_gui(run)

    def test_applying_english_persists_and_rebuilds_the_manager_in_english(self):
        import i18n

        self.addCleanup(i18n.set_language, i18n.DEFAULT_LANGUAGE)

        def run(shared_root):
            self.app._build_manager_window(shared_root)
            first = self.app.manager_window
            combo, = self._settings_widgets(
                ttk.Combobox, lambda w: i18n.LANGUAGES["en-US"] in w.cget("values"))
            combo.set(i18n.LANGUAGES["en-US"])
            apply, = self._settings_widgets(
                BUTTONS, lambda w: w.cget("text") == "Aplicar idioma")
            with mock.patch.object(tx.ui_widgets, "confirm") as confirm, \
                    mock.patch.object(self.app, "refresh_tray_menu") as refresh_tray:
                apply.invoke()
            confirm.assert_not_called()
            first.update()
            rebuilt = self.app.manager_window
            self.assertIsNot(rebuilt, first)
            self.assertEqual(i18n.language(), "en-US")
            self.assertEqual(tx.load_settings(self.app.settings_file)["language"], "en-US")
            refresh_tray.assert_called_once_with()
            titles = _notebook_titles(rebuilt)
            self.assertIn("Settings", titles)
            self.assertEqual(
                self.app._manager_notebook.select(), str(self.app._manager_settings_tab))

        self._on_gui(run)

    def test_declining_the_language_reload_changes_nothing(self):
        import i18n

        self.addCleanup(i18n.set_language, i18n.DEFAULT_LANGUAGE)

        def run(shared_root):
            self.app._build_manager_window(shared_root)
            first = self.app.manager_window
            self._start_a_static_draft(first)
            combo, = self._settings_widgets(
                ttk.Combobox, lambda w: i18n.LANGUAGES["en-US"] in w.cget("values"))
            combo.set(i18n.LANGUAGES["en-US"])
            apply, = self._settings_widgets(
                BUTTONS, lambda w: w.cget("text") == "Aplicar idioma")
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=None):
                apply.invoke()
            first.update()
            self.assertIs(self.app.manager_window, first)
            self.assertEqual(i18n.language(), "pt-BR")
            self.assertNotIn("language", tx.load_settings(self.app.settings_file))
            self.assertEqual(combo.get(), i18n.LANGUAGES["pt-BR"])

        self._on_gui(run)

    def test_manager_window_is_tracked_and_reused(self):
        """Track/reuse logic does not require constructing the manager UI."""
        first = mock.Mock()
        first.winfo_exists.return_value = True
        first.title.return_value = f"{tx.PRODUCT_NAME} — Biblioteca"

        def build_fake_manager(_root):
            self.app.manager_window = first

        with mock.patch.object(
            self.app,
            "_build_manager_window",
            side_effect=build_fake_manager,
        ) as build_manager:
            self.app.gui.call(self.app._show_manager_window, timeout=30)
            self.assertIs(self.app.manager_window, first)
            self.assertEqual(
                first.title(),
                f"{tx.PRODUCT_NAME} — Biblioteca",
            )

            self.app.gui.call(self.app._show_manager_window, timeout=30)
            self.assertIs(
                self.app.manager_window,
                first,
                "second open should reuse the window",
            )

        build_manager.assert_called_once()
        first.deiconify.assert_called_once_with()
        first.lift.assert_called_once_with()
        first.focus_force.assert_called_once_with()
        self.app.manager_window = None













def _notebook_titles(window):
    notebooks = [
        widget for widget in _descendants(window)
        if isinstance(widget, ttk.Notebook)
    ]
    if not notebooks:
        return []
    notebook = notebooks[0]
    return [notebook.tab(tab_id, "text") for tab_id in notebook.tabs()]


def _form_windows(root):
    return [c for c in root.winfo_children()
            if isinstance(c, tk.Toplevel) and c.title() == "Preencher campos"]


def _find_form(root, label_text):
    for window in _form_windows(root):
        for widget in _descendants(window):
            if isinstance(widget, tk.Label) and label_text in str(widget.cget("text")):
                return window
    return None


@unittest.skipUnless(TK_AVAILABLE, TK_SKIP_REASON)
class ModalDialogSerializationTests(unittest.TestCase):
    """A second expansion dialog must be refused, never stacked.

    Stacked dialogs block their workers in nested event loops that unwind
    strictly LIFO: answering the older one first stranded its caller and lost
    its result. See Sniptype._run_modal_dialog.
    """

    def setUp(self):
        self.app = _make_app(tempfile.mkdtemp())
        for name, result in (
            ("capture_text_target", ("hwnd", 42)),
            ("restore_text_target", True),
        ):
            patcher = mock.patch.object(tx.platform_support, name, return_value=result)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app.gui.ensure_started()
        self.results = {}

    def tearDown(self):
        # Destroying a leftover form also releases a worker still waiting on it.
        _reset_shared_root(self.app)

    def _open_form(self, field):
        def worker():
            self.results[field] = self.app._show_form_dialog([field])

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread

    def _wait_for_form(self, label, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.app.gui.call(lambda root: _find_form(root, label) is not None, timeout=10):
                return
            time.sleep(0.05)
        self.fail(f"form dialog {label!r} never appeared")

    def _answer_form(self, label, value):
        def act(root):
            window = _find_form(root, label)
            if window is None:
                return False
            entry = [w for w in _descendants(window) if _is_text_entry(w)][0]
            entry.insert(0, value)
            window.event_generate("<Return>")
            return True

        self.assertTrue(self.app.gui.call(act, timeout=10), f"could not answer {label!r}")

    def test_second_dialog_is_refused_while_one_is_open(self):
        first = self._open_form("first")
        self._wait_for_form("First")

        second = self._open_form("second")
        second.join(10)
        self.assertFalse(second.is_alive(), "second dialog call should return immediately")
        self.assertIsNone(self.results["second"], "a refused dialog reports like a cancel")
        self.assertEqual(self.app.gui.call(lambda root: len(_form_windows(root)), timeout=10), 1)

        # The first dialog stays fully usable.
        self._answer_form("First", "one")
        first.join(10)
        self.assertEqual(self.results["first"], {"first": "one"})

    def test_dialog_lock_is_released_for_the_next_expansion(self):
        first = self._open_form("first")
        self._wait_for_form("First")
        self._answer_form("First", "one")
        first.join(10)

        later = self._open_form("later")
        self._wait_for_form("Later")
        self._answer_form("Later", "two")
        later.join(10)
        self.assertEqual(self.results["later"], {"later": "two"})


def _close_log_handlers(home):
    """Release the app's log file in a temporary home so it can be removed."""
    logger = logging.getLogger(LOGGER_NAME)
    prefix = os.path.normcase(os.path.abspath(home))
    for handler in list(logger.handlers):
        filename = getattr(handler, "baseFilename", None)
        if filename and os.path.normcase(os.path.abspath(filename)).startswith(prefix):
            logger.removeHandler(handler)
            handler.close()


def _watch_prompts(root, steps, timeout=20):
    """Answer, in order, the prompts the next action opens on the GUI thread.

    ``steps`` holds one ``act(window)`` per prompt. Each runs once its prompt
    is up and holds the grab, that is, once it waits for an answer; the
    returned list fills with what the steps return. Call it on the GUI thread
    just before the action that opens the prompts.
    """
    before = {str(w) for w in _descendants(root) if isinstance(w, tk.Toplevel)}
    pending = list(steps)
    answered = []
    used = set()
    deadline = time.monotonic() + timeout

    def poll():
        if not pending or time.monotonic() > deadline:
            return
        for window in _descendants(root):
            name = str(window)
            if not isinstance(window, tk.Toplevel) or name in before or name in used:
                continue
            if not window.winfo_exists() or str(window.grab_current()) != name:
                continue
            used.add(name)
            window.update()
            answered.append(pending.pop(0)(window))
            break
        root.after(25, poll)

    root.after(25, poll)
    return answered


def _buttons(window):
    return {str(w.cget("text")): w for w in _descendants(window) if isinstance(w, BUTTONS)}


def _labels(window):
    return [str(w.cget("text")) for w in _descendants(window) if isinstance(w, tk.Label)]


def _press(widget, sequence):
    """Deliver a key to ``widget`` with the keyboard focus on it."""
    widget.focus_force()
    widget.update()
    widget.event_generate(sequence)


def _click(label):
    def act(window):
        _buttons(window)[label].invoke()
        return True
    return act


@unittest.skipUnless(TK_AVAILABLE, TK_SKIP_REASON)
class DialogKitTests(unittest.TestCase):
    """The themed prompts on the shared root: answers, keys, focus and palette."""

    def tearDown(self):
        import i18n

        i18n.set_language(i18n.DEFAULT_LANGUAGE)

        def cleanup(root):
            for child in list(root.winfo_children()):
                child.destroy()
            gc.collect()

        _SHARED_GUI.call(cleanup, timeout=10)

    def _prompt(self, open_prompt, *steps):
        """Open a prompt over a visible window whose field has focus.

        Returns ``(answer, step results, focus went back to the field)``.
        """
        def run(root):
            owner = tk.Toplevel(root)
            tx.ui_theme.prepare_window(owner, tx.ui_theme.bind(owner))
            owner.geometry("420x320+60+60")
            opener = ui_widgets.entry(owner)
            opener.pack()
            owner.update()
            opener.focus_force()
            owner.update()
            answered = _watch_prompts(root, steps)
            answer = open_prompt(owner)
            owner.update()
            return answer, answered, owner.focus_get() is opener

        return _SHARED_GUI.call(run, timeout=60)

    @staticmethod
    def _confirm(owner, **options):
        return ui_widgets.confirm(owner, "Excluir tudo", "Corpo da pergunta.", "Excluir tudo", **options)

    def test_confirm_answers_with_the_choice_or_none(self):
        def press(sequence):
            def act(window):
                _press(window.focus_get(), sequence)
                return True
            return act

        def close_box(window):
            window.tk.call(window.protocol("WM_DELETE_WINDOW"))
            return True

        cases = (
            ("primary", _click("Excluir tudo"), ui_widgets.PRIMARY),
            ("extra", _click("Mesclar"), ui_widgets.EXTRA),
            ("Cancelar", _click("Cancelar"), None),
            ("Escape", press("<Escape>"), None),
            ("close box", close_box, None),
            ("Enter on the primary", press("<Return>"), ui_widgets.PRIMARY),
        )
        for name, act, expected in cases:
            with self.subTest(name):
                answer, answered, focus_back = self._prompt(
                    lambda owner: self._confirm(owner, extra="Mesclar"), act)
                self.assertEqual([True], answered)
                self.assertEqual(expected, answer)
                self.assertTrue(focus_back, "focus returns to the control that opened it")

    def test_a_destructive_confirm_starts_on_cancelar_so_enter_is_safe(self):
        def act(window):
            focused = str(window.focus_get().cget("text"))
            _press(window.focus_get(), "<Return>")
            return focused

        answer, answered, _focus = self._prompt(lambda owner: self._confirm(owner, danger=True), act)
        self.assertEqual(["Cancelar"], answered)
        self.assertIsNone(answer)

    def test_a_typed_word_keeps_the_primary_disabled_until_it_matches(self):
        def act(window):
            field = next(w for w in _descendants(window) if _is_text_entry(w))
            primary = _buttons(window)["Excluir tudo"]
            seen = [window.focus_get() is field, str(primary.cget("state"))]
            _press(field, "<Return>")
            seen.append(window.winfo_exists())
            field.insert(0, "excluir")
            seen.append(str(primary.cget("state")))
            primary.invoke()
            seen.append(window.winfo_exists())
            field.delete(0, tk.END)
            field.insert(0, "EXCLUIR")
            seen.append(str(primary.cget("state")))
            _press(field, "<Return>")
            return seen

        answer, answered, _focus = self._prompt(
            lambda owner: self._confirm(owner, danger=True, typed_word="EXCLUIR"), act)
        self.assertEqual([[True, "disabled", True, "disabled", True, "normal"]], answered)
        self.assertEqual(ui_widgets.PRIMARY, answer)

    def test_ask_text_validates_inline_and_answers_the_stripped_text(self):
        def act(window):
            field = next(w for w in _descendants(window) if _is_text_entry(w))
            _press(field, "<Return>")
            seen = [window.winfo_exists(), "Obrigatório." in _labels(window)]
            field.insert(0, "  novo  ")
            _press(field, "<Return>")
            return seen

        answer, answered, focus_back = self._prompt(
            lambda owner: ui_widgets.ask_text(
                owner, "Novo item", "Nome", validate=lambda value: None if value else "Obrigatório.",
                primary_label="Criar"),
            act)
        self.assertEqual([[True, True]], answered)
        self.assertEqual("novo", answer)
        self.assertTrue(focus_back)

    def test_ask_text_starts_with_the_initial_text_selected_and_escape_cancels(self):
        def act(window):
            field = next(w for w in _descendants(window) if _is_text_entry(w))
            seen = (window.focus_get() is field, field.get(), field.selection_present())
            _press(field, "<Escape>")
            return seen

        answer, answered, _focus = self._prompt(
            lambda owner: ui_widgets.ask_text(owner, "Renomear", "Novo nome", "xhi", primary_label="Renomear"),
            act)
        self.assertEqual([(True, "xhi", True)], answered)
        self.assertIsNone(answer)

    def test_an_alert_closes_on_enter_and_on_escape(self):
        for sequence in ("<Return>", "<Escape>"):
            with self.subTest(sequence):
                def act(window, sequence=sequence):
                    labels = list(_buttons(window))
                    _press(window.focus_get(), sequence)
                    return labels

                answer, answered, focus_back = self._prompt(
                    lambda owner: ui_widgets.alert(owner, "Falhou", "Algo falhou.", tone="danger"), act)
                self.assertEqual([["Fechar"]], answered)
                self.assertIsNone(answer)
                self.assertTrue(focus_back)

    def test_prompts_take_the_palette_and_language_of_their_window(self):
        import i18n

        def look(window):
            return window.cget("background"), sorted(_buttons(window))

        for language, buttons in (("pt-BR", ["Cancelar", "Excluir tudo"]), ("en-US", ["Cancel", "Excluir tudo"])):
            with self.subTest(language):
                i18n.set_language(language)
                tx.ui_theme.set_preference("dark")
                self.addCleanup(tx.ui_theme.set_preference, None)

                def look_and_cancel(window):
                    seen = look(window)
                    _press(window, "<Escape>")
                    return seen

                _answer, answered, _focus = self._prompt(self._confirm, look_and_cancel)
                background, labels = answered[0]
                self.assertEqual(tx.ui_theme.theme().surface.upper(), background.upper())
                self.assertEqual(buttons, labels)

    def test_a_receipt_action_expires_and_the_receipt_stays(self):
        def run(root):
            owner = tk.Toplevel(root)
            ui = tx.ui_theme.bind(owner)
            tx.ui_theme.prepare_window(owner, ui)
            receipt = ui_widgets.ReceiptLine(owner, "Dica")
            receipt.frame.pack(fill=tk.X)
            calls = []
            receipt.show("Excluído às 10:00 · xhi", "Desfazer", lambda: calls.append(1), seconds=0.05)
            offered = receipt.action.winfo_manager() == "pack"
            deadline = time.monotonic() + 2
            while receipt.action.winfo_manager() and time.monotonic() < deadline:
                owner.update()
                time.sleep(0.01)
            return offered, receipt.action.winfo_manager(), str(receipt.label.cget("text")), calls

        offered, manager, text, calls = _SHARED_GUI.call(run, timeout=10)
        self.assertTrue(offered)
        self.assertEqual("", manager, "Desfazer is withdrawn when it expires")
        self.assertEqual("Excluído às 10:00 · xhi", text)
        self.assertEqual([], calls)


@unittest.skipUnless(TK_AVAILABLE, TK_SKIP_REASON)
class DestructiveActionTests(unittest.TestCase):
    """Import, delete and undo through the real views, checked on disk."""

    def setUp(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        self.addCleanup(_close_log_handlers, home)
        self.app = _make_app(home)
        self.app.gui.ensure_started()

    def tearDown(self):
        _reset_shared_root(self.app)

    def _on_disk(self):
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            return json.load(handle)

    def _bytes(self):
        with open(self.app.snippets_file, "rb") as handle:
            return handle.read()

    def _persist(self, result):
        self.assertTrue(self.app._persist_manager_action(result))

    def _tab(self, root, build):
        window = tk.Toplevel(root)
        window.withdraw()
        tx.ui_theme.prepare_window(window, tx.ui_theme.bind(window))
        frame = tk.Frame(window)
        build(frame, window)
        window.update_idletasks()
        return window, frame

    def _import(self, document, *steps):
        source = os.path.join(self.app.data_dir, "import-source.json")
        with open(source, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

        def run(root):
            window, frame = self._tab(root, self.app._create_backups_tab)
            answered = _watch_prompts(root, steps)
            with mock.patch.object(tx.filedialog, "askopenfilename", return_value=source):
                _buttons(frame)["Importar…"].invoke()
            return answered

        return self.app.gui.call(run, timeout=60)

    def _seed_import_library(self):
        self.app.snippets["xold"] = "velho"
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        return {"xhi": "mudou", "xnew": "novo"}

    def test_cancelling_an_import_leaves_the_library_byte_identical(self):
        imported = self._seed_import_library()
        before = self._bytes()

        def read_and_cancel(window):
            text = "\n".join(_labels(window))
            # Left to right as drawn: the outcomes, then the safe choice.
            order = [label for label, button in sorted(
                _buttons(window).items(), key=lambda item: item[1].winfo_rootx())]
            _buttons(window)["Cancelar"].invoke()
            return text, order

        (body, order), = self._import(imported, read_and_cancel)
        self.assertEqual(before, self._bytes())
        self.assertIn("Novos: 1 · Sobrescritos: 1 · Removidos: 0", body)
        self.assertIn("Novos: 1 · Sobrescritos: 1 · Removidos: 1", body)
        self.assertEqual(["Mesclar", "Substituir tudo…", "Cancelar"], order)

    def test_replacing_everything_needs_the_typed_word(self):
        imported = self._seed_import_library()
        before = self._bytes()

        def refuse_without_the_word(window):
            field = next(w for w in _descendants(window) if _is_text_entry(w))
            primary = _buttons(window)["Substituir tudo"]
            _press(field, "<Return>")
            primary.invoke()
            seen = (str(primary.cget("state")), window.winfo_exists())
            _press(field, "<Escape>")
            return seen

        answered = self._import(imported, _click("Substituir tudo…"), refuse_without_the_word)
        self.assertEqual([True, ("disabled", True)], answered)
        self.assertEqual(before, self._bytes())

        def type_the_word(window):
            field = next(w for w in _descendants(window) if _is_text_entry(w))
            field.insert(0, "SUBSTITUIR")
            _press(field, "<Return>")
            return True

        # The import ends in a receipt on the page, not in a dialog to close.
        answered = self._import(imported, _click("Substituir tudo…"), type_the_word)
        self.assertEqual([True, True], answered)
        saved = self._on_disk()
        saved.pop("__sniptype__", None)
        self.assertEqual(imported, saved)

    def test_merging_keeps_the_library_and_lets_the_file_win(self):
        imported = self._seed_import_library()
        answered = self._import(imported, _click("Mesclar"))
        self.assertEqual([True], answered)
        saved = self._on_disk()
        self.assertEqual(("mudou", "novo", "velho"), (saved["xhi"], saved["xnew"], saved["xold"]))

    def _receipt(self, frame):
        label = next(
            w for w in _descendants(frame)
            if isinstance(w, tk.Label) and str(w.cget("text")).startswith(("Excluído", "Restaurado")))
        undo = _buttons(frame).get("Desfazer")
        return str(label.cget("text")), undo is not None and undo.winfo_manager() == "pack", undo

    def test_deleting_a_snippet_asks_nothing_and_desfazer_restores_it_on_disk(self):
        self._persist(manager_actions.toggle_favorite(
            self.app.snippets, self.app.library_metadata, "xhi", True))

        def run(root):
            window, frame = self._tab(root, self.app._create_static_snippets_tab)
            tree = next(w for w in _descendants(frame) if isinstance(w, ttk.Treeview))
            tree.selection_set("xhi")
            window.update()
            with mock.patch.object(tx.ui_widgets, "confirm") as confirm:
                _buttons(frame)["Excluir"].invoke()
            window.update()
            deleted = ("xhi" in self._on_disk(), confirm.called, self._receipt(frame)[:2])
            self._receipt(frame)[2].invoke()
            window.update()
            text, offered, _undo = self._receipt(frame)
            return deleted, (text, offered), tuple(tree.selection())

        deleted, restored, selection = self.app.gui.call(run, timeout=60)
        self.assertEqual(False, deleted[0])
        self.assertFalse(deleted[1], "a reversible delete does not ask")
        self.assertRegex(deleted[2][0], r"^Excluído às \d\d:\d\d · xhi$")
        self.assertTrue(deleted[2][1], "the receipt offers Desfazer")
        saved = self._on_disk()
        self.assertEqual("hello", saved["xhi"])
        self.assertTrue(saved["__sniptype__"]["items"]["static"]["xhi"]["favorite"])
        self.assertRegex(restored[0], r"^Restaurado às \d\d:\d\d · xhi$")
        self.assertFalse(restored[1])
        self.assertEqual(("xhi",), selection)

    def test_deleting_a_mapping_item_can_be_undone(self):
        self.app.snippets["_cpf_numbers"] = {"__prefix__": "cpf", "alice": "123"}
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        self._persist(manager_actions.toggle_mapping_favorite(
            self.app.snippets, self.app.library_metadata, "_cpf_numbers", "alice", True))

        def run(root):
            window, frame = self._tab(root, self.app._create_dynamic_mappings_tab)
            tree = next(w for w in _descendants(frame) if isinstance(w, ttk.Treeview) and "trigger" in w["columns"])
            tree.selection_set("alice")
            window.update()
            _buttons(frame)["Excluir"].invoke()
            window.update()
            gone = "alice" not in self._on_disk()["_cpf_numbers"]
            self._receipt(frame)[2].invoke()
            window.update()
            return gone, tuple(tree.selection())

        gone, selection = self.app.gui.call(run, timeout=60)
        self.assertTrue(gone)
        saved = self._on_disk()
        self.assertEqual("123", saved["_cpf_numbers"]["alice"])
        self.assertTrue(saved["__sniptype__"]["items"]["mappings"]["_cpf_numbers"]["alice"]["favorite"])
        self.assertEqual(("alice",), selection)

    def test_deleting_a_group_can_be_undone_with_its_members(self):
        self._persist(manager_actions.create_group(
            self.app.snippets, self.app.library_metadata, group_id="work", label="Trabalho"))
        self._persist(manager_actions.assign_item(
            self.app.snippets, self.app.library_metadata, "xhi", "work"))

        def run(root):
            window, frame = self._tab(root, self.app._create_static_snippets_tab)
            group_filter = [w for w in _descendants(frame) if isinstance(w, ttk.Combobox)][0]
            group_filter.set("Trabalho")
            group_filter.event_generate("<<ComboboxSelected>>")
            window.update()
            menu = next(w for w in _descendants(frame) if isinstance(w, tk.Menu))
            labels = [menu.entrycget(index, "label") for index in range(menu.index("end") + 1)]
            menu.invoke(labels.index("Excluir grupo"))
            window.update()
            after_delete = self._on_disk()["__sniptype__"]
            text, offered, undo = self._receipt(frame)
            undo.invoke()
            window.update()
            return labels, after_delete, (text, offered)

        labels, after_delete, receipt = self.app.gui.call(run, timeout=60)
        self.assertEqual(["Novo grupo…", "Editar grupo…", "Excluir grupo"], labels)
        self.assertNotIn("work", after_delete.get("groups", {}))
        self.assertNotIn("xhi", after_delete.get("items", {}).get("static", {}))
        self.assertRegex(receipt[0], r"^Excluído às \d\d:\d\d · Trabalho$")
        self.assertTrue(receipt[1])
        restored = self._on_disk()["__sniptype__"]
        self.assertEqual("Trabalho", restored["groups"]["work"]["label"])
        self.assertEqual("work", restored["items"]["static"]["xhi"]["group_id"])

    def test_deleting_a_mapping_type_requires_typing_its_name(self):
        self.app.snippets["_mail_codes"] = {"__prefix__": "mail", "team": "team@example.test"}
        self.assertTrue(self.app.save_snippets(self.app.snippets))

        def delete_type(*steps):
            def run(root):
                window, frame = self._tab(root, self.app._create_dynamic_mappings_tab)
                # Select the type the way navigation does, through its item.
                target = self.app._manager_target(SnippetRef("mapping", "team", "_mail_codes"))
                self.assertTrue(self.app._manager_tab_selectors["mapping"](target))
                window.update()
                answered = _watch_prompts(root, steps)
                _buttons(frame)["Excluir tipo"].invoke()
                return answered

            return self.app.gui.call(run, timeout=60)

        def wrong_name(window):
            field = next(w for w in _descendants(window) if _is_text_entry(w))
            field.insert(0, "mail")
            primary = _buttons(window)["Excluir tipo"]
            seen = (str(primary.cget("state")), "Para confirmar, digite MAIL" in _labels(window))
            _press(field, "<Return>")
            _press(field, "<Escape>")
            return seen

        self.assertEqual([("disabled", True)], delete_type(wrong_name))
        self.assertIn("_mail_codes", self._on_disk())

        def right_name(window):
            field = next(w for w in _descendants(window) if _is_text_entry(w))
            field.insert(0, "MAIL")
            _press(field, "<Return>")
            return True

        self.assertEqual([True], delete_type(right_name))
        self.assertNotIn("_mail_codes", self._on_disk())

    def test_duplicar_asks_for_the_new_trigger_inline(self):
        def run(root):
            window, frame = self._tab(root, self.app._create_static_snippets_tab)
            tree = next(w for w in _descendants(frame) if isinstance(w, ttk.Treeview))
            tree.selection_set("xhi")
            window.update()

            def answer(prompt):
                field = next(w for w in _descendants(prompt) if _is_text_entry(w))
                seen = [prompt.title(), sorted(_buttons(prompt))]
                _press(field, "<Return>")
                seen.append("Informe um trigger." in _labels(prompt))
                field.insert(0, "xhi")
                _press(field, "<Return>")
                seen.append("O trigger 'xhi' já existe." in _labels(prompt))
                field.delete(0, tk.END)
                field.insert(0, "xcopia")
                _press(field, "<Return>")
                return seen

            answered = _watch_prompts(root, [answer])
            _buttons(frame)["Duplicar"].invoke()
            return answered

        answered = self.app.gui.call(run, timeout=60)
        self.assertEqual(
            [["Duplicar snippet", ["Cancelar", "Duplicar"], True, True]], answered)
        self.assertEqual("hello", self._on_disk()["xcopia"])


@unittest.skipUnless(TK_AVAILABLE, TK_SKIP_REASON)
class WorkPreservationTests(unittest.TestCase):
    """Drafts survive row changes, refreshes, restores, closes and rebuilds."""

    def setUp(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        self.addCleanup(_close_log_handlers, home)
        self.app = _make_app(home)
        self.app.snippets["xola"] = "Olá, tudo bem?"
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        self.app.gui.ensure_started()

    def tearDown(self):
        _reset_shared_root(self.app)

    def _on_disk(self):
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _visible_window(root):
        # Shown, not withdrawn: Tk drops generated events (keys, virtual
        # events) aimed at an unmapped window.
        window = tk.Toplevel(root)
        tx.ui_theme.prepare_window(window, tx.ui_theme.bind(window))
        window.geometry("1180x760+40+40")
        return window

    def _static_tab(self, root):
        window = self._visible_window(root)
        frame = tk.Frame(window)
        frame.pack(fill=tk.BOTH, expand=True)
        self.app._create_static_snippets_tab(frame, window)
        window.update()
        return window, frame

    @staticmethod
    def _parts(frame):
        tree = next(w for w in _descendants(frame) if isinstance(w, ttk.Treeview) and "trigger" in w["columns"])
        text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
        trigger = [w for w in _descendants(frame) if _is_text_entry(w)][1]
        return tree, text, trigger

    @staticmethod
    def _shown(frame):
        """Labels on screen: an unmapped label (a hidden marker) does not count."""
        return [str(w.cget("text")) for w in _descendants(frame)
                if isinstance(w, tk.Label) and w.winfo_manager()
                and all(a.winfo_manager() for a in _ancestors(w, frame))]

    def test_selecting_another_row_asks_and_cancelar_keeps_the_draft(self):
        def run(root):
            window, frame = self._static_tab(root)
            tree, text, _trigger = self._parts(frame)
            tree.selection_set("xola")
            window.update()
            text.insert("end", " (rascunho)")
            window.update()
            seen = {"dirty_header": "• Não salvo" in self._shown(frame)}
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=None) as ask:
                tree.selection_set("xhi")
                window.update()
            seen["asked"] = ask.call_args.args[1:4] if ask.called else None
            seen["extra"] = ask.call_args.kwargs.get("extra") if ask.called else None
            seen["after_cancel"] = (tuple(tree.selection()), text.get("1.0", "end-1c"))
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=tx.ui_widgets.EXTRA):
                tree.selection_set("xhi")
                window.update()
            seen["after_discard"] = (tuple(tree.selection()), text.get("1.0", "end-1c"))
            seen["clean_header"] = "• Não salvo" in self._shown(frame)
            return seen

        seen = self.app.gui.call(run, timeout=60)
        self.assertTrue(seen["dirty_header"])
        self.assertEqual(
            ("Alterações não salvas",
             "O snippet xola tem alterações não salvas.\n\n"
             "Salvar grava as alterações e continua; Descartar continua sem elas.",
             "Salvar"),
            seen["asked"])
        self.assertEqual("Descartar", seen["extra"])
        self.assertEqual((("xola",), "Olá, tudo bem? (rascunho)"), seen["after_cancel"])
        self.assertEqual((("xhi",), "hello"), seen["after_discard"])
        self.assertFalse(seen["clean_header"])
        self.assertEqual("Olá, tudo bem?", self._on_disk()["xola"], "Descartar writes nothing")

    def test_salvar_in_the_prompt_saves_then_opens_the_other_row(self):
        def run(root):
            window, frame = self._static_tab(root)
            tree, text, _trigger = self._parts(frame)
            tree.selection_set("xola")
            window.update()
            text.insert("end", "!")
            window.update()
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=tx.ui_widgets.PRIMARY):
                tree.selection_set("xhi")
                window.update()
            return tuple(tree.selection()), text.get("1.0", "end-1c")

        self.assertEqual((("xhi",), "hello"), self.app.gui.call(run, timeout=60))
        self.assertEqual("Olá, tudo bem?!", self._on_disk()["xola"])

    def test_novo_and_editar_ultimo_ask_before_dropping_a_draft(self):
        def run(root):
            window, frame = self._static_tab(root)
            tree, text, trigger = self._parts(frame)
            tree.selection_set("xola")
            window.update()
            text.insert("end", "!")
            window.update()
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=None) as ask:
                _buttons(frame)["Novo"].invoke()
                kept_after_new = (trigger.get(), text.get("1.0", "end-1c"))
                # Editar último goes through the tab selector.
                handled = self.app._select_manager_target(SnippetRef("static", "xhi"))
                window.update()
            return ask.call_count, kept_after_new, handled, trigger.get(), tuple(tree.selection())

        asked, kept, handled, trigger, selection = self.app.gui.call(run, timeout=60)
        self.assertEqual(2, asked)
        self.assertEqual(("xola", "Olá, tudo bem?!"), kept)
        self.assertTrue(handled, "a kept draft is not reported as a missing item")
        self.assertEqual(("xola", ("xola",)), (trigger, selection))

    def test_a_clean_editor_follows_a_restore(self):
        backup = self._backup_with(xola="Restaurado do backup")

        def run(root):
            window, frame = self._static_tab(root)
            tree, text, _trigger = self._parts(frame)
            tree.selection_set("xola")
            window.update()
            ok, error = self.app.restore_backup(backup)
            self.assertTrue(ok, error)
            self.app._refresh_manager_lists()
            window.update()
            return text.get("1.0", "end-1c"), [t for t in self._shown(frame) if t.startswith("A biblioteca")]

        value, notices = self.app.gui.call(run, timeout=60)
        self.assertEqual("Restaurado do backup", value)
        self.assertEqual([], notices)

    def test_a_dirty_editor_keeps_its_draft_over_a_restore_and_says_so(self):
        backup = self._backup_with(xola="Restaurado do backup")

        def run(root):
            window, frame = self._static_tab(root)
            tree, text, _trigger = self._parts(frame)
            tree.selection_set("xola")
            window.update()
            text.insert("end", " (rascunho)")
            window.update()
            ok, error = self.app.restore_backup(backup)
            self.assertTrue(ok, error)
            self.app._refresh_manager_lists()
            window.update()
            seen = {
                "draft": text.get("1.0", "end-1c"),
                "notice": [t for t in self._shown(frame) if t.startswith("A biblioteca")],
                "actions": [label for label in ("Usar a versão nova", "Manter rascunho")
                            if label in _buttons(frame)],
            }
            _buttons(frame)["Manter rascunho"].invoke()
            window.update()
            seen["after_keep"] = (
                [t for t in self._shown(frame) if t.startswith("A biblioteca")],
                "• Não salvo" in self._shown(frame),
            )
            # The kept draft is saved over the restored value only on purpose.
            _press(text, "<Control-s>")
            window.update()
            seen["saved"] = "• Não salvo" in self._shown(frame)
            return seen

        seen = self.app.gui.call(run, timeout=60)
        self.assertEqual("Olá, tudo bem? (rascunho)", seen["draft"])
        self.assertEqual(["A biblioteca mudou: xola tem uma versão salva mais nova."], seen["notice"])
        self.assertEqual(["Usar a versão nova", "Manter rascunho"], seen["actions"])
        self.assertEqual(([], True), seen["after_keep"])
        self.assertFalse(seen["saved"])
        self.assertEqual("Olá, tudo bem? (rascunho)", self._on_disk()["xola"])

    def test_usar_a_versao_nova_drops_the_draft_for_the_library(self):
        backup = self._backup_with(xola="Restaurado do backup")

        def run(root):
            window, frame = self._static_tab(root)
            tree, text, _trigger = self._parts(frame)
            tree.selection_set("xola")
            window.update()
            text.insert("end", " (rascunho)")
            window.update()
            self.assertTrue(self.app.restore_backup(backup)[0])
            self.app._refresh_manager_lists()
            window.update()
            _buttons(frame)["Usar a versão nova"].invoke()
            window.update()
            return text.get("1.0", "end-1c"), "• Não salvo" in self._shown(frame)

        self.assertEqual(("Restaurado do backup", False), self.app.gui.call(run, timeout=60))

    def _backup_with(self, **values):
        document = dict(self._on_disk())
        document.update(values)
        path = os.path.join(self.app.data_dir, "restore-source.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        return path

    def test_restaurar_with_a_draft_asks_and_cancelar_restores_nothing(self):
        def run(root):
            self.app._build_manager_window(root)
            window = self.app.manager_window
            notebook = self.app._manager_notebook
            static_tab = notebook.nametowidget(notebook.tabs()[0])
            tree, text, _trigger = self._parts(static_tab)
            tree.selection_set("xola")
            window.update()
            text.insert("end", "!")
            window.update()
            before = self._on_disk()
            backups = notebook.nametowidget(notebook.tabs()[3])
            backup_tree = next(w for w in _descendants(backups) if isinstance(w, ttk.Treeview))
            backup_tree.selection_set(backup_tree.get_children()[0])
            # Restaurar backup? yes. The draft? Cancelar.
            with mock.patch.object(
                    tx.ui_widgets, "confirm", side_effect=[tx.ui_widgets.PRIMARY, None]) as ask:
                _buttons(backups)["Restaurar"].invoke()
            window.update()
            return before, [call.args[1] for call in ask.call_args_list], text.get("1.0", "end-1c")

        before, asked, draft = self.app.gui.call(run, timeout=60)
        self.assertEqual(["Restaurar backup", "Alterações não salvas"], asked)
        self.assertEqual(before, self._on_disk())
        self.assertEqual("Olá, tudo bem?!", draft)

    def test_ctrl_s_keeps_the_selection_and_the_scroll(self):
        for index in range(40):
            self.app.snippets[f"note{index:02d}"] = f"Synthetic note {index}"
        self.assertTrue(self.app.save_snippets(self.app.snippets))

        def run(root):
            self.app._build_manager_window(root)
            window = self.app.manager_window
            window.geometry("1280x800")
            window.update()
            notebook = self.app._manager_notebook
            tab = notebook.nametowidget(notebook.tabs()[0])
            tree, text, _trigger = self._parts(tab)
            save = _buttons(tab)["Salvar"]
            tree.see("note30")
            tree.selection_set("note30")
            window.update()
            seen = {"clean": str(save.cget("state"))}
            yview = tree.yview()
            text.insert("end", " editada")
            window.update()
            seen["dirty"] = str(save.cget("state"))
            seen["title_dirty"] = window.title()
            _press(text, "<Control-s>")
            window.update()
            seen["after"] = (tuple(tree.selection()), tree.yview() == yview, str(save.cget("state")))
            seen["title_clean"] = window.title()
            return seen

        seen = self.app.gui.call(run, timeout=60)
        self.assertEqual("disabled", seen["clean"], "Salvar waits for a change")
        self.assertEqual("normal", seen["dirty"])
        self.assertTrue(seen["title_dirty"].startswith("• "), seen["title_dirty"])
        self.assertEqual((("note30",), True, "disabled"), seen["after"])
        self.assertFalse(seen["title_clean"].startswith("• "))
        self.assertEqual("Synthetic note 30 editada", self._on_disk()["note30"])

    def test_closing_with_a_draft_asks_first(self):
        def run(root):
            self.app._build_manager_window(root)
            window = self.app.manager_window
            notebook = self.app._manager_notebook
            tab = notebook.nametowidget(notebook.tabs()[0])
            tree, text, _trigger = self._parts(tab)
            tree.selection_set("xola")
            window.update()
            text.insert("end", "!")
            window.update()
            close = window.protocol("WM_DELETE_WINDOW")
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=None):
                window.tk.call(close)
            kept = window.winfo_exists() and self.app.manager_window is window
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=tx.ui_widgets.EXTRA):
                window.tk.call(close)
            return kept, window.winfo_exists(), self.app._manager_appearance_poll

        kept, exists, poll = self.app.gui.call(run, timeout=60)
        self.assertTrue(kept, "Cancelar keeps the window open")
        self.assertFalse(exists, "Descartar closes it")
        self.assertIsNone(poll, "the System appearance check stops with the window")
        self.assertEqual("Olá, tudo bem?", self._on_disk()["xola"])

    def test_the_editor_names_its_target_and_offers_only_what_applies(self):
        self.app.snippets["sig"] = "Atenciosamente"
        self.assertTrue(self.app.save_snippets(self.app.snippets))
        self.assertTrue(self.app._persist_manager_action(manager_actions.create_group(
            self.app.snippets, self.app.library_metadata,
            group_id="mail", label="Correio", prefix="as")))
        self.assertTrue(self.app._persist_manager_action(manager_actions.assign_item(
            self.app.snippets, self.app.library_metadata, "sig", "mail")))

        def states(frame):
            buttons = _buttons(frame)
            return {label: str(buttons[label].cget("state"))
                    for label in ("Salvar", "Duplicar", "Renomear", "Excluir", "Prévia")}

        def run(root):
            window, frame = self._static_tab(root)
            tree, text, trigger = self._parts(frame)
            search = [w for w in _descendants(frame) if _is_text_entry(w)][0]
            seen = {"empty": (states(frame), self._shown(frame))}
            tree.selection_set("sig")
            window.update()
            seen["open"] = (states(frame), self._shown(frame))
            search.insert(0, "nada-casa")
            window.update()
            seen["hidden"] = (self._shown(frame), _buttons(frame)["Mostrar na lista"].winfo_manager() == "grid")
            _buttons(frame)["Mostrar na lista"].invoke()
            window.update()
            seen["revealed"] = (search.get(), tuple(tree.selection()))
            _buttons(frame)["Novo"].invoke()
            window.update()
            seen["new"] = (states(frame), self._shown(frame), tuple(tree.selection()))
            trigger.insert(0, "xnovo")
            window.update()
            seen["typed"] = (states(frame), self._shown(frame))
            return seen

        seen = self.app.gui.call(run, timeout=60)
        disabled = {"Salvar": "disabled", "Duplicar": "disabled", "Renomear": "disabled",
                    "Excluir": "disabled", "Prévia": "disabled"}
        empty_states, empty_labels = seen["empty"]
        self.assertEqual(disabled, empty_states)
        self.assertIn("Nenhum snippet aberto", empty_labels)
        self.assertIn("Selecione um snippet na lista ou clique em Novo.", empty_labels)
        open_states, open_labels = seen["open"]
        self.assertEqual({**disabled, "Duplicar": "normal", "Renomear": "normal",
                          "Excluir": "normal", "Prévia": "normal"}, open_states)
        self.assertIn("Editando sig", open_labels)
        self.assertIn("Efetivo: assig", open_labels, "Efetivo comes from the editor")
        hidden_labels, reveal_mapped = seen["hidden"]
        self.assertIn("Oculto pelo filtro atual.", hidden_labels)
        self.assertIn("Editando sig", hidden_labels, "the editor keeps its target")
        self.assertTrue(reveal_mapped)
        self.assertEqual(("", ("sig",)), seen["revealed"])
        new_states, new_labels, new_selection = seen["new"]
        self.assertEqual(disabled, new_states)
        self.assertIn("Novo snippet", new_labels)
        self.assertEqual((), new_selection, "no row claims to be the new draft")
        typed_states, typed_labels = seen["typed"]
        self.assertEqual("disabled", typed_states["Salvar"], "a draft with no value cannot be saved")
        self.assertIn("• Não salvo", typed_labels)
        self.assertIn("Informe um valor para o snippet.", typed_labels)
        self.assertIn("Efetivo: xnovo", typed_labels)

    def test_renaming_keeps_the_draft_on_the_renamed_snippet(self):
        def run(root):
            window, frame = self._static_tab(root)
            tree, text, trigger = self._parts(frame)
            tree.selection_set("xola")
            window.update()
            text.insert("end", " (rascunho)")
            window.update()
            with mock.patch.object(tx.ui_widgets, "ask_text", return_value="xoi"):
                _buttons(frame)["Renomear"].invoke()
            window.update()
            return (trigger.get(), text.get("1.0", "end-1c"), tuple(tree.selection()),
                    [t for t in self._shown(frame) if t.startswith(("Editando", "A biblioteca", "•"))])

        trigger, draft, selection, labels = self.app.gui.call(run, timeout=60)
        self.assertEqual("xoi", trigger)
        self.assertEqual("Olá, tudo bem? (rascunho)", draft)
        self.assertEqual(("xoi",), selection)
        self.assertEqual(["Editando xoi", "• Não salvo"], labels)
        saved = self._on_disk()
        self.assertEqual("Olá, tudo bem?", saved["xoi"], "the rename writes the saved text")
        self.assertNotIn("xola", saved)

    def test_a_failed_save_keeps_the_draft_and_the_library(self):
        def run(root):
            window, frame = self._static_tab(root)
            tree, text, _trigger = self._parts(frame)
            tree.selection_set("xola")
            window.update()
            text.insert("end", "!")
            window.update()
            with mock.patch.object(self.app, "save_snippets", return_value=False), \
                    mock.patch.object(tx.ui_widgets, "alert") as alert:
                _buttons(frame)["Salvar"].invoke()
            window.update()
            return (alert.call_args.kwargs.get("tone"), self.app.snippets["xola"],
                    str(_buttons(frame)["Salvar"].cget("state")), "• Não salvo" in self._shown(frame))

        tone, in_memory, save_state, dirty = self.app.gui.call(run, timeout=60)
        # Regression: memory kept the unsaved value, so the editor looked saved.
        self.assertEqual("danger", tone)
        self.assertEqual("Olá, tudo bem?", in_memory)
        self.assertEqual("normal", save_state, "Salvar stays available to retry")
        self.assertTrue(dirty)

    def _save_notes(self, frame):
        """What the header says Salvar will do with a draft whose name differs."""
        return [t for t in self._shown(frame) if t.startswith("Salvar ")]

    def test_a_trigger_that_names_another_snippet_asks_before_replacing_it(self):
        # Regression: typing a saved trigger over the open snippet and pressing
        # Salvar wrote over that other snippet without a word, while the header
        # still named the snippet that was open.
        def run(root):
            window, frame = self._static_tab(root)
            tree, text, trigger = self._parts(frame)
            tree.selection_set("xola")
            window.update()
            trigger.delete(0, tk.END)
            trigger.insert(0, "xhi")
            window.update()
            seen = {"note": self._save_notes(frame),
                    "header": [t for t in self._shown(frame) if t.startswith("Editando")]}
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=None) as ask:
                _buttons(frame)["Salvar"].invoke()
            window.update()
            seen["asked"] = (ask.call_args.args[1:4], ask.call_args.kwargs.get("danger"))
            seen["cancelled"] = (self._on_disk()["xhi"], trigger.get(),
                                 "• Não salvo" in self._shown(frame))
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=tx.ui_widgets.PRIMARY):
                _buttons(frame)["Salvar"].invoke()
            window.update()
            seen["confirmed"] = (self._on_disk(), "• Não salvo" in self._shown(frame),
                                 [t for t in self._shown(frame) if t.startswith("Editando")])
            return seen

        seen = self.app.gui.call(run, timeout=60)
        self.assertEqual(["Salvar substitui xhi."], seen["note"])
        self.assertEqual(["Editando xola"], seen["header"])
        self.assertEqual(
            (("Substituir snippet",
              "O snippet xhi já existe. Salvar troca o texto dele pelo que está no editor.",
              "Substituir"), True),
            seen["asked"])
        self.assertEqual(("hello", "xhi", True), seen["cancelled"], "Cancelar keeps the draft")
        confirmed, dirty, header = seen["confirmed"]
        self.assertEqual("Olá, tudo bem?", confirmed["xhi"])
        self.assertEqual("Olá, tudo bem?", confirmed["xola"], "the snippet that was open stays saved")
        self.assertFalse(dirty)
        self.assertEqual(["Editando xhi"], header)

    def test_a_new_trigger_says_it_creates_and_keeps_the_open_snippet(self):
        def run(root):
            window, frame = self._static_tab(root)
            tree, text, trigger = self._parts(frame)
            tree.selection_set("xola")
            window.update()
            trigger.delete(0, tk.END)
            trigger.insert(0, "xnova")
            window.update()
            note = self._save_notes(frame)
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=tx.ui_widgets.PRIMARY) as ask:
                _buttons(frame)["Salvar"].invoke()
            window.update()
            return note, [call.args[1] for call in ask.call_args_list]

        note, asked = self.app.gui.call(run, timeout=60)
        self.assertEqual(["Salvar cria xnova; xola continua salvo."], note)
        self.assertNotIn("Substituir snippet", asked, "a free name replaces nothing")
        saved = self._on_disk()
        self.assertEqual(("Olá, tudo bem?", "Olá, tudo bem?"), (saved["xola"], saved["xnova"]))

    def test_a_new_draft_over_a_saved_trigger_asks_too(self):
        def run(root):
            window, frame = self._static_tab(root)
            _tree, text, trigger = self._parts(frame)
            _buttons(frame)["Novo"].invoke()
            window.update()
            trigger.insert(0, "xhi")
            text.insert("end", "outro texto")
            window.update()
            note = self._save_notes(frame)
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=None) as ask:
                _buttons(frame)["Salvar"].invoke()
            return note, ask.call_count, self._on_disk()["xhi"]

        note, asked, on_disk = self.app.gui.call(run, timeout=60)
        self.assertEqual(["Salvar substitui xhi."], note)
        self.assertEqual(1, asked)
        self.assertEqual("hello", on_disk)

    def test_a_deleted_open_snippet_is_gone_not_hidden_by_the_filter(self):
        # Regression: the library dropping the open snippet under a draft
        # showed "Oculto pelo filtro atual." and a dead Mostrar na lista above
        # the "does not exist any more" bar.
        def run(root):
            window, frame = self._static_tab(root)
            tree, text, _trigger = self._parts(frame)
            tree.selection_set("xola")
            window.update()
            text.insert("end", " (rascunho)")
            window.update()
            del self.app.snippets["xola"]
            self.assertTrue(self.app.save_snippets(self.app.snippets))
            self.app._refresh_manager_lists()
            window.update()
            return self._shown(frame), _buttons(frame)["Mostrar na lista"].winfo_manager()

        shown, reveal = self.app.gui.call(run, timeout=60)
        self.assertIn("A biblioteca mudou: xola não existe mais.", shown)
        self.assertNotIn("Oculto pelo filtro atual.", shown)
        self.assertEqual("", reveal, "there is nothing in the list to show")

    def test_a_mapping_identifier_that_names_another_item_asks_before_replacing_it(self):
        self.app.snippets["_cpf_numbers"] = {"__prefix__": "cpf", "alice": "1", "bruno": "2"}
        self.assertTrue(self.app.save_snippets(self.app.snippets))

        def run(root):
            window = self._visible_window(root)
            frame = tk.Frame(window)
            frame.pack(fill=tk.BOTH, expand=True)
            self.app._create_dynamic_mappings_tab(frame, window)
            window.update()
            tree, _text, name = self._parts(frame)
            types = next(w for w in _descendants(frame) if isinstance(w, ttk.Treeview) and not w["columns"])
            types.selection_set("_cpf_numbers")
            types.event_generate("<<TreeviewSelect>>")
            window.update()
            tree.selection_set("alice")
            window.update()
            name.delete(0, tk.END)
            name.insert(0, "bruno")
            window.update()
            seen = {"note": self._save_notes(frame)}
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=None) as ask:
                _buttons(frame)["Salvar"].invoke()
            window.update()
            seen["asked"] = (ask.call_args.args[1:4], ask.call_args.kwargs.get("danger"))
            seen["cancelled"] = (self._on_disk()["_cpf_numbers"]["bruno"], name.get(),
                                 "• Não salvo" in self._shown(frame))
            name.delete(0, tk.END)
            name.insert(0, "carla")
            window.update()
            seen["free_note"] = self._save_notes(frame)
            with mock.patch.object(tx.ui_widgets, "confirm") as free_ask:
                _buttons(frame)["Salvar"].invoke()
            window.update()
            seen["free_asked"] = free_ask.called
            name.delete(0, tk.END)
            name.insert(0, "bruno")
            window.update()
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=tx.ui_widgets.PRIMARY):
                _buttons(frame)["Salvar"].invoke()
            window.update()
            seen["confirmed"] = self._on_disk()["_cpf_numbers"]
            return seen

        seen = self.app.gui.call(run, timeout=60)
        self.assertEqual(["Salvar substitui bruno."], seen["note"])
        self.assertEqual(
            (("Substituir item",
              "O item bruno de CPF já existe. Salvar troca o texto dele pelo que está no editor.",
              "Substituir"), True),
            seen["asked"])
        self.assertEqual(("2", "bruno", True), seen["cancelled"], "Cancelar keeps the draft")
        self.assertEqual(["Salvar cria carla; alice continua salvo."], seen["free_note"])
        self.assertFalse(seen["free_asked"], "a free identifier replaces nothing")
        self.assertEqual({"__prefix__": "cpf", "alice": "1", "bruno": "1", "carla": "1"},
                         seen["confirmed"])

    def test_a_deleted_open_mapping_item_is_gone_not_hidden_by_the_filter(self):
        self.app.snippets["_cpf_numbers"] = {"__prefix__": "cpf", "alice": "1", "bruno": "2"}
        self.assertTrue(self.app.save_snippets(self.app.snippets))

        def run(root):
            window = self._visible_window(root)
            frame = tk.Frame(window)
            frame.pack(fill=tk.BOTH, expand=True)
            self.app._create_dynamic_mappings_tab(frame, window)
            window.update()
            tree, text, _name = self._parts(frame)
            types = next(w for w in _descendants(frame) if isinstance(w, ttk.Treeview) and not w["columns"])
            types.selection_set("_cpf_numbers")
            types.event_generate("<<TreeviewSelect>>")
            window.update()
            tree.selection_set("alice")
            window.update()
            text.insert("end", "23")
            window.update()
            del self.app.snippets["_cpf_numbers"]["alice"]
            self.assertTrue(self.app.save_snippets(self.app.snippets))
            self.app._refresh_manager_lists()
            window.update()
            return self._shown(frame), _buttons(frame)["Mostrar na lista"].winfo_manager()

        shown, reveal = self.app.gui.call(run, timeout=60)
        self.assertIn("A biblioteca mudou: alice não existe mais.", shown)
        self.assertNotIn("Oculto pelo filtro atual.", shown)
        self.assertEqual("", reveal, "there is nothing in the list to show")

    def test_a_mapping_draft_guards_rows_and_type_changes(self):
        self.app.snippets["_cpf_numbers"] = {"__prefix__": "cpf", "alice": "1", "bruno": "2"}
        self.assertTrue(self.app.save_snippets(self.app.snippets))

        def run(root):
            window = self._visible_window(root)
            frame = tk.Frame(window)
            frame.pack(fill=tk.BOTH, expand=True)
            self.app._create_dynamic_mappings_tab(frame, window)
            window.update()
            tree, text, _name = self._parts(frame)
            types = next(w for w in _descendants(frame) if isinstance(w, ttk.Treeview) and not w["columns"])
            types.selection_set("_cpf_numbers")
            types.event_generate("<<TreeviewSelect>>")
            window.update()
            tree.selection_set("alice")
            window.update()
            text.insert("end", "23")
            window.update()
            seen = {"header": [t for t in self._shown(frame) if t.startswith("Editando")]}
            with mock.patch.object(tx.ui_widgets, "confirm", return_value=None) as ask:
                tree.selection_set("bruno")
                window.update()
                seen["row"] = (tuple(tree.selection()), text.get("1.0", "end-1c"))
                types.selection_set("_cnpj_numbers")
                types.event_generate("<<TreeviewSelect>>")
                window.update()
                seen["type"] = (types.item(types.selection()[0], "text"), text.get("1.0", "end-1c"))
            seen["asked"] = [call.args[2] for call in ask.call_args_list]
            return seen

        seen = self.app.gui.call(run, timeout=60)
        self.assertEqual(["Editando alice em CPF"], seen["header"])
        self.assertEqual((("alice",), "123"), seen["row"])
        self.assertEqual(("CPF", "123"), seen["type"])
        self.assertEqual(2, len(seen["asked"]))
        self.assertTrue(seen["asked"][0].startswith("O item alice de CPF tem alterações não salvas."))

    @unittest.skipUnless(tx.IS_WINDOWS, "System follows the Windows app theme")
    def test_system_appearance_follows_windows_unless_a_draft_holds_it(self):
        self.addCleanup(tx.ui_theme.set_preference, None)
        tx.ui_theme.set_preference("system")
        apps_use_light = {"value": False}
        patcher = mock.patch.object(
            tx.ui_theme, "_windows_apps_use_light_theme", side_effect=lambda: apps_use_light["value"])
        patcher.start()
        self.addCleanup(patcher.stop)

        def run(root):
            self.app._build_manager_window(root)
            first = self.app.manager_window
            first.update()
            seen = {"first": first.theme_kind}
            self.app._check_system_appearance(first)
            seen["unchanged"] = self.app.manager_window is first
            # Windows switches apps to light while Textos holds a draft.
            apps_use_light["value"] = True
            notebook = self.app._manager_notebook
            tab = notebook.nametowidget(notebook.tabs()[0])
            tree, text, _trigger = self._parts(tab)
            tree.selection_set("xola")
            first.update()
            text.insert("end", "!")
            first.update()
            self.app._check_system_appearance(first)
            first.update()
            seen["held"] = (self.app.manager_window is first,
                            [t for t in self._shown(tab) if t.startswith("O tema do Windows")])
            _press(text, "<Control-s>")
            first.update()
            notebook.select(notebook.tabs()[1])
            self.app._check_system_appearance(first)
            rebuilt = self.app.manager_window
            rebuilt.update()
            rebuilt_notebook = self.app._manager_notebook
            seen["rebuilt"] = (
                rebuilt is not first, first.winfo_exists(), rebuilt.theme_kind,
                ttk.Style(rebuilt).theme_use(),
                rebuilt_notebook.index(rebuilt_notebook.select()),
            )
            return seen

        seen = self.app.gui.call(run, timeout=60)
        self.assertEqual("dark", seen["first"])
        self.assertTrue(seen["unchanged"])
        self.assertEqual(
            (True, ["O tema do Windows mudou. O gerenciador troca de tema quando este rascunho "
                    "for salvo ou descartado."]),
            seen["held"])
        self.assertEqual((True, False, "windows", "sniptype-fluent-light", 1), seen["rebuilt"])
        self.assertEqual("Olá, tudo bem?!", self._on_disk()["xola"])


def _ancestors(widget, stop):
    while widget is not stop and widget is not None:
        widget = widget.master
        if widget is not None and widget is not stop:
            yield widget


class _FakeTrayIcon:
    """Records the toasts and the tray redraws a real pystray icon would show."""

    visible = True
    icon = None
    title = None

    def __init__(self):
        self.toasts = []

    def notify(self, text, title=None):
        self.toasts.append(text)

    def update_menu(self):
        pass


@unittest.skipUnless(TK_AVAILABLE, TK_SKIP_REASON)
class StatusAndAttentionTests(unittest.TestCase):
    """The InfoBar, the sidebar signal, receipts in the window and the dated history."""

    def setUp(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        self.addCleanup(_close_log_handlers, home)
        self.app = _make_app(home)
        self.tray = _FakeTrayIcon()
        self.app.icon = self.tray
        self.app.gui.ensure_started()

    def tearDown(self):
        _reset_shared_root(self.app)

    def _manager(self, root):
        """The real manager, mapped, as the person sees it."""
        self.app._build_manager_window(root)
        window = self.app.manager_window
        window.geometry("1180x760+40+40")
        window.deiconify()
        window.update()
        return window

    @staticmethod
    def _bar(app):
        """``(texts, buttons, bands)`` of the InfoBar as drawn, or None when hidden."""
        bar = app._manager_health
        if not bar.frame.winfo_manager():
            return None
        bands = [w for w in bar.frame.winfo_children()
                 if isinstance(w, tk.Frame) and str(w.cget("bg")) != str(bar.frame.cget("bg"))
                 and w.winfo_height() > 2]
        return _labels(bar.frame), _buttons(bar.frame), bands

    def _on_gui(self, func):
        return self.app.gui.call(func, timeout=60)

    def test_a_healthy_manager_is_quiet_and_has_no_tagline(self):
        def run(root):
            window = self._manager(root)
            ui = tx.ui_theme.theme()
            status = self.app._manager_status_label
            return {
                "bar": self._bar(self.app),
                "status": self.app._manager_status_var.get(),
                "status_fg": str(status.cget("fg")),
                "dot": bool(str(self.app._manager_status_icon.cget("image"))),
                "muted": ui.text_muted,
                "labels": _labels(window),
                "button": str(self.app._manager_toggle_button.cget("text")),
            }

        seen = self._on_gui(run)
        self.assertIsNone(seen["bar"], "a healthy app has nothing to say")
        self.assertEqual("Expansão ativa", seen["status"])
        self.assertEqual(seen["muted"], seen["status_fg"])
        self.assertTrue(seen["dot"], "the quiet state is a drawn dot")
        self.assertNotIn("Sua biblioteca de textos e ações rápidas", seen["labels"])
        self.assertEqual("Pausar expansão", seen["button"])

    def test_a_pause_is_a_written_warning_with_retomar_and_resuming_clears_it(self):
        def run(root):
            window = self._manager(root)
            ui = tx.ui_theme.theme()
            self.app.toggle_enabled(self.tray, None)
            window.update()
            texts, buttons, bands = self._bar(self.app)
            seen = {
                "texts": texts,
                "actions": sorted(buttons),
                "fill": str(bands[0].cget("bg")),
                "warning_bg": ui.warning_bg,
                "status": self.app._manager_status_var.get(),
                "status_fg": str(self.app._manager_status_label.cget("fg")),
                "warning": ui.warning,
                "sidebar_button": str(self.app._manager_toggle_button.cget("text")),
                "tray_title": self.tray.title,
            }
            buttons["Retomar"].invoke()
            window.update()
            seen["after"] = (self.app.enabled, self._bar(self.app), self.tray.title)
            return seen

        seen = self._on_gui(run)
        self.assertIn("Expansão pausada", seen["texts"])
        self.assertEqual(["Retomar"], seen["actions"])
        self.assertEqual(seen["warning_bg"], seen["fill"])
        self.assertEqual(("Expansão pausada", seen["warning"]), (seen["status"], seen["status_fg"]))
        self.assertEqual("Retomar expansão", seen["sidebar_button"])
        self.assertEqual(f"{tx.APP_DISPLAY_NAME} · Expansão pausada", seen["tray_title"])
        self.assertEqual((True, None, tx.APP_DISPLAY_NAME), seen["after"])

    def test_a_failed_capture_is_a_danger_infobar_and_the_sidebar_says_so(self):
        def run(root):
            window = self._manager(root)
            ui = tx.ui_theme.theme()
            self.app.capture_error = OSError("hook unavailable")
            self.app.enabled = False
            self.app._refresh_manager_status()
            window.update()
            texts, buttons, bands = self._bar(self.app)
            return {
                "texts": texts, "actions": sorted(buttons), "fill": str(bands[0].cget("bg")),
                "danger_bg": ui.danger_bg, "status": self.app._manager_status_var.get(),
                "status_fg": str(self.app._manager_status_label.cget("fg")), "danger": ui.danger,
                "button": (str(self.app._manager_toggle_button.cget("text")),
                           str(self.app._manager_toggle_button.cget("state"))),
            }

        seen = self._on_gui(run)
        self.assertIn("Captura falhou", seen["texts"])
        self.assertNotIn("Expansão pausada", seen["texts"], "a failed capture is not a pause")
        self.assertEqual(["Abrir log"], seen["actions"])
        self.assertEqual(seen["danger_bg"], seen["fill"])
        self.assertEqual(("Captura falhou", seen["danger"]), (seen["status"], seen["status_fg"]))
        self.assertEqual(("Reinicie o SnipType", "disabled"), seen["button"])

    def _corrupt_library(self, *, with_backup):
        if not with_backup:
            shutil.rmtree(self.app.backups_dir)
        with open(self.app.snippets_file, "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        self.app.reload_snippets_from_disk()

    def test_sample_defaults_are_a_danger_infobar_naming_the_quarantined_file(self):
        self._corrupt_library(with_backup=False)
        quarantined = self.app.library_recovery["quarantined"]

        def run(root):
            window = self._manager(root)
            ui = tx.ui_theme.theme()
            texts, buttons, bands = self._bar(self.app)
            with mock.patch.object(self.app, "open_data_folder") as open_folder:
                buttons["Abrir pasta"].invoke()
            return texts, str(bands[0].cget("bg")), ui.danger_bg, open_folder.called, sorted(buttons)

        texts, fill, danger_bg, opened, actions = self._on_gui(run)
        self.assertIn("Usando a biblioteca de exemplo", texts)
        self.assertTrue(any(quarantined in text for text in texts), texts)
        self.assertEqual(danger_bg, fill)
        self.assertEqual(["Abrir pasta"], actions, "an error cannot be dismissed")
        self.assertTrue(opened)

    def test_a_restore_from_backup_is_info_that_can_be_dismissed_or_followed(self):
        self._corrupt_library(with_backup=True)
        self.assertEqual("backup", self.app.library_recovery["kind"])

        def run(root):
            window = self._manager(root)
            texts, buttons, bands = self._bar(self.app)
            seen = {"texts": texts, "actions": sorted(buttons)}
            buttons["Ver cópias de segurança"].invoke()
            window.update()
            notebook = self.app._manager_notebook
            seen["page"] = notebook.select() == str(self.app._manager_pages["backups"])
            buttons = self._bar(self.app)[1]
            buttons["Dispensar"].invoke()
            window.update()
            seen["after"] = self._bar(self.app)
            return seen

        seen = self._on_gui(run)
        self.assertTrue(any(t.startswith("Biblioteca restaurada do backup · ") for t in seen["texts"]))
        self.assertEqual(["Dispensar", "Ver cópias de segurança"], seen["actions"])
        self.assertTrue(seen["page"], "the action opens the exact place")
        self.assertIsNone(seen["after"], "a dismissed info stays gone")

    def test_the_infobar_keeps_its_widgets_when_nothing_changed(self):
        def run(root):
            self._manager(root)
            self.app.enabled = False
            self.app._refresh_manager_health()
            before = list(self.app._manager_health.frame.winfo_children())
            self.app._refresh_manager_health()
            return before == list(self.app._manager_health.frame.winfo_children())

        self.assertTrue(self._on_gui(run), "a refresh must not cost a button its focus")

    def test_multiple_issues_keep_one_band_and_the_editor_inside_the_minimum_window(self):
        def run(root):
            window = self._manager(root)
            record = {"ok": False, "at": "2026-10-20T10:00:00", "error": "x", "path": "p"}
            self.app.enabled = False
            self.app.last_save_error = {"at": record["at"], "error": "x"}
            self.app.shadowed_static_snippets = {"xdup": "t"}
            self.app.last_mirror = record
            self.app.last_sync = record
            self.app._refresh_manager_health()
            window.update()
            frame = self._static_tab_of(window)
            editor = self.app._manager_receipts[str(frame)].frame.master
            texts, _buttons_shown, bands = self._bar(self.app)
            return {
                "texts": texts,
                "bands": len(bands),
                "editor_bottom": editor.winfo_rooty() + editor.winfo_height(),
                "window_bottom": window.winfo_rooty() + window.winfo_height(),
            }

        seen = self._on_gui(run)
        texts = seen["texts"]
        # One full issue and a compact summary preserve the editor's height.
        self.assertIn("Não foi possível salvar a biblioteca", texts)
        self.assertEqual(1, seen["bands"])
        summary = next(text for text in texts if text.startswith("Também aguardando atenção:"))
        for title in ("Expansão pausada", "Triggers em conflito com ações dinâmicas",
                      "Cópia espelho não gravada", "Pacote de sincronização não exportado"):
            self.assertIn(title, summary)
        self.assertLessEqual(seen["editor_bottom"], seen["window_bottom"])

    def test_library_recovery_clears_receipts_for_items_that_are_no_longer_loaded(self):
        def run(root):
            window = self._manager(root)
            for receipt in self.app._manager_receipts.values():
                receipt.show("Salvo às 10:00 · xhi", "Desfazer", lambda: None)
            self._corrupt_library(with_backup=False)
            window.update()
            return [(str(receipt.label.cget("text")), receipt._hint,
                     receipt.action.winfo_manager())
                    for receipt in self.app._manager_receipts.values()]

        receipts = self._on_gui(run)
        self.assertTrue(receipts)
        for text, resting_text, action_manager in receipts:
            self.assertEqual(resting_text, text)
            self.assertFalse(action_manager, "an undo for the replaced library must disappear")

    def test_a_library_refresh_redraws_the_infobar_with_the_new_state(self):
        # A dynamic toggle, a reload, a restore and an import all end in
        # _refresh_manager_lists; the shadowed triggers they change must show.
        def run(root):
            self._manager(root)
            before = self._bar(self.app)
            self.app.shadowed_static_snippets = {"xdup": "text"}
            self.app._refresh_manager_lists()
            shown = self._bar(self.app)
            self.app.shadowed_static_snippets = {}
            self.app._refresh_manager_lists()
            return before, shown, self._bar(self.app)

        before, shown, after = self._on_gui(run)
        self.assertIsNone(before)
        self.assertIsNotNone(shown, "the bar must show the state a refresh just read")
        self.assertIn("Triggers em conflito com ações dinâmicas", shown[0])
        self.assertIsNone(after, "resolved trouble leaves the bar")

    def _static_tab_of(self, window):
        notebook = self.app._manager_notebook
        notebook.select(notebook.tabs()[0])
        window.update()
        return notebook.nametowidget(notebook.tabs()[0])

    @staticmethod
    def _status_line(frame, start):
        return [t for t in _labels(frame) if t.startswith(start)]

    def test_a_save_with_the_manager_open_writes_a_receipt_and_sends_no_toast(self):
        def run(root):
            window = self._manager(root)
            frame = self._static_tab_of(window)
            tree = next(w for w in _descendants(frame) if isinstance(w, ttk.Treeview))
            text = next(w for w in _descendants(frame) if isinstance(w, tk.Text))
            tree.selection_set("xhi")
            window.update()
            text.insert("end", "!")
            window.update()
            _buttons(frame)["Salvar"].invoke()
            window.update()
            return self._status_line(frame, "Salvo às")

        receipt = self._on_gui(run)
        self.assertEqual([], self.tray.toasts, "success is quiet while the window is up")
        self.assertEqual(1, len(receipt))
        self.assertRegex(receipt[0], r"^Salvo às \d\d:\d\d · xhi$")
        with open(self.app.snippets_file, encoding="utf-8") as handle:
            self.assertEqual("hello!", json.load(handle)["xhi"])
        # The record keeps it, dated.
        self.assertEqual(receipt[0], self.app.notification_history[-1]["message"])
        self.assertIn("at", self.app.notification_history[-1])

    def test_the_editor_status_line_rests_on_the_save_shortcut_not_on_a_format_caption(self):
        def run(root):
            window = self._manager(root)
            return _labels(self._static_tab_of(window))

        labels = self._on_gui(run)
        self.assertIn("Ctrl+S para salvar", labels)
        self.assertFalse([t for t in labels if t.startswith("Formatação opcional")])

    def test_the_backups_page_confirms_in_its_status_line_and_opens_no_dialog(self):
        def run(root):
            window = self._manager(root)
            notebook = self.app._manager_notebook
            page = self.app._manager_pages["backups"]
            notebook.select(page)
            window.update()
            seen = {}
            with mock.patch.object(tx.ui_widgets, "alert") as alert, \
                    mock.patch.object(tx.ui_widgets, "confirm", return_value=tx.ui_widgets.PRIMARY):
                _buttons(page)["Criar backup"].invoke()
                window.update()
                seen["created"] = self._status_line(page, "Backup criado às")
                tree = next(w for w in _descendants(page) if isinstance(w, ttk.Treeview))
                tree.selection_set(tree.get_children()[0])
                _buttons(page)["Restaurar"].invoke()
                window.update()
                seen["restored"] = self._status_line(page, "Backup restaurado às")
                destination = os.path.join(self.app.data_dir, "export.json")
                with mock.patch.object(tx.filedialog, "asksaveasfilename", return_value=destination):
                    _buttons(page)["Exportar…"].invoke()
                window.update()
                seen["exported"] = self._status_line(page, "Biblioteca exportada às")
                source = os.path.join(self.app.data_dir, "import-source.json")
                with open(source, "w", encoding="utf-8") as handle:
                    json.dump({"xnew": "novo"}, handle)
                with mock.patch.object(tx.filedialog, "askopenfilename", return_value=source),                         mock.patch.object(self.app, "_ask_import_mode", return_value="merge"):
                    _buttons(page)["Importar…"].invoke()
                window.update()
                seen["imported"] = self._status_line(page, "Biblioteca importada às")
            seen["alerts"] = alert.call_args_list
            return seen

        seen = self._on_gui(run)
        self.assertEqual([], seen["alerts"], "a success is never a modal")
        self.assertRegex(seen["created"][0], r"^Backup criado às \d\d:\d\d$")
        self.assertRegex(seen["restored"][0], r"^Backup restaurado às \d\d:\d\d · ")
        self.assertRegex(seen["exported"][0], r"^Biblioteca exportada às \d\d:\d\d · export\.json$")
        self.assertRegex(
            seen["imported"][0], r"^Biblioteca importada às \d\d:\d\d · import-source\.json$")
        self.assertEqual([], self.tray.toasts)

    def test_a_failure_on_the_backups_page_is_still_told_with_a_dialog(self):
        def run(root):
            window = self._manager(root)
            page = self.app._manager_pages["backups"]
            self.app._manager_notebook.select(page)
            window.update()
            with mock.patch.object(self.app, "backup_now", return_value=None), \
                    mock.patch.object(tx.ui_widgets, "alert") as alert:
                _buttons(page)["Criar backup"].invoke()
            return alert.call_args

        call = self._on_gui(run)
        self.assertEqual("Criar backup", call.args[1])
        self.assertEqual("danger", call.kwargs["tone"])

    def _history(self, root, parent):
        before = set(parent.winfo_children())
        self.app._open_notification_history(parent)
        parent.update()
        window = next(w for w in parent.winfo_children() if w not in before)
        tree = next(w for w in _descendants(window) if isinstance(w, ttk.Treeview))
        return window, tree

    @staticmethod
    def _rows(tree):
        return [(tree.item(i, "values"), tuple(tree.item(i, "tags"))) for i in tree.get_children()]

    def test_the_history_shows_dates_tags_errors_and_filters_to_them(self):
        now = datetime.now()
        today = now.replace(hour=11, minute=15, second=3, microsecond=0)
        yesterday = today - timedelta(days=1)
        self.app.notification_history = [
            {"time": "10:05:00", "title": "SnipType", "message": "legacy status", "kind": "status"},
            {"time": yesterday.strftime("%H:%M:%S"), "at": yesterday.isoformat(timespec="seconds"),
             "title": "SnipType", "message": "yesterday status", "kind": "status"},
            {"time": today.strftime("%H:%M:%S"), "at": today.isoformat(timespec="seconds"),
             "title": "SnipType", "message": "boom", "kind": "error"},
        ]

        def run(root):
            parent = self._manager(root)
            window, tree = self._history(root, parent)
            seen = {"title": window.title(), "rows": self._rows(tree)}
            seen["headings"] = [str(tree.heading(c, "anchor")) for c in ("time", "kind", "message")]
            seen["columns"] = [str(tree.column(c, "anchor")) for c in ("time", "kind", "message")]
            toggle = _buttons_or_checks(window)["Somente erros"]
            toggle.invoke()
            window.update()
            seen["errors_only"] = self._rows(tree)
            return seen

        seen = self._on_gui(run)
        self.assertEqual("Histórico de notificações", seen["title"])
        self.assertEqual(
            [(("Hoje 11:15", "Erro", "boom"), ("error",)),
             ((yesterday_label(yesterday), "Status", "yesterday status"), ()),
             (("10:05:00", "Status", "legacy status"), ())],
            [(values, tags) for values, tags in seen["rows"]],
        )
        self.assertEqual(["w", "w", "w"], seen["headings"])
        self.assertEqual(["w", "w", "w"], seen["columns"])
        self.assertEqual([(("Hoje 11:15", "Erro", "boom"), ("error",))], seen["errors_only"])

    def test_an_empty_history_says_so_instead_of_inventing_a_row(self):
        self.app.notification_history = []

        def run(root):
            parent = self._manager(root)
            window, tree = self._history(root, parent)
            empty = next(w for w in _descendants(window)
                         if isinstance(w, tk.Label) and str(w.cget("text")).startswith("Nenhuma"))
            at_rest = str(empty.cget("text"))
            _buttons_or_checks(window)["Somente erros"].invoke()
            window.update()
            return self._rows(tree), at_rest, str(empty.cget("text"))

        rows, empty, filtered = self._on_gui(run)
        self.assertEqual([], rows)
        self.assertEqual("Nenhuma notificação registrada ainda.", empty)
        self.assertEqual("Nenhum erro registrado.", filtered)

    def test_the_dados_card_reports_each_destination_and_offers_a_retry_on_failure(self):
        mirror = os.path.join(self.app.data_dir, "mirror")
        cloud = os.path.join(self.app.data_dir, "cloud")
        self.app.settings.update({"mirror_dir": mirror, "sync_export_dir": cloud})

        def run(root):
            window = self._manager(root)
            self.app._manager_settings_sections.select("data")
            self.app._manager_notebook.select(self.app._manager_settings_tab)
            window.update()
            page = self.app._manager_settings_tab
            seen = {"first": [t for t in _labels(page) if "nesta sessão" in t]}
            exported = datetime.now() - timedelta(days=30)
            seen["stamp"] = tx.time_format.absolute_stamp(exported, datetime.now())
            self.app.last_sync = {
                "ok": True, "at": exported.isoformat(timespec="seconds"), "error": None, "path": cloud}
            self.app.last_mirror = {
                "ok": False, "at": datetime.now().isoformat(timespec="seconds"),
                "error": "denied", "path": mirror}
            self.app._refresh_manager_health()
            window.update()
            seen["lines"] = [t for t in _labels(page) if t.startswith("Última")]
            retries = [w for w in _descendants(page)
                       if isinstance(w, BUTTONS) and str(w.cget("text")) == "Tentar agora"
                       and w.winfo_ismapped()]
            seen["retry_buttons"] = len(retries)
            with mock.patch.object(self.app, "retry_sync") as retry:
                retries[0].invoke()
            seen["retried"] = retry.called
            bar = self._bar(self.app)
            seen["bar"] = bar[0] if bar else None
            return seen

        seen = self._on_gui(run)
        self.assertEqual(
            ["Nenhuma cópia nesta sessão ainda.", "Nenhuma exportação nesta sessão ainda."],
            seen["first"])
        self.assertIn(f"Última exportação {seen['stamp']} · OK", seen["lines"])
        self.assertTrue(any(l.startswith("Última cópia falhou") and l.endswith("· denied")
                            for l in seen["lines"]), seen["lines"])
        self.assertEqual(1, seen["retry_buttons"], "only the failed destination offers a retry")
        self.assertTrue(seen["retried"])
        self.assertIn("Cópia espelho não gravada", seen["bar"])

    def test_nav_counts_are_totals_and_the_list_header_shows_how_many_the_filter_leaves(self):
        self.app.snippets.update({"xola": "Olá", "xbye": "Tchau"})
        self.assertTrue(self.app.save_snippets(self.app.snippets))

        def run(root):
            window = self._manager(root)
            frame = self._static_tab_of(window)
            search = self.app._manager_search_entries[str(frame)]
            before = (self._status_line(frame, "3 de"), self._nav_text(window))
            search.insert(0, "xola")
            window.update()
            after = (self._status_line(frame, "1 de"), self._nav_text(window))
            return before, after

        before, after = self._on_gui(run)
        self.assertEqual((["3 de 3"], "Textos (3)"), before)
        self.assertEqual((["1 de 3"], "Textos (3)"), after)

    def test_an_exception_in_a_tk_callback_is_logged_and_told_not_lost(self):
        self.app.logger = mock.Mock()

        def run(root):
            self.app._install_callback_hook(root)
            try:
                root.after(0, lambda: 1 / 0)
                root.update()
            finally:
                del root.report_callback_exception

        self._on_gui(run)

        self.assertIn("ZeroDivisionError", self.app.logger.error.call_args.args[0])
        self.assertEqual(["Erro inesperado: division by zero"], self.tray.toasts)

    @staticmethod
    def _nav_text(window):
        return next(str(b.cget("text")) for b in _buttons(window).values()
                    if str(b.cget("text")).startswith("Textos ("))


def _buttons_or_checks(window):
    return {str(w.cget("text")): w for w in _descendants(window) if isinstance(w, BUTTONS + CHECKBOXES)}


def yesterday_label(moment):
    return f"Ontem {moment.strftime('%H:%M')}"


# GuiThread's own marshaling contract (call/submit/stop, exceptions, reentrancy,
# stranded callers) is covered directly and adversarially in test_gui_thread.py.
# This file keeps only the manager-GUI construction and dialog-serialization
# smoke tests that genuinely exercise Sniptype widgets on the shared root.


if __name__ == "__main__":
    unittest.main()
