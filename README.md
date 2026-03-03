# Text Expander – Snippets para Windows com System Tray

Aplicativo em Python para Windows que expande **snippets de texto** em qualquer campo de digitação, similar ao TextExpander/Espanso, com:

- Ícone na bandeja do sistema (System Tray)
- Snippets estáticos salvos em `snippets.json`
- Snippets dinâmicos (datas, indicadores BCB, ações B3/US via yfinance)
- GUI completa em Tkinter para gerenciar:
  - Snippets estáticos
  - Mapeamentos dinâmicos (CPF, CNPJ, CGE e tipos personalizados)
- Execução de snippets “lentos” (consultas financeiras) em **threads**, sem travar a digitação

> ⚠ Uso pessoal. O programa **não registra** teclas digitadas; apenas observa os últimos caracteres digitados para expandir os triggers.

---

## 1. Estrutura do projeto

Arquivos principais:

- `txt_xpander.pyw`  
  Versão principal executável em background, sem console (recomendada para uso diário).

- `txt_xpander.py`  
  Versão com console, útil para debug/log.

- `run_txt_xpanderw.bat`  
  Arquivo para iniciar o Text Expander com dupla-clique (detalhes abaixo).

- `bcb_consultor.py`  
  Consulta indicadores econômicos do BCB (Dólar, Selic, IPCA, CDI etc.).

- `yf_stocks.py`  
  Implementa `B3FundamentosConsultor` para cotações e fundamentos via `yfinance`.

- `snippets.json`  
  Armazena snippets estáticos e mapeamentos dinâmicos.

## 2. Instalação

### 2.1 Requisitos

- Windows 10 ou superior
- Python 3.9+ instalado e no PATH

### 2.2 Instalação das dependências

pip install -r requirements.txt

### 2.3 Execução

#### Opção A – Modo padrão (com console)

python txt_xpander.py

#### Opção B – Modo silencioso com `.pyw` (recomendado)

Clique duas vezes em:

run_txt_xpanderw.bat

## 3. Arquivo `run_txt_xpanderw.bat`

O projeto inclui um arquivo para facilitar a execução do expansor no modo silencioso (**pythonw**), sem abrir terminal.

### O que esse arquivo faz:

1. Garante que está rodando na mesma pasta do projeto.
2. Confirma se o **Python está instalado**.
3. Verifica se o arquivo `txt_xpander.pyw` existe.
4. Confere se as dependências básicas estão instaladas.
5. Caso faltem, instala automaticamente (`pynput`, `pystray`, `Pillow`).
6. Inicia o expansor usando **pythonw**, sem terminal.
7. Fecha a janela automaticamente após 2 segundos.

### Vantagens

* Executa o Text Expander de forma limpa e invisível.
* Útil para criar um **atalho na área de trabalho** ou colocar no **Startup do Windows**.

Para iniciar automaticamente no login:

1. Pressione `Win + R`
2. Digite: shell:startup
3. Coloque um atalho do arquivo `run_txt_xpanderw.bat` dentro dessa pasta.

## 4. Snippets estáticos

Snippets estáticos são pares `trigger → texto` definidos em `snippets.json` ou pela GUI.

Exemplo simples de `snippets.json`:

```json
{
  "xname": "Seu Nome",
  "xemail": "seu.email@exemplo.com"
}
```

Uso:

* Digite `xname` em qualquer campo de texto
* O programa apaga `xname` e digita `Seu Nome`

Pontos importantes:

* Triggers **não podem** começar com `_` (prefixo reservado para mapeamentos dinâmicos).
* Na GUI, use a aba **“Snippets Estáticos”** para:

  * Criar novos snippets
  * Editar gatilhos e textos
  * Excluir snippets

## 5. Mapeamentos dinâmicos (cpf, cnpj, etc.)

Além dos snippets simples, o programa suporta **mapeamentos dinâmicos**, úteis para grupos de dados do mesmo tipo:

* CPFs
* CNPJs
* Códigos internos (CGE)
* E tipos customizados (e-mails, contas bancárias, etc.)

### 5.1. Estrutura em `snippets.json`

```json
{
  "_cpf_numbers": {
    "fulano": "123.456.789-00",
    "ciclano": "987.654.321-00"
  },
  "_cnpj_numbers": {
    "empresa1": "12.345.678/0001-90"
  }
}
```

Com isso:

* Digitar `cpffulano` expande para `123.456.789-00`
* Digitar `cnpjempresa1` expande para `12.345.678/0001-90`

O mapeamento é:

* chave interna começando com `_` (ex.: `_cpf_numbers`)
* prefixo de uso: `cpf`, `cnpj`, `cge`, etc.

### 5.2. Criando tipos customizados pela GUI

Na aba **“Mapeamentos Dinâmicos”** da GUI você pode:

* Selecionar tipos existentes (`CPF`, `CNPJ`, `CGE`)
* Criar novos tipos:

  * Ex.: tipo `email`, prefixo `email`
  * Depois, cadastrar itens como:

    * `trabalho` → `seu.email@empresa.com`
    * `pessoal` → `seu.email@gmail.com`
  * Uso: `emailtrabalho`, `emailpessoal`

Os tipos customizados são gravados em `snippets.json` como:

```json
"_email_codes": {
  "trabalho": "seu.email@empresa.com",
  "pessoal": "seu.email@gmail.com"
}
```

## 6. Snippets dinâmicos de data e indicadores (BCB)

Alguns gatilhos já vêm embutidos no código:

* Datas:

  * `xhj` → data atual `dd/mm/aaaa`
  * `xhoje` → data por extenso
  * `xnow` → hora atual `HH:MM:SS`
  * `xdatahora` → data e hora

* Indicadores do Banco Central (via `BCBConsultor`):

  * `xdolar`
  * `xselic`
  * `xipcam`
  * `xipca12`
  * `xcdi`
  * `xptax`
  * `xeconomia`

Esses snippets são funções Python e **não aparecem** em `snippets.json`.

---

## 7. Snippets de ações (B3 / US) – “lentos”

Snippets que pedem ticker e consultam `yfinance` são tratados como “lentos” e executados em **thread separada** para não bloquear a digitação:

Principais:

* `xcot`      → Cotação
* `xcap`      → Market Cap
* `xdy`       → Dividend Yield
* `xpl`       → P/L
* `xpvp`      → P/VP
* `xebt`      → EBITDA
* `xmarg`     → Margem líquida
* `xroe`      → ROE
* `xdivt`     → Dívida total
* `xdivl`     → Dívida líquida
* `xcaixa`    → Caixa
* `xvol`      → Volume médio
* `xrec`      → Receita líquida
* `xbeta`     → Beta
* `x52w`      → Máx/Mín 52 semanas
* `xfund`     → Resumo “estilo Bloomberg” com os principais fundamentos

Fluxo:

1. Digite, por exemplo, `xfund`
2. O expansor apaga `xfund`
3. Abre uma caixa de input pedindo o ticker (`PETR4`, `ITUB4`, `AAPL`, etc.)
4. Consulta `yfinance` via `B3FundamentosConsultor`
5. Digita o resumo formatado na posição atual do cursor

O modo BR/US (vírgula vs ponto, R$ vs $) é tratado dentro da classe `B3FundamentosConsultor`.

## 8. Segurança e limitações

* Projetado para uso em **Windows**.
* Foi testado com aplicativos comuns (navegadores, VS Code, Word, etc.).
  Alguns aplicativos com proteção especial de entrada podem exigir execução “como Administrador”.
* O programa não intercepta combinações de teclas para controle remoto; apenas observa os últimos caracteres digitados para comparar com triggers.


## 9. Desenvolvimento e customização

Pontos de extensão:

* Adicionar novos snippets dinâmicos em `get_dynamic_snippets()`
* Criar novos tipos de mapeamentos na aba “Mapeamentos Dinâmicos”
* Ajustar ou acrescentar novos indicadores/consultas em:

  * `bcb_consultor.py`
  * `yf_stocks.py` (classe `B3FundamentosConsultor`)

Sugestões de melhorias futuras:

* Opção de importar/exportar snippets em outros formatos
* Suporte a perfis diferentes de snippets
* Configuração de hotkey global para ativar/desativar o expansor


## 10. Execução em modo debug

Para acompanhar o comportamento em tempo real (gatilhos, snippet acionado, erros), execute o script pelo terminal/PowerShell:

python txt_xpander.py


As mensagens de log aparecem no console, incluindo:

* Snippets carregados
* Tickers digitados
* Erros ao consultar APIs
* Avisos sobre permissões de administrador

## `requirements.txt`

pynput>=1.7.0
pystray>=0.19.0
Pillow>=10.0.0
yfinance>=0.2.40
