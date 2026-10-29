// Same convention as source/i18n.py: Portuguese is the source language and each
// Portuguese string is its own message id. Messages the app sends over the
// bridge arrive already translated by the Python catalog.

const EN_US: Record<string, string> = {
  "Abrir": "Open",
  "Abrir gerenciador clássico": "Open classic manager",
  "Abrir pasta": "Open folder",
  "Ajuste a aparência, a expansão e os dados do SnipType.": "Adjust SnipType's appearance, expansion and data.",
  "Alterações não salvas": "Unsaved changes",
  "Aparência": "Appearance",
  "Avisos": "Notices",
  "Biblioteca, backups e logs ficam nesta pasta.": "The library, backups and logs live in this folder.",
  "Buscar itens": "Search items",
  "Buscar por identificador ou valor": "Search by identifier or value",
  "Buscar por trigger ou texto": "Search by trigger or text",
  "Buscar textos": "Search texts",
  "Cancelar": "Cancel",
  "Claro": "Light",
  "Compacta": "Compact",
  "Configurações": "Settings",
  "Confortável": "Comfortable",
  "Criar tipo": "Create type",
  "Dados": "Data",
  "Densidade": "Density",
  "Descartar": "Discard",
  "Desfazer": "Undo",
  "Desfazer exclusão": "Undo deletion",
  "Digite o prefixo {prefix} e o identificador para expandir.":
    "Type the prefix {prefix} and the identifier to expand.",
  "Digite {trigger} para expandir.": "Type {trigger} to expand.",
  "Editor": "Editor",
  "Erro ao salvar": "Error saving",
  "Escuro": "Dark",
  "Espaço dos controles e das linhas.": "Spacing of controls and rows.",
  "Este texto tem formatação. Esta janela mostra só o texto; edite a formatação no gerenciador clássico.":
    "This text has formatting. This window shows only the text; edit the formatting in the classic manager.",
  "Este tipo ainda não tem itens.": "This type has no items yet.",
  "Ex.: tipo 'email' + prefixo 'mail' -> mailtrabalho": "E.g. type 'email' + prefix 'mail' -> mailwork",
  "Excluir": "Delete",
  "Excluir item": "Delete item",
  "Excluir snippet": "Delete snippet",
  "Excluir tipo": "Delete type",
  "Excluído às {time} · {name}": "Deleted at {time} · {name}",
  "Expande só depois de um espaço ou pontuação, que continua no texto. Enter não conta.":
    "Expands only after a space or punctuation, which stays in the text. Enter does not count.",
  "Feche esta janela e abra o gerenciador de novo pelo ícone da bandeja.":
    "Close this window and open the manager again from the tray icon.",
  "Gerenciador clássico": "Classic manager",
  "Identificador": "Identifier",
  "Idioma": "Language",
  "Idioma da interface. O texto dos snippets não muda.": "Interface language. Snippet text does not change.",
  "Mapeamentos": "Mappings",
  "Modo terminador": "Terminator mode",
  "Nenhum item corresponde à busca.": "No items match the search.",
  "Nenhum texto ainda. Use Novo para criar o primeiro.": "No texts yet. Use New to create the first one.",
  "Nenhum texto encontrado. Ctrl+N cria um com este trigger.": "No text found. Ctrl+N creates one with this trigger.",
  "Nome do tipo": "Type name",
  "Novo": "New",
  "Novo item": "New item",
  "Novo item em {type}": "New item in {type}",
  "Novo texto": "New text",
  "Novo tipo": "New type",
  "Novo tipo de mapeamento": "New mapping type",
  "Não foi possível abrir o item": "Could not open the item",
  "Não foi possível abrir o snippet": "Could not open the snippet",
  "Não é possível excluir tipos padrão (CPF, CNPJ).": "The default types (CPF, CNPJ) cannot be deleted.",
  "O SnipType não respondeu": "SnipType did not respond",
  "O que você digita para expandir. Triggers com '_' são reservados.":
    "What you type to expand. Triggers starting with '_' are reserved.",
  "O texto que entra no lugar do trigger.": "The text that replaces the trigger.",
  "O tipo {type} será excluído com todos os itens ({count}).\n\nA exclusão não pode ser desfeita aqui; a biblioteca anterior continua em Cópias de segurança.":
    "The type {type} will be deleted with all of its items ({count}).\n\nThis cannot be undone here; the previous library stays in Backups.",
  "OK": "OK",
  "Para confirmar, digite {word}": "To confirm, type {word}",
  "Prefixo usado no trigger": "Prefix used in the trigger",
  "Restaurado às {time} · {name}": "Restored at {time} · {name}",
  "Salvar": "Save",
  "Salvar item": "Save item",
  "Salvar snippet": "Save snippet",
  "Salvo": "Saved",
  "Salvo às {time} · {name}": "Saved at {time} · {name}",
  "Salvo.": "Saved.",
  "Selecione um item na lista ou crie um novo.": "Select an item in the list or create a new one.",
  "Selecione um texto na lista ou crie um novo.": "Select a text in the list or create a new one.",
  "Seções": "Sections",
  "Siga o tema do Windows ou escolha um fixo.": "Follow the Windows theme or choose a fixed one.",
  "Sistema": "System",
  "Snippets dinâmicos, formulários, grupos e backups continuam no gerenciador clássico por enquanto.":
    "Dynamic snippets, forms, groups and backups stay in the classic manager for now.",
  "Texto": "Text",
  "Textos": "Texts",
  "Tipo criado às {time} · {name}": "Type created at {time} · {name}",
  "Tipo de mapeamento": "Mapping type",
  "Tipo excluído às {time} · {name}": "Type deleted at {time} · {name}",
  "Toque": "Touch",
  "Trigger": "Trigger",
  "Um snippet dinâmico usa este trigger e tem prioridade.": "A dynamic snippet uses this trigger and takes priority.",
  "Valor": "Value",
  "Variáveis como %%clipboard-paste%% são resolvidas na expansão.":
    "Variables such as %%clipboard-paste%% are resolved on expansion.",
  "desativado": "disabled",
  "formatado": "formatted",
  "novo item": "new item",
  "novo snippet": "new snippet",
  "sombreado": "shadowed",
  "{name} em {type}": "{name} in {type}",
  "{name} tem alterações que ainda não foram salvas.": "{name} has changes that have not been saved yet.",
  "{shown} de {total}": "{shown} of {total}",
  "{total} itens": "{total} items",
  "{total} textos": "{total} texts",
};

let catalog: Record<string, string> = {};

export function setLanguage(code: string): void {
  catalog = code === "en-US" ? EN_US : {};
}

/** Translate a Portuguese message id and fill its `{name}` placeholders. */
export function t(message: string, values: Record<string, string | number> = {}): string {
  const text = catalog[message] ?? message;
  return text.replace(/\{(\w+)\}/g, (match, key: string) => (key in values ? String(values[key]) : match));
}
