# NF — Sistema de emissão de notas fiscais

Sistema local (offline-first) para emissão de NF-e com despacho automático por
e-mail e envio assistido por WhatsApp.

## Como funciona

- **Roda 100% local**: servidor web em Python que abre no navegador
  (`http://localhost:8000`). Cadastros e notas ficam num banco **SQLite** no
  próprio computador — tudo funciona sem internet.
- **Fila off-line**: ao emitir uma nota sem conexão, ela entra na fila com
  status `PENDENTE`. Um worker verifica a conectividade a cada 10 segundos e,
  quando a internet volta, transmite as notas na ordem em que foram criadas.
- **Emissão por provedor**: a comunicação com a SEFAZ é feita por uma API de
  emissão (Focus NFe), que cuida do certificado digital A1, assinatura do XML e
  contingência. Há também um **modo simulado** para testar todo o fluxo sem
  certificado ou credenciais (gera chave de acesso e DANFE sem validade fiscal).
- **Despacho automático**: quando a nota é autorizada, o sistema gera o DANFE
  (PDF), salva o XML e envia os dois por e-mail (SMTP) para o cliente.
- **WhatsApp sem API**: o sistema gera um link `wa.me` com a mensagem pronta
  (emissão, cancelamento ou carta de correção); basta clicar, anexar o PDF e
  enviar. A camada é isolada, então dá para trocar depois por envio automático
  via WhatsApp Business API sem mexer no resto.
- **NFC-e (modelo 65)**: venda no balcão, consumidor opcional, forma de
  pagamento e cupom térmico 80 mm com QR Code. NFC-e não admite carta de
  correção — cancele e emita outra.

## Executando

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Abra http://localhost:8000 no navegador.

Para conferir o fluxo de eventos e o backup:

```bash
PYTHONPATH=. python3 -m unittest tests.test_eventos tests.test_nfce -v
```

### Primeiros passos

1. Em **Configurações**, preencha os dados do emitente (razão social e CNPJ são
   obrigatórios). Opcionalmente configure o SMTP para envio automático por
   e-mail.
2. Cadastre **clientes** (com e-mail e WhatsApp para o despacho) e **produtos**
   (descrição, NCM, CFOP, unidade e preço).
3. Em **Nova nota**, escolha o cliente, adicione os itens e clique em
   **Emitir nota**. Sem internet, a nota fica na fila e é transmitida sozinha
   quando a conexão voltar.
4. Para venda no caixa, use **NFC-e (balcão)**: produtos, pagamento e CPF
   opcional. O PDF do cupom abre em 80 mm para imprimir.

### Emissão real (Focus NFe)

1. Crie uma conta em [focusnfe.com.br](https://focusnfe.com.br), envie o
   certificado digital A1 da empresa no painel deles e gere um token de API.
2. Em **Configurações → Emissão**, selecione o provedor *Focus NFe*, escolha o
   ambiente (comece por *homologação*) e cole o token.

## Estrutura do projeto

```
app/
  main.py                  # aplicação FastAPI + páginas
  database.py              # SQLite local (pasta dados/)
  models.py                # clientes, produtos, notas, itens, configurações
  routers/                 # API REST (clientes, produtos, notas, configurações)
  services/
    fila.py                # worker da fila off-line (notas e eventos)
    backup.py              # backup automático do banco e arquivos
    danfe.py / danfe_nfce.py  # DANFE A4 e cupom NFC-e 80 mm
    email_sender.py        # envio SMTP com PDF + XML anexos
    whatsapp.py            # link wa.me com mensagem pronta
    emissores/             # provedores de emissão (simulado, Focus NFe)
  templates/ + static/     # interface web local (sem CDN, funciona off-line)
dados/                     # criado em runtime: nf.db, PDFs/XMLs e backups
```

## Ciclo de vida da nota

```
RASCUNHO → PENDENTE → PROCESSANDO → AUTORIZADA → CANCELADA
                        ↘ REJEITADA (corrigir e reemitir)
Falha de rede durante a transmissão devolve a nota (ou o evento) para PENDENTE.
```

Na nota autorizada você pode:

- **Cancelar**, com justificativa de no mínimo 15 caracteres. Sem internet, o pedido fica na fila. Ao autorizar, abre o WhatsApp com a mensagem de cancelamento (se o cliente tiver número).
- **Emitir carta de correção (CC-e)** na NF-e (não vale para NFC-e). Também gera link de WhatsApp com o texto da correção.
- **Duplicar** como rascunho para repetir uma venda.

## O que ainda falta (opcional, para produção)

O ciclo operacional está fechado: emitir NF-e/NFC-e, fila off-line, cancelar, CC-e, e-mail, WhatsApp assistido e backup.

Restam **5 passos** se quiser deixar o sistema mais redondo no dia a dia:

1. **Pacote XML do mês para o contador** (ZIP com as notas do período).
2. **Inutilização de numeração** (quando um número da série é pulado).
3. **Validação de CPF/CNPJ** no cadastro.
4. **Login simples** para proteger o painel na rede local.
5. **Impressão térmica direta (ESC/POS)** e/ou **WhatsApp Business API** (envio sem clicar). O cupom 80 mm já imprime pelo PDF; o `wa.me` já cobre o aviso manual.

## Backup automático

A cada 24 horas (e na primeira subida do dia) o sistema gera um ZIP em
`dados/backups/` com o banco SQLite e os XMLs/PDFs. Os 14 mais recentes são
mantidos. Em **Configurações** dá para gerar e baixar na hora. Para restaurar,
pare o sistema e extraia o ZIP sobre a pasta `dados/`.

## Stack

- **Python 3.12 + FastAPI** — API e páginas.
- **SQLite (SQLAlchemy)** — banco local, sem servidor.
- **fpdf2** — geração do DANFE em PDF.
- **httpx** — chamadas à API de emissão e teste de conectividade.
- Frontend em HTML/CSS/JS puro servido localmente (sem CDN — a interface abre
  mesmo sem internet).
