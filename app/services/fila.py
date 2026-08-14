"""Fila de emissão e eventos off-line.

As notas e os eventos (cancelamento, carta de correção, inutilização) são
gravados primeiro no banco local. Um worker verifica a conectividade
periodicamente e, quando há internet, transmite na ordem de criação. Falhas de
rede devolvem o item à fila. Após a autorização, o DANFE é gerado e o e-mail é
despachado sozinho.

Garantias de consistência:

- ``processar_fila`` roda sob um lock de processo: o worker e os endpoints
  manuais nunca processam em paralelo.
- Cada item é "reivindicado" com um UPDATE condicional (PENDENTE →
  PROCESSANDO); mesmo que duas passadas concorram, só uma transmite.
- Itens presos em PROCESSANDO (queda do processo no meio da transmissão)
  voltam à fila na passada seguinte.
- Depois de ``MAX_TENTATIVAS`` falhas de comunicação, o item é marcado como
  rejeitado com o motivo, em vez de tentar para sempre.
"""
import asyncio
import logging
import threading
import time
from datetime import datetime

import httpx

from ..database import ARQUIVOS_DIR, SessionLocal
from ..models import (
    Inutilizacao,
    Nota,
    NotaEvento,
    StatusEvento,
    StatusInutilizacao,
    StatusNota,
    TipoEvento,
)
from . import backup as svc_backup
from . import config as cfg
from .danfe import gerar_documento
from .email_sender import enviar_cancelamento_por_email, enviar_nota_por_email, smtp_configurado
from .emissores import obter_emissor
from .emissores.base import ErroComunicacao
from .whatsapp import tentar_enviar_cloud

log = logging.getLogger("nf.fila")

INTERVALO_SEGUNDOS = 10
CACHE_CONECTIVIDADE_SEGUNDOS = 15
URL_TESTE_CONEXAO = "https://www.gstatic.com/generate_204"
MAX_TENTATIVAS = 10

_estado = {"online": False, "verificado_em": 0.0}
_lock = threading.Lock()


def esta_online(forcar: bool = False) -> bool:
    """Verifica conectividade com cache curto para não custar em cada request."""
    agora = time.monotonic()
    if not forcar and agora - _estado["verificado_em"] < CACHE_CONECTIVIDADE_SEGUNDOS:
        return _estado["online"]
    try:
        httpx.head(URL_TESTE_CONEXAO, timeout=3)
        _estado["online"] = True
    except httpx.HTTPError:
        _estado["online"] = False
    _estado["verificado_em"] = agora
    return _estado["online"]


def _reivindicar_nota(db, nota_id: int) -> bool:
    """PENDENTE → PROCESSANDO de forma atômica; False se outro já pegou."""
    linhas = (
        db.query(Nota)
        .filter(Nota.id == nota_id, Nota.status == StatusNota.PENDENTE)
        .update(
            {Nota.status: StatusNota.PROCESSANDO, Nota.tentativas: Nota.tentativas + 1},
            synchronize_session=False,
        )
    )
    db.commit()
    return linhas == 1


def _reivindicar_evento(db, evento_id: int) -> bool:
    linhas = (
        db.query(NotaEvento)
        .filter(NotaEvento.id == evento_id, NotaEvento.status == StatusEvento.PENDENTE)
        .update(
            {
                NotaEvento.status: StatusEvento.PROCESSANDO,
                NotaEvento.tentativas: NotaEvento.tentativas + 1,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return linhas == 1


def _reivindicar_inutilizacao(db, item_id: int) -> bool:
    linhas = (
        db.query(Inutilizacao)
        .filter(
            Inutilizacao.id == item_id,
            Inutilizacao.status == StatusInutilizacao.PENDENTE,
        )
        .update(
            {
                Inutilizacao.status: StatusInutilizacao.PROCESSANDO,
                Inutilizacao.tentativas: Inutilizacao.tentativas + 1,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return linhas == 1


def _recuperar_travados(db) -> None:
    """Itens presos em PROCESSANDO (queda do processo) voltam para a fila.

    Só roda dentro do lock: nesse momento nenhum item está sendo transmitido
    por este processo, então qualquer PROCESSANDO é resto de uma queda.
    """
    n = (
        db.query(Nota)
        .filter(Nota.status == StatusNota.PROCESSANDO)
        .update({Nota.status: StatusNota.PENDENTE}, synchronize_session=False)
    )
    e = (
        db.query(NotaEvento)
        .filter(NotaEvento.status == StatusEvento.PROCESSANDO)
        .update({NotaEvento.status: StatusEvento.PENDENTE}, synchronize_session=False)
    )
    i = (
        db.query(Inutilizacao)
        .filter(Inutilizacao.status == StatusInutilizacao.PROCESSANDO)
        .update(
            {Inutilizacao.status: StatusInutilizacao.PENDENTE},
            synchronize_session=False,
        )
    )
    db.commit()
    if n or e or i:
        log.warning(
            "Recuperados da interrupção: %s nota(s), %s evento(s), %s inutilização(ões)",
            n, e, i,
        )


def _finalizar_autorizacao(db, nota: Nota, resultado, emitente: dict[str, str]) -> None:
    nota.status = StatusNota.AUTORIZADA
    nota.chave_acesso = resultado.chave_acesso
    nota.protocolo = resultado.protocolo
    nota.autorizada_em = datetime.now()
    nota.ultimo_erro = ""
    if getattr(resultado, "qrcode_url", ""):
        nota.qrcode_url = resultado.qrcode_url
    elif getattr(nota, "modelo", 55) == 65 and resultado.chave_acesso:
        nota.qrcode_url = (
            "https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx"
            f"?tipoConsulta=completa&nfe={resultado.chave_acesso}"
        )

    try:
        if resultado.xml:
            xml_path = ARQUIVOS_DIR / f"nota-{nota.id}.xml"
            xml_path.write_text(resultado.xml, encoding="utf-8")
            nota.xml_path = str(xml_path)
    except OSError as exc:
        log.exception("Falha ao gravar XML da nota %s", nota.id)
        nota.ultimo_erro = f"XML: {exc}"

    pdf_path = ARQUIVOS_DIR / f"nota-{nota.id}.pdf"
    try:
        danfe_oficial = getattr(resultado, "danfe_pdf", b"")
        if danfe_oficial:
            # DANFE/DANFCe oficial do provedor: é o documento fiscalmente válido.
            pdf_path.write_bytes(danfe_oficial)
        else:
            gerar_documento(nota, emitente, str(pdf_path))
        nota.pdf_path = str(pdf_path)
    except Exception as exc:  # PDF não pode impedir a autorização
        log.exception("Falha ao gerar DANFE da nota %s", nota.id)
        nota.ultimo_erro = f"DANFE: {exc}"

    db.commit()

    if nota.cliente and nota.cliente.email and smtp_configurado(emitente):
        try:
            enviar_nota_por_email(nota, emitente)
            nota.email_enviado_em = datetime.now()
        except Exception as exc:
            log.warning("Falha ao enviar e-mail da nota %s: %s", nota.id, exc)
            nota.ultimo_erro = f"E-mail: {exc}"
        db.commit()

    envio = tentar_enviar_cloud(nota, emitente, tipo="emissao")
    if envio and not envio.get("enviado") and envio.get("motivo") != "Cliente sem WhatsApp.":
        nota.ultimo_erro = f"WhatsApp: {envio.get('motivo', '')}"[:500]
        db.commit()


def _falha_comunicacao(db, obj, campo_status, status_pendente, status_rejeitado, exc) -> None:
    """Devolve o item à fila ou o rejeita ao estourar o limite de tentativas."""
    if obj.tentativas >= MAX_TENTATIVAS:
        setattr(obj, campo_status, status_rejeitado)
        obj.motivo_rejeicao = (
            f"Falha de comunicação após {obj.tentativas} tentativas: {exc}"
        )
        log.warning("Item %s rejeitado por excesso de tentativas: %s", obj.id, exc)
    else:
        setattr(obj, campo_status, status_pendente)
    obj.ultimo_erro = str(exc)
    db.commit()


def processar_nota(db, nota: Nota) -> None:
    emitente = cfg.obter_todas(db)
    emissor = obter_emissor(db)

    try:
        resultado = emissor.emitir(nota, emitente)
    except ErroComunicacao as exc:
        _falha_comunicacao(db, nota, "status", StatusNota.PENDENTE, StatusNota.REJEITADA, exc)
        log.info("Nota %s voltou à fila: %s", nota.id, exc)
        return
    except Exception as exc:
        _falha_comunicacao(db, nota, "status", StatusNota.PENDENTE, StatusNota.REJEITADA, exc)
        log.exception("Erro inesperado ao emitir nota %s", nota.id)
        return

    if resultado.autorizada:
        _finalizar_autorizacao(db, nota, resultado, emitente)
        log.info("Nota %s autorizada (chave %s)", nota.id, nota.chave_acesso)
    else:
        nota.status = StatusNota.REJEITADA
        nota.motivo_rejeicao = resultado.motivo
        db.commit()
        log.info("Nota %s rejeitada: %s", nota.id, resultado.motivo)


def _salvar_xml_evento(evento: NotaEvento, xml: str) -> None:
    if not xml:
        return
    prefixo = "canc" if evento.tipo == TipoEvento.CANCELAMENTO else "cce"
    xml_path = ARQUIVOS_DIR / f"nota-{evento.nota_id}-{prefixo}-{evento.id}.xml"
    xml_path.write_text(xml, encoding="utf-8")
    evento.xml_path = str(xml_path)


def processar_evento(db, evento: NotaEvento) -> None:
    nota = evento.nota
    emitente = cfg.obter_todas(db)
    emissor = obter_emissor(db)

    try:
        if evento.tipo == TipoEvento.CANCELAMENTO:
            resultado = emissor.cancelar(nota, evento.texto)
        else:
            resultado = emissor.carta_correcao(nota, evento.texto)
    except ErroComunicacao as exc:
        _falha_comunicacao(db, evento, "status", StatusEvento.PENDENTE, StatusEvento.REJEITADO, exc)
        log.info("Evento %s voltou à fila: %s", evento.id, exc)
        return
    except Exception as exc:
        _falha_comunicacao(db, evento, "status", StatusEvento.PENDENTE, StatusEvento.REJEITADO, exc)
        log.exception("Erro inesperado no evento %s", evento.id)
        return

    if not resultado.autorizado:
        evento.status = StatusEvento.REJEITADO
        evento.motivo_rejeicao = resultado.motivo
        db.commit()
        log.info("Evento %s rejeitado: %s", evento.id, resultado.motivo)
        return

    evento.status = StatusEvento.AUTORIZADO
    evento.protocolo = resultado.protocolo
    evento.sequencia = resultado.sequencia or evento.sequencia
    evento.processado_em = datetime.now()
    evento.ultimo_erro = ""
    _salvar_xml_evento(evento, resultado.xml)

    if evento.tipo == TipoEvento.CANCELAMENTO:
        nota.status = StatusNota.CANCELADA
        nota.cancelada_em = evento.processado_em
        nota.justificativa_cancelamento = evento.texto
        if nota.pdf_path:
            try:
                gerar_documento(nota, emitente, nota.pdf_path)
            except Exception:
                log.exception("Falha ao regenerar DANFE cancelado da nota %s", nota.id)
        if nota.cliente and nota.cliente.email and smtp_configurado(emitente):
            try:
                enviar_cancelamento_por_email(nota, emitente)
            except Exception as exc:
                log.warning("Falha ao enviar e-mail de cancelamento da nota %s: %s", nota.id, exc)
        tentar_enviar_cloud(nota, emitente, tipo="cancelamento")
    else:
        tentar_enviar_cloud(nota, emitente, tipo="carta")

    db.commit()
    log.info("Evento %s (%s) autorizado na nota %s", evento.id, evento.tipo.value, nota.id)


def processar_inutilizacao(db, item: Inutilizacao) -> None:
    emitente = cfg.obter_todas(db)
    emissor = obter_emissor(db)

    try:
        resultado = emissor.inutilizar(
            emitente,
            item.modelo,
            item.serie,
            item.ano,
            item.numero_inicial,
            item.numero_final,
            item.justificativa,
        )
    except ErroComunicacao as exc:
        _falha_comunicacao(
            db, item, "status", StatusInutilizacao.PENDENTE, StatusInutilizacao.REJEITADA, exc
        )
        log.info("Inutilização %s voltou à fila: %s", item.id, exc)
        return
    except Exception as exc:
        _falha_comunicacao(
            db, item, "status", StatusInutilizacao.PENDENTE, StatusInutilizacao.REJEITADA, exc
        )
        log.exception("Erro inesperado na inutilização %s", item.id)
        return

    if not resultado.autorizado:
        item.status = StatusInutilizacao.REJEITADA
        item.motivo_rejeicao = resultado.motivo
        db.commit()
        log.info("Inutilização %s rejeitada: %s", item.id, resultado.motivo)
        return

    item.status = StatusInutilizacao.AUTORIZADA
    item.protocolo = resultado.protocolo
    item.processada_em = datetime.now()
    item.ultimo_erro = ""
    if resultado.xml:
        xml_path = ARQUIVOS_DIR / f"inut-{item.id}.xml"
        xml_path.write_text(resultado.xml, encoding="utf-8")
        item.xml_path = str(xml_path)
    db.commit()
    log.info(
        "Inutilização %s autorizada (%s-%s série %s)",
        item.id, item.numero_inicial, item.numero_final, item.serie,
    )


def processar_fila() -> dict[str, int]:
    """Emite notas, eventos e inutilizações pendentes (se houver internet).

    Retorna quantos itens foram efetivamente processados nesta passada.
    """
    with _lock:
        db = SessionLocal()
        try:
            _recuperar_travados(db)
            ids_notas = [
                n.id
                for n in db.query(Nota.id)
                .filter(Nota.status == StatusNota.PENDENTE)
                .order_by(Nota.criado_em)
                .all()
            ]
            ids_eventos = [
                e.id
                for e in db.query(NotaEvento.id)
                .filter(NotaEvento.status == StatusEvento.PENDENTE)
                .order_by(NotaEvento.criado_em)
                .all()
            ]
            ids_inut = [
                i.id
                for i in db.query(Inutilizacao.id)
                .filter(Inutilizacao.status == StatusInutilizacao.PENDENTE)
                .order_by(Inutilizacao.criado_em)
                .all()
            ]
            resultado = {"notas": 0, "eventos": 0, "inutilizacoes": 0}
            if not ids_notas and not ids_eventos and not ids_inut:
                return resultado
            if not esta_online():
                log.debug(
                    "Off-line: %s nota(s), %s evento(s) e %s inutilização(ões) na fila",
                    len(ids_notas), len(ids_eventos), len(ids_inut),
                )
                return resultado

            for nota_id in ids_notas:
                if not _reivindicar_nota(db, nota_id):
                    continue
                nota = db.get(Nota, nota_id)
                processar_nota(db, nota)
                resultado["notas"] += 1
            for evento_id in ids_eventos:
                if not _reivindicar_evento(db, evento_id):
                    continue
                evento = db.get(NotaEvento, evento_id)
                processar_evento(db, evento)
                resultado["eventos"] += 1
            for item_id in ids_inut:
                if not _reivindicar_inutilizacao(db, item_id):
                    continue
                item = db.get(Inutilizacao, item_id)
                processar_inutilizacao(db, item)
                resultado["inutilizacoes"] += 1
            return resultado
        finally:
            db.close()


async def worker_fila() -> None:
    log.info("Worker da fila de emissão iniciado")
    await asyncio.to_thread(svc_backup.talvez_criar)
    while True:
        try:
            await asyncio.to_thread(processar_fila)
            await asyncio.to_thread(svc_backup.talvez_criar)
        except Exception:
            log.exception("Erro no worker da fila")
        await asyncio.sleep(INTERVALO_SEGUNDOS)
