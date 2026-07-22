import unittest
from unittest.mock import Mock

from whatsapp_runtime_support import execute_whatsapp_action


class WhatsAppRuntimeSupportTests(unittest.TestCase):
    def test_xwapp_uses_clipboard_and_opens_browser(self):
        get_clipboard_text = Mock(return_value="11999999999")
        ask_input = Mock()
        set_clipboard_content = Mock(return_value=True)
        open_url = Mock(return_value=(True, None))
        notify_error = Mock()

        result = execute_whatsapp_action(
            "xwapp",
            get_clipboard_text=get_clipboard_text,
            ask_input=ask_input,
            set_clipboard_content=set_clipboard_content,
            open_url=open_url,
            notify_error=notify_error,
        )

        self.assertIsNone(result)
        ask_input.assert_not_called()
        set_clipboard_content.assert_called_once_with("https://wa.me/5511999999999")
        open_url.assert_called_once_with("https://wa.me/5511999999999")
        notify_error.assert_not_called()

    def test_xlwapp_falls_back_to_popup_and_returns_url(self):
        get_clipboard_text = Mock(return_value="histórico do clipboard")
        ask_input = Mock(return_value=("5511999999999", "Olá!"))
        set_clipboard_content = Mock(return_value=True)
        open_url = Mock()
        notify_error = Mock()

        result = execute_whatsapp_action(
            "xlwapp",
            get_clipboard_text=get_clipboard_text,
            ask_input=ask_input,
            set_clipboard_content=set_clipboard_content,
            open_url=open_url,
            notify_error=notify_error,
        )

        self.assertEqual("https://wa.me/5511999999999?text=Ol%C3%A1%21", result)
        ask_input.assert_called_once_with()
        set_clipboard_content.assert_called_once_with("https://wa.me/5511999999999?text=Ol%C3%A1%21")
        open_url.assert_not_called()
        notify_error.assert_not_called()

    def test_xpwapp_skips_clipboard_and_prompts_immediately(self):
        get_clipboard_text = Mock(side_effect=AssertionError("clipboard should not be read"))
        ask_input = Mock(return_value=("5511999999999", "Mensagem pronta"))
        set_clipboard_content = Mock(return_value=True)
        open_url = Mock(return_value=(True, None))
        notify_error = Mock()

        result = execute_whatsapp_action(
            "xpwapp",
            get_clipboard_text=get_clipboard_text,
            ask_input=ask_input,
            set_clipboard_content=set_clipboard_content,
            open_url=open_url,
            notify_error=notify_error,
        )

        self.assertIsNone(result)
        ask_input.assert_called_once_with()
        set_clipboard_content.assert_called_once_with(
            "https://wa.me/5511999999999?text=Mensagem%20pronta"
        )
        open_url.assert_called_once_with(
            "https://wa.me/5511999999999?text=Mensagem%20pronta"
        )
        notify_error.assert_not_called()

    def test_xlwapp_notifies_when_clipboard_copy_fails_but_still_returns_url(self):
        notify_error = Mock()

        result = execute_whatsapp_action(
            "xlwapp",
            get_clipboard_text=Mock(return_value="+1 (212) 555-1234"),
            ask_input=Mock(),
            set_clipboard_content=Mock(return_value=False),
            open_url=Mock(),
            notify_error=notify_error,
        )

        self.assertEqual("https://wa.me/12125551234", result)
        notify_error.assert_called_once()
        self.assertIn("copiar o link do WhatsApp", notify_error.call_args.args[0])

    # --- clipboard-first fallback behaviour ---

    def test_xwapp_clipboard_read_error_notifies_and_falls_back_to_prompt(self):
        get_clipboard_text = Mock(side_effect=OSError("clipboard busy"))
        ask_input = Mock(return_value=("5511999999999", ""))
        set_clipboard_content = Mock(return_value=True)
        open_url = Mock(return_value=(True, None))
        notify_error = Mock()

        result = execute_whatsapp_action(
            "xwapp",
            get_clipboard_text=get_clipboard_text,
            ask_input=ask_input,
            set_clipboard_content=set_clipboard_content,
            open_url=open_url,
            notify_error=notify_error,
        )

        self.assertIsNone(result)
        ask_input.assert_called_once_with()
        open_url.assert_called_once_with("https://wa.me/5511999999999")
        notify_error.assert_called_once()
        self.assertEqual(
            "xwapp-clipboard-read-error", notify_error.call_args.kwargs["key"]
        )

    def test_xwapp_empty_clipboard_prompts_without_error(self):
        ask_input = Mock(return_value=("5511999999999", ""))
        notify_error = Mock()

        execute_whatsapp_action(
            "xwapp",
            get_clipboard_text=Mock(return_value=""),
            ask_input=ask_input,
            set_clipboard_content=Mock(return_value=True),
            open_url=Mock(return_value=(True, None)),
            notify_error=notify_error,
        )

        ask_input.assert_called_once_with()
        notify_error.assert_not_called()

    def test_xwapp_uses_whatsapp_link_from_clipboard_without_prompting(self):
        ask_input = Mock()
        open_url = Mock(return_value=(True, None))

        execute_whatsapp_action(
            "xwapp",
            get_clipboard_text=Mock(return_value="https://wa.me/5511988887777"),
            ask_input=ask_input,
            set_clipboard_content=Mock(return_value=True),
            open_url=open_url,
            notify_error=Mock(),
        )

        ask_input.assert_not_called()
        open_url.assert_called_once_with("https://wa.me/5511988887777")

    def test_cancelled_prompt_returns_none_and_touches_nothing(self):
        set_clipboard_content = Mock()
        open_url = Mock()

        result = execute_whatsapp_action(
            "xwapp",
            get_clipboard_text=Mock(return_value=None),
            ask_input=Mock(return_value=(None, "")),
            set_clipboard_content=set_clipboard_content,
            open_url=open_url,
            notify_error=Mock(),
        )

        self.assertIsNone(result)
        set_clipboard_content.assert_not_called()
        open_url.assert_not_called()

    # --- URL build / browser-open failure paths ---

    def test_invalid_phone_from_prompt_notifies_build_error_and_aborts(self):
        set_clipboard_content = Mock()
        open_url = Mock()
        notify_error = Mock()

        result = execute_whatsapp_action(
            "xpwapp",
            get_clipboard_text=Mock(side_effect=AssertionError("clipboard not read")),
            ask_input=Mock(return_value=("abc", "mensagem")),
            set_clipboard_content=set_clipboard_content,
            open_url=open_url,
            notify_error=notify_error,
        )

        self.assertIsNone(result)
        set_clipboard_content.assert_not_called()
        open_url.assert_not_called()
        self.assertEqual("xpwapp-build-error", notify_error.call_args.kwargs["key"])

    def test_browser_open_failure_is_reported_with_message(self):
        notify_error = Mock()

        execute_whatsapp_action(
            "xwapp",
            get_clipboard_text=Mock(return_value="5511999999999"),
            ask_input=Mock(),
            set_clipboard_content=Mock(return_value=True),
            open_url=Mock(return_value=(False, "no default browser")),
            notify_error=notify_error,
        )

        self.assertEqual("xwapp-open-error", notify_error.call_args.kwargs["key"])
        self.assertIn("no default browser", notify_error.call_args.args[0])

    def test_browser_open_exception_is_caught_and_reported(self):
        notify_error = Mock()

        execute_whatsapp_action(
            "xwapp",
            get_clipboard_text=Mock(return_value="5511999999999"),
            ask_input=Mock(),
            set_clipboard_content=Mock(return_value=True),
            open_url=Mock(side_effect=RuntimeError("webbrowser exploded")),
            notify_error=notify_error,
        )

        self.assertEqual("xwapp-open-error", notify_error.call_args.kwargs["key"])
        self.assertIn("webbrowser exploded", notify_error.call_args.args[0])

    def test_clipboard_write_exception_notifies_but_still_opens_browser(self):
        open_url = Mock(return_value=(True, None))
        notify_error = Mock()

        execute_whatsapp_action(
            "xwapp",
            get_clipboard_text=Mock(return_value="5511999999999"),
            ask_input=Mock(),
            set_clipboard_content=Mock(side_effect=OSError("clipboard locked")),
            open_url=open_url,
            notify_error=notify_error,
        )

        open_url.assert_called_once_with("https://wa.me/5511999999999")
        self.assertEqual(
            "xwapp-clipboard-write-error", notify_error.call_args.kwargs["key"]
        )

    def test_unsupported_trigger_raises_value_error(self):
        with self.assertRaises(ValueError):
            execute_whatsapp_action(
                "xzzapp",
                get_clipboard_text=Mock(),
                ask_input=Mock(),
                set_clipboard_content=Mock(),
                open_url=Mock(),
                notify_error=Mock(),
            )


if __name__ == "__main__":
    unittest.main()
