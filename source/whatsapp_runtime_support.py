from dataclasses import dataclass

from whatsapp_support import build_whatsapp_url, normalize_phone_number


@dataclass(frozen=True)
class WhatsAppActionMode:
    clipboard_first: bool
    copy_url: bool
    open_browser: bool
    return_url: bool


WHATSAPP_ACTION_MODES = {
    "xwapp": WhatsAppActionMode(
        clipboard_first=True,
        copy_url=True,
        open_browser=True,
        return_url=False,
    ),
    "xlwapp": WhatsAppActionMode(
        clipboard_first=True,
        copy_url=True,
        open_browser=False,
        return_url=True,
    ),
    "xpwapp": WhatsAppActionMode(
        clipboard_first=False,
        copy_url=True,
        open_browser=True,
        return_url=False,
    ),
}


def execute_whatsapp_action(
    trigger,
    *,
    get_clipboard_text,
    ask_input,
    set_clipboard_content,
    open_url,
    notify_error,
):
    mode = WHATSAPP_ACTION_MODES.get(trigger)
    if mode is None:
        raise ValueError(f"Unsupported WhatsApp trigger: {trigger}")

    normalized_phone = None
    message_text = ""

    if mode.clipboard_first:
        try:
            clipboard_text = get_clipboard_text()
        except Exception as exc:
            clipboard_text = None
            notify_error(
                f"Falha ao ler a area de transferencia para o WhatsApp: {exc}",
                key=f"{trigger}-clipboard-read-error",
                cooldown_seconds=5,
            )
        normalized_phone = normalize_phone_number(clipboard_text)

    if not normalized_phone:
        normalized_phone, message_text = ask_input()
        if not normalized_phone:
            return None

    try:
        url = build_whatsapp_url(normalized_phone, message_text)
    except Exception as exc:
        notify_error(
            f"Falha ao gerar link do WhatsApp: {exc}",
            key=f"{trigger}-build-error",
            cooldown_seconds=5,
        )
        return None

    if mode.copy_url:
        try:
            copied = set_clipboard_content(url)
        except Exception as exc:
            copied = False
            notify_error(
                f"Nao foi possivel copiar o link do WhatsApp para a area de transferencia: {exc}",
                key=f"{trigger}-clipboard-write-error",
                cooldown_seconds=5,
            )
        else:
            if not copied:
                notify_error(
                    "Nao foi possivel copiar o link do WhatsApp para a area de transferencia.",
                    key=f"{trigger}-clipboard-write-error",
                    cooldown_seconds=5,
                )

    if mode.open_browser:
        try:
            opened, open_error = open_url(url)
        except Exception as exc:
            opened = False
            open_error = str(exc)
        if not opened:
            notify_error(
                f"Nao foi possivel abrir o link do WhatsApp: {open_error}",
                key=f"{trigger}-open-error",
                cooldown_seconds=5,
            )

    if mode.return_url:
        return url

    return None
