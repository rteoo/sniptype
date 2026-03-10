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


if __name__ == "__main__":
    unittest.main()
