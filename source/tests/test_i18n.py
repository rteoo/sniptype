"""Interface language: switching, and catalog completeness against the source.

The completeness tests read the source with ``ast`` rather than trusting a list:
every ``_()``/``N_()``/``lazy()`` literal must have an English entry, every entry
must still be used, placeholders must survive translation, and a Portuguese
literal outside those markers fails unless its line says ``# i18n: not ui``
(snippet output, log text and other strings that are deliberately not interface).
"""

import ast
import json
import os
import re
import string
import sys
import unittest

SOURCE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SOURCE)

import i18n
from i18n_en_us import EN_US

MARKERS = {"_", "N_", "lazy"}
# ``print`` is console output that the packaged ``pythonw`` build never shows.
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "_warn", "_log", "print"}
# Whole modules whose Portuguese text is snippet output, not interface.
CONTENT_MODULES = {"bcb_consultor.py", "yf_stocks.py"}
OPT_OUT = "# i18n: not ui"
# Structural rule on top of the Portuguese heuristic, which misses single words
# such as "Notas": text handed straight to one of these UI sinks must be marked.
UI_KEYWORDS = {"text", "title", "message", "detail"}
UI_ARGS = {
    "title": (0,), "showinfo": (0, 1), "showerror": (0, 1), "showwarning": (0, 1),
    "askyesno": (0, 1), "askokcancel": (0, 1), "askyesnocancel": (0, 1),
    "askstring": (0, 1), "_label": (1,), "_button": (1,), "notify_status": (0,),
    "notify_error": (0,), "MenuItem": (0,), "add": (1,),
}

PORTUGUESE = re.compile(
    r"[ãõçáéíóúâêôàÃÕÇÁÉÍÓÚÂÊÔÀ]|\b("
    r"não|nao|sim|para|sem|uma?|da|dos|das|nos|nas|ao|pelo|pela|"
    r"salvar|salvo|cancelar|fechar|excluir|editar|novo|nova|nome|erro|falha|abrir|"
    r"atalhos?|grupos?|gatilhos?|buscar|copiar|colar|aplicar|restaurar|importar|"
    r"exportar|selecione|escolha|digite|adicionar|remover|renomear|duplicar|voltar|"
    r"ativar|desativar|ativo|ativos|arquivos?|pasta|textos?|mapeamentos?|dados|geral|"
    r"nenhum|nenhuma|todos|todas|campos?|valor|valores|visualizar|sair|pausar|"
    r"retomar|limpar|recarregar|gerenciar|iniciar|sistema|claro|escuro|idioma|"
    r"favoritos?|tipo|padrão|obrigatório|opcional|enviar|abrindo|aguarde|telefone|"
    r"mensagem|número|numero|inválido|invalido|vazio|existe|já|ja|está|esta|foi|"
    r"ser|será|pode|deve|seu|sua|este|esse|essa|isso|aqui|agora|depois|antes|"
    r"entre|sobre|também|apenas|ainda|cada|outro|outra|quando|onde|como|mais|menos|"
    r"formato|negrito|sublinhado|tachado|efetivo|exemplo|prefixo|identificador|"
    r"ativado|ativada|desativado|desativada"
    r")\b",
    re.IGNORECASE,
)


def _source_files():
    for name in sorted(os.listdir(SOURCE)):
        if name.endswith((".py", ".pyw")) and name not in {"i18n.py", "i18n_en_us.py"}:
            yield name


def _parse(name):
    path = os.path.join(SOURCE, name)
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    return ast.parse(text), text.splitlines()


def _call_name(node):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _scan():
    """Return (ids, stray) — marked ids with locations, and unmarked Portuguese."""
    ids = {}
    stray = []
    for name in _source_files():
        tree, lines = _parse(name)
        skip = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.body and isinstance(node.body[0], ast.Expr) and _literal(node.body[0].value) is not None:
                    skip.add(id(node.body[0].value))
            if isinstance(node, ast.Call):
                called = _call_name(node)
                if called in MARKERS:
                    for arg in node.args:
                        skip.update(id(child) for child in ast.walk(arg))
                        text = _literal(arg)
                        if text is not None:
                            ids.setdefault(text, f"{name}:{node.lineno}")
                        elif isinstance(arg, ast.JoinedStr):
                            stray.append(f"{name}:{node.lineno}: f-string inside {called}()")
                elif called in LOG_METHODS or (
                    isinstance(node.func, ast.Attribute)
                    and called in {"append"} and "log" in ast.unparse(node.func.value).lower()
                ):
                    skip.update(id(child) for child in ast.walk(node))
        if name in CONTENT_MODULES:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) in MARKERS or id(node) in skip:
                continue
            sinks = [kw.value for kw in node.keywords if kw.arg in UI_KEYWORDS]
            sinks += [node.args[i] for i in UI_ARGS.get(_call_name(node), ()) if i < len(node.args)]
            # ``text=value or "Padrão"`` and ``text="A" if on else "B"`` hide
            # their literals one level down.
            for value in list(sinks):
                if isinstance(value, ast.BoolOp):
                    sinks += value.values
                elif isinstance(value, ast.IfExp):
                    sinks += [value.body, value.orelse]
            for value in sinks:
                text = _literal(value)
                if isinstance(value, ast.JoinedStr):
                    text = "".join(v.value for v in value.values if isinstance(v, ast.Constant)) or "{}"
                if text is None or not any(ch.isalpha() for ch in text):
                    continue
                skip.update(id(child) for child in ast.walk(value))
                span = lines[value.lineno - 1:value.end_lineno]
                if not any(OPT_OUT in line for line in span):
                    stray.append(f"{name}:{value.lineno}: {text[:70]!r} (UI sink)")
        for node in ast.walk(tree):
            if id(node) in skip:
                continue
            if isinstance(node, ast.JoinedStr):
                text = "".join(v.value for v in node.values if isinstance(v, ast.Constant))
                skip.update(id(child) for child in ast.walk(node))
            else:
                text = _literal(node)
            if not text or not PORTUGUESE.search(text):
                continue
            span = lines[node.lineno - 1:getattr(node, "end_lineno", node.lineno)]
            if any(OPT_OUT in line for line in span):
                continue
            stray.append(f"{name}:{node.lineno}: {text[:70]!r}")
    return ids, stray


def _registry_ids():
    with open(os.path.join(SOURCE, "dynamic_snippets.json"), encoding="utf-8") as handle:
        registry = json.load(handle)
    return {
        entry[key]
        for entry in registry.values()
        for key in ("description", "dialog")
        if isinstance(entry, dict) and entry.get(key)
    }


def _placeholders(text):
    return sorted(field for _, field, _, _ in string.Formatter().parse(text) if field is not None)


class LanguageSwitchTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_default_is_portuguese_and_returns_the_source_text(self):
        self.assertEqual(i18n.language(), "pt-BR")
        self.assertEqual(i18n._("Texto sem entrada no catálogo"), "Texto sem entrada no catálogo")

    def test_english_uses_the_catalog_and_falls_back_to_portuguese(self):
        msgid, english = next(iter(EN_US.items()))
        i18n.set_language("en-US")
        self.assertEqual(i18n._(msgid), english)
        self.assertEqual(i18n._("Texto sem entrada no catálogo"), "Texto sem entrada no catálogo")

    def test_unknown_language_falls_back_to_portuguese(self):
        i18n.set_language("fr-FR")
        self.assertEqual(i18n.language(), "pt-BR")

    def test_lazy_label_follows_the_current_language(self):
        msgid, english = next(iter(EN_US.items()))
        label = i18n.lazy(msgid)
        self.assertEqual(label(None), msgid)
        i18n.set_language("en-US")
        self.assertEqual(label(None), english)

    def test_marker_returns_its_argument_untranslated(self):
        i18n.set_language("en-US")
        msgid = next(iter(EN_US))
        self.assertEqual(i18n.N_(msgid), msgid)


class CatalogCompletenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ids, cls.stray = _scan()
        cls.used = set(cls.ids) | _registry_ids()

    def test_no_portuguese_interface_text_is_left_unmarked(self):
        self.assertEqual(self.stray, [], "\n" + "\n".join(self.stray))

    def test_every_marked_string_has_an_english_entry(self):
        missing = sorted(f"{where}: {msgid!r}" for msgid, where in self.ids.items() if msgid not in EN_US)
        missing += sorted(repr(msgid) for msgid in _registry_ids() if msgid not in EN_US)
        self.assertEqual(missing, [], "\n" + "\n".join(missing))

    def test_catalog_has_no_unused_entries(self):
        unused = sorted(repr(msgid) for msgid in EN_US if msgid not in self.used)
        self.assertEqual(unused, [], "\n" + "\n".join(unused))

    def test_translations_keep_their_placeholders(self):
        mismatched = [
            f"{msgid!r} -> {text!r}"
            for msgid, text in EN_US.items()
            if not text.strip() or _placeholders(msgid) != _placeholders(text)
        ]
        self.assertEqual(mismatched, [], "\n" + "\n".join(mismatched))


if __name__ == "__main__":
    unittest.main()
