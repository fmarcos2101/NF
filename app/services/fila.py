"""Fila de emissão off-line.

As notas são sempre gravadas primeiro no banco local (status PENDENTE).
Um worker em segundo plano verifica a conectividade periodicamente e,
quando há internet, transmite as pendentes na ordem de criação. Falhas
de rede devolvem a nota à fila; rejeições da SEFAZ marcam REJEITADA.
Após a autorização, o DANFE é gerado e o e-mail é despachado sozinho.
"""
import asyncio
import logging
import time
from datetime import datetime

import httpx

from ..database import ARQUIVOS_DIR, SessionLocal
from ..models import Nota, StatusNota
from . import config as cfg
from .danfe import gerar_danfe
from .email_sender import enviar_nota_por_email, smtp_configurado
from .emissores import obter_emissor
from .emissores.base import ErroComunicacao

log = logging.getLogger("nf.fila")

INTERVALO_SEGUNDOS = 10
CACHE_CONECTIVIDADE_SEGUNDOS = 15
URL_TESTE_CONEXAO = "https://www.gstatic.com/generate_204"

_estado = {"online": False, "verificado_em": 0.0}


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


def _finalizar_autorizacao(db, nota: Nota, resultado, emitente: dict[str, str]) -> None:
    nota.status = StatusNota.AUTORIZADA
    nota.chave_acesso = resultado.chave_acesso
    nota.protocolo = resultado.protocolo
    nota.autorizada_em = datetime.now()
    nota.ultimo_erro = ""

    if resultado.xml:
        xml_path = ARQUIVOS_DIR / f"nota-{nota.id}.xml"
        xml_path.write_text(resultado.xml, encoding="utf-8")
        nota.xml_path = str(xml_path)

    pdf_path = ARQUIVOS_DIR / f"nota-{nota.id}.pdf"
    try:
        gerar_danfe(nota, emitente, str(pdf_path))
        nota.pdf_path = str(pdf_path)
    except Exception as exc:  # PDF não pode impedir a autorização
        log.exception("Falha ao gerar DANFE da nota %s", nota.id)
        nota.ultimo_erro = f"DANFE: {exc}"

    db.commit()

    # Despacho automático por e-mail
    if nota.cliente and nota.cliente.email and smtp_configurado(emitente):
        try:
            enviar_nota_por_email(nota, emitente)
            nota.email_enviado_em = datetime.now()
        except Exception as exc:
            log.warning("Falha ao enviar e-mail da nota %s: %s", nota.id, exc)
            nota.ultimo_erro = f"E-mail: {exc}"
        db.commit()


def processar_nota(db, nota: Nota) -> None:
    emitente = cfg.obter_todas(db)
    emissor = obter_emissor(db)

    nota.status = StatusNota.PROCESSANDO
    nota.tentativas += 1
    db.commit()

    try:
        resultado = emissor.emitir(nota, emitente)
    except ErroComunicacao as exc:
        nota.status = StatusNota.PENDENTE  # volta para a fila
        nota.ultimo_erro = str(exc)
        db.commit()
        log.info("Nota %s voltou à fila: %s", nota.id, exc)
        return
    except Exception as exc:
        nota.status = StatusNota.PENDENTE
        nota.ultimo_erro = f"Erro inesperado: {exc}"
        db.commit()
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


def processar_fila() -> int:
    """Emite as notas pendentes (se houver internet). Retorna quantas processou."""
    db = SessionLocal()
    try:
        pendentes = (
            db.query(Nota)
            .filter(Nota.status == StatusNota.PENDENTE)
            .order_by(Nota.criado_em)
            .all()
        )
        if not pendentes:
            return 0
        if not esta_online():
            log.debug("Off-line: %s nota(s) aguardando na fila", len(pendentes))
            return 0
        for nota in pendentes:
            processar_nota(db, nota)
        return len(pendentes)
    finally:
        db.close()


async def worker_fila() -> None:
    log.info("Worker da fila de emissão iniciado")
    while True:
        try:
            await asyncio.to_thread(processar_fila)
        except Exception:
            log.exception("Erro no worker da fila")
        await asyncio.sleep(INTERVALO_SEGUNDOS)
