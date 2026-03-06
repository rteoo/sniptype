from rich_text_support import extract_plain_text


DATETIME_SNIPPETS = [
    ("xhj", "Data de hoje (DD/MM/AAAA)"),
    ("x-hj", "Data de hoje (AAAA-MM-DD)"),
    ("xhoje", "Data por extenso (ex: segunda-feira, 02 de março de 2026)"),
    ("xnow", "Hora atual (HH:MM:SS)"),
    ("xdatahora", "Data e hora (DD/MM/AAAA às HH:MM)"),
]

ECONOMY_SNIPPETS = [
    ("xdolar", "Cotação do dólar (PTAX compra/venda)"),
    ("xselic", "Taxa Selic meta (% a.a.)"),
    ("xipcam", "IPCA mensal (%)"),
    ("xipca12", "IPCA acumulado 12 meses (%)"),
    ("xcdi", "Taxa CDI acumulada no mês"),
    ("xptax", "PTAX via SGS"),
    ("xeconomia", "Resumo completo de indicadores"),
]

STOCK_SNIPPETS = [
    ("xcot", "Cotação atual"),
    ("xplucro", "P/L (Preço / Lucro)"),
    ("xcap", "Market Cap (Valor de Mercado)"),
    ("xpvp", "P/VP (Preço / Valor Patrimonial)"),
    ("xdy", "Dividend Yield (%)"),
    ("xebt", "EBITDA"),
    ("xmarg", "Margem Líquida (%)"),
    ("xroe", "ROE (Return on Equity)"),
    ("xdivt", "Dívida Total"),
    ("xdivl", "Dívida Líquida"),
    ("xcaixa", "Caixa (Total Cash)"),
    ("xvol", "Volume Médio Diário"),
    ("xrec", "Receita Líquida"),
    ("xbeta", "Beta (volatilidade vs. mercado)"),
    ("x52w", "Máxima e Mínima de 52 semanas"),
    ("xfund", "Resumo completo de fundamentos"),
]


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
