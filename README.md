# NF — Sistema de emissão de notas fiscais

Sistema local (offline-first) para emissão de NF-e e NFC-e com despacho por
e-mail e WhatsApp.

## Como funciona

- **Roda 100% local**: servidor web em Python que abre no navegador
  (`http://localhost:8000`). Cadastros e notas ficam num banco **SQLite** no
  próprio computador — tudo funciona sem internet.
- **Fila off-line**: ao emitir uma nota sem conexão, ela entra na fila com
  status `PENDENTE`. Um worker verifica a conectividade a cada 10 segundos e,
  quando a internet volta, transmite as notas na ordem em que foram criadas.
  Cancelamento, carta de correção e inutilização de numeração usam a mesma fila.
  O processamento é serializado (lock) com "claim" atômico por item — nem duas
  passadas simultâneas transmitem a mesma nota — e itens interrompidos no meio
  da transmissão voltam à fila sozinhos. Após 10 falhas de comunicação o item é
  marcado como rejeitado com o motivo.
- **Numeração fiscal segura**: rascunhos não recebem número; o número da série
  é reservado de forma atômica só no momento de emitir (um índice único em
  `(modelo, série, número)` impede duplicidade). Criações rejeitadas não pulam
  a sequência. Cada nota tem uma referência única (UUID) usada junto ao
  provedor, o que evita colisões mesmo após restaurar um backup.
- **Emissão por provedor**: a comunicação com a SEFAZ é feita por uma API de
  emissão (Focus NFe), que cuida do certificado digital A1, assinatura do XML e
  contingência. Há também um **modo simulado** para testar todo o fluxo sem
  certificado ou credenciais (gera chave de acesso e DANFE sem validade fiscal).
- **Despacho**: quando a nota é autorizada, o sistema salva o XML autorizado e
  o **DANFE oficial do provedor** (quando disponível; no modo simulado gera um
  PDF local sem validade fiscal) e envia os dois por e-mail (SMTP). O WhatsApp
  pode ser assistido (`wa.me`, com o PDF anexado manualmente) ou automático
  (Cloud API — somente texto, sem promessa de anexo).
- **NFC-e (modelo 65)**: venda no balcão, consumidor opcional, forma de
  pagamento, cupom térmico 80 mm com QR Code e envio ESC/POS para impressora
  de rede. NFC-e não admite carta de correção — cancele e emita outra.
- **Contabilidade**: ZIP com os XMLs do mês (notas, eventos e inutilizações)
  e inutilização de faixas puladas da série.
- **Acesso**: senha opcional (um usuário). Enquanto estiver vazia, o painel
  abre sem login.

## Executando

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Abra http://localhost:8000 no navegador.

```bash
PYTHONPATH=. python3 -m pytest tests/ -q
```

### Primeiros passos

1. Em **Configurações**, preencha os dados do emitente (razão social e CNPJ são
   obrigatórios para emitir). O CNPJ/CPF é validado no cadastro. Opcionalmente
   configure SMTP, senha de acesso, impressora térmica e WhatsApp Cloud API.
2. Cadastre **clientes** (com e-mail e WhatsApp para o despacho) e **produtos**
   (descrição, NCM, CFOP, CSOSN, unidade e preço). Cadastre o CFOP da operação
   habitual: na emissão o primeiro dígito se ajusta sozinho à UF do cliente
   (5xxx venda interna, 6xxx interestadual; NFC-e é sempre interna).
3. Em **Nova nota**, escolha o cliente, adicione os itens e clique em
   **Emitir nota**. Sem internet, a nota fica na fila e é transmitida sozinha
   quando a conexão voltar.
4. Para venda no caixa, use **NFC-e (balcão)**: produtos, pagamento e CPF
   opcional. O PDF do cupom abre em 80 mm; com o IP da impressora, use
   **Imprimir** (ESC/POS).
5. Em **Contabilidade**, baixe o ZIP do mês para o contador e inutilize
   números pulados da série.

### Emissão real (Focus NFe)

1. Crie uma conta em [focusnfe.com.br](https://focusnfe.com.br), envie o
   certificado digital A1 da empresa no painel deles e gere um token de API.
2. Em **Configurações → Emissão**, selecione o provedor *Focus NFe*, escolha o
   ambiente (comece por *homologação*) e cole o token.
3. O payload envia `data_emissao`, número/série locais, CSOSN por item (do
   cadastro do produto), IE e indicador de contribuinte do destinatário e as
   observações da nota. NFC-e é tratada como síncrona (`local_destino` interno).
   Respostas 4xx do provedor rejeitam a nota com a mensagem retornada; 5xx/429
   devolvem à fila. **Importante**: valide o fluxo completo em homologação
   (com o seu contador) antes de emitir em produção.

## Estrutura do projeto

```
app/
  main.py                  # aplicação FastAPI + páginas + login
  database.py              # SQLite local (pasta dados/)
  models.py                # clientes, produtos, notas, eventos, inutilizações
  routers/                 # API REST
  services/
    fila.py                # worker da fila off-line (notas, eventos, inutilização)
    backup.py              # backup automático do banco e arquivos
    danfe.py / danfe_nfce.py  # DANFE A4 e cupom NFC-e 80 mm
    escpos.py              # cupom térmico ESC/POS
    email_sender.py        # envio SMTP com PDF + XML anexos
    whatsapp.py            # wa.me e WhatsApp Cloud API
    documentos.py          # validação de CPF/CNPJ
    auth.py                # senha local (PBKDF2) e sessão
    contabilidade.py       # ZIP XML do mês
    emissores/             # provedores de emissão (simulado, Focus NFe)
  templates/ + static/     # interface web local (sem CDN, funciona off-line)
dados/                     # criado em runtime: nf.db, PDFs/XMLs e backups
```

## Ciclo de vida da nota

```
RASCUNHO (sem número) → PENDENTE (número reservado) → PROCESSANDO → AUTORIZADA → CANCELADA
                                                        ↘ REJEITADA (Corrigir e reemitir)
Falha de rede durante a transmissão devolve a nota (ou o evento) para PENDENTE.
```

Notas `RASCUNHO` ou `REJEITADA` têm o botão **Corrigir** (NF-e): abre a tela de
edição com cliente, itens, desconto e observações para ajustar e reemitir.

Na nota autorizada você pode:

- **Cancelar**, com justificativa de no mínimo 15 caracteres. Sem internet, o pedido fica na fila. Ao autorizar, abre o WhatsApp com a mensagem de cancelamento (se o cliente tiver número).
- **Emitir carta de correção (CC-e)** na NF-e (não vale para NFC-e). Também gera link de WhatsApp com o texto da correção.
- **Duplicar** como rascunho para repetir uma venda.
- **Imprimir** o cupom ESC/POS (rede, porta 9100) ou baixar o arquivo `.bin`.

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
