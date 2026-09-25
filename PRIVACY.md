# SnipType Privacy Policy

Effective date: 2026-09-25. [Versão em português abaixo](#política-de-privacidade-do-sniptype).

SnipType is a text expander for Windows published by Strateo. It runs on your
device and has no accounts, no servers, no analytics and no telemetry. Strateo
does not receive any data from the app.

## Keyboard input

To expand snippets, SnipType watches what you type system-wide. The keys it
observes are compared, in memory, against your own snippet triggers and
shortcuts. They are never written to disk, logged, or sent anywhere.

SnipType cannot yet tell password fields apart from other fields. If you type
a trigger in a password field, it will expand there too. Nothing typed is
recorded in either case.

## Clipboard

Most expansions paste the snippet through the clipboard and then put back the
text that was there before. Other clipboard content, such as images, is not
restored. Snippets that use the clipboard variable read the current
clipboard content to insert it. The clipboard content stays on your device.

## Data stored on your device

Everything SnipType keeps is stored locally in `%USERPROFILE%\.sniptype`:

- your snippet library (`snippets.json`) and settings (`settings.json`);
- rotating backups of the library;
- logs of app events and errors. Logs can include file paths and, when an
  expansion fails, the trigger name. They never contain typed text or snippet
  content.

Uninstalling SnipType leaves this folder in place so your library survives a
reinstall. Delete the folder to remove all of it.

If you set the optional `mirror_dir` or `sync_export_dir` settings, SnipType
copies your library, in plain text, to the folder you chose. If that folder is
synchronized by a cloud service, that service's privacy terms apply to the
copy.

## Network access

SnipType connects to the internet only when you use a snippet that needs it:

| Feature | Service | What is sent |
|---|---|---|
| Central Bank indicators | Banco Central do Brasil (`api.bcb.gov.br`, `olinda.bcb.gov.br`) | The requested series and date |
| Stock data | Yahoo Finance, via the open-source yfinance library | The requested ticker symbol |
| WhatsApp actions | Opens `wa.me` in your default browser | The phone number and message you entered |

As with any internet request, those services also receive your IP address and
standard request details. Their own privacy policies apply. SnipType sends none
of your snippets or typed text to them.

## Microsoft Store

If you install SnipType from the Microsoft Store, Microsoft may collect install
and crash data under the
[Microsoft Privacy Statement](https://privacy.microsoft.com/privacystatement)
and share aggregate reports with Strateo. SnipType itself adds nothing to that
data.

## Children

SnipType is a general-purpose productivity tool and is not directed at
children.

## Changes and contact

Changes to this policy are published in this file, with a new effective date.
Questions: open an issue at <https://github.com/rteoo/sniptype/issues>.

---

## Política de privacidade do SnipType

Vigente desde 25/09/2026.

O SnipType é um expansor de texto para Windows publicado pela Strateo. Ele roda
no seu computador e não tem contas, servidores, análises de uso nem telemetria.
A Strateo não recebe nenhum dado do aplicativo.

### Entrada do teclado

Para expandir snippets, o SnipType acompanha o que você digita em qualquer
aplicativo. As teclas são comparadas, em memória, com os seus próprios gatilhos
e atalhos. Elas nunca são gravadas em disco, registradas em log nem enviadas a
lugar nenhum.

O SnipType ainda não distingue campos de senha dos demais. Se você digitar um
gatilho em um campo de senha, ele também será expandido ali. Em nenhum dos
casos o que você digita é registrado.

### Área de transferência

A maioria das expansões cola o snippet pela área de transferência e depois
devolve o texto que estava lá antes. Outros conteúdos, como imagens, não são
restaurados. Snippets que usam a variável de área de
transferência leem o conteúdo atual para inseri-lo. Esse conteúdo não sai do
seu computador.

### Dados guardados no seu computador

Tudo o que o SnipType guarda fica em `%USERPROFILE%\.sniptype`:

- sua biblioteca de snippets (`snippets.json`) e as configurações
  (`settings.json`);
- backups rotativos da biblioteca;
- logs de eventos e erros do aplicativo. Os logs podem conter caminhos de
  arquivo e, quando uma expansão falha, o nome do gatilho. Nunca contêm texto
  digitado nem o conteúdo dos snippets.

Desinstalar o SnipType mantém essa pasta, para que sua biblioteca sobreviva a
uma reinstalação. Para apagar tudo, exclua a pasta.

Se você ativar as configurações opcionais `mirror_dir` ou `sync_export_dir`, o
SnipType copia sua biblioteca, em texto puro, para a pasta escolhida. Se essa
pasta for sincronizada por um serviço de nuvem, a cópia fica sujeita aos termos
de privacidade desse serviço.

### Acesso à internet

O SnipType só se conecta à internet quando você usa um snippet que precisa
disso:

| Recurso | Serviço | O que é enviado |
|---|---|---|
| Indicadores do Banco Central | Banco Central do Brasil (`api.bcb.gov.br`, `olinda.bcb.gov.br`) | A série e a data consultadas |
| Dados de ações | Yahoo Finance, pela biblioteca de código aberto yfinance | O código da ação consultada |
| Ações do WhatsApp | Abre `wa.me` no seu navegador padrão | O número e a mensagem que você informou |

Como em qualquer acesso à internet, esses serviços também recebem seu endereço
IP e os dados técnicos usuais da requisição, e valem as políticas de
privacidade deles. O SnipType não envia a eles seus snippets nem o que você
digita.

### Microsoft Store

Se você instalar o SnipType pela Microsoft Store, a Microsoft pode coletar
dados de instalação e de falhas conforme a
[Declaração de Privacidade da Microsoft](https://privacy.microsoft.com/pt-br/privacystatement)
e compartilhar relatórios agregados com a Strateo. O SnipType não acrescenta
nada a esses dados.

### Crianças

O SnipType é uma ferramenta de produtividade de uso geral e não é direcionado
a crianças.

### Alterações e contato

Alterações nesta política são publicadas neste arquivo, com nova data de
vigência. Dúvidas: abra uma issue em <https://github.com/rteoo/sniptype/issues>.
