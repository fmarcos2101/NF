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
  (número da nota, valor e chave de acesso); basta clicar, anexar o PDF e
  enviar. A camada é isolada, então dá para trocar depois por envio automático
  via WhatsApp Business API sem mexer no resto.

## Executando

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Abra http://localhost:8000 no navegador.

### Primeiros passos

1. Em **Configurações**, preencha os dados do emitente (razão social e CNPJ são
   obrigatórios). Opcionalmente configure o SMTP para envio automático por
   e-mail.
2. Cadastre **clientes** (com e-mail e WhatsApp para o despacho) e **produtos**
   (descrição, NCM, CFOP, unidade e preço).
3. Em **Nova nota**, escolha o cliente, adicione os itens e clique em
   **Emitir nota**. Sem internet, a nota fica na fila e é transmitida sozinha
   quando a conexão voltar.

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
    fila.py                # worker da fila off-line
    danfe.py               # geração do DANFE (PDF)
    email_sender.py        # envio SMTP com PDF + XML anexos
    whatsapp.py            # link wa.me com mensagem pronta
    emissores/             # provedores de emissão (simulado, Focus NFe)
  templates/ + static/     # interface web local (sem CDN, funciona off-line)
dados/                     # criado em runtime: nf.db + PDFs/XMLs das notas
```

## Ciclo de vida da nota

```
RASCUNHO → PENDENTE → PROCESSANDO → AUTORIZADA
                        ↘ REJEITADA (corrigir e reemitir)
Falha de rede durante a transmissão devolve a nota para PENDENTE.
```

## Stack

- **Python 3.12 + FastAPI** — API e páginas.
- **SQLite (SQLAlchemy)** — banco local, sem servidor.
- **fpdf2** — geração do DANFE em PDF.
- **httpx** — chamadas à API de emissão e teste de conectividade.
- Frontend em HTML/CSS/JS puro servido localmente (sem CDN — a interface abre
  mesmo sem internet).
