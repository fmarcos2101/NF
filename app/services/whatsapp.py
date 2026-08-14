"""Despacho via WhatsApp: link wa.me (manual) e Cloud API (automático).

Sem token, o sistema gera um link wa.me com a mensagem pronta. Com token e
phone_id da Cloud API, o aviso é enviado sozinho após autorização, cancelamento
ou carta de correção.
"""
import logging
from urllib.parse import quote

import httpx

from ..models import Nota, StatusEvento, TipoEvento
from .formatos import moeda

log = logging.getLogger("nf.whatsapp")

GRAPH_URL = "https://graph.facebook.com/v21.0"


def _telefone(nota: Nota) -> str:
    cliente = nota.cliente
    telefone = "".join(c for c in (cliente.whatsapp if cliente else "") if c.isdigit())
    if telefone and not telefone.startswith("55"):
        telefone = "55" + telefone
    return telefone


def _empresa(config: dict[str, str]) -> str:
    return config.get("emitente_nome_fantasia") or config.get("emitente_razao_social") or ""


def _rotulo_documento(nota: Nota) -> str:
    if getattr(nota, "modelo", 55) == 65:
        return f"NFC-e nº {nota.numero:09d}"
    return f"nota fiscal nº {nota.numero:09d}"


def montar_link(nota: Nota, config: dict[str, str], tipo: str = "emissao") -> dict[str, str]:
    """tipo: emissao | cancelamento | carta"""
    cliente = nota.cliente
    nome = cliente.nome if cliente else "cliente"
    empresa = _empresa(config)
    doc = _rotulo_documento(nota)

    if tipo == "cancelamento":
        mensagem = (
            f"Olá, {nome}! Informamos que a {doc} foi cancelada"
            + (f" por {empresa}" if empresa else "")
            + f".\nValor: {moeda(nota.total)}"
            + (f"\nChave de acesso: {nota.chave_acesso}" if nota.chave_acesso else "")
            + (f"\nJustificativa: {nota.justificativa_cancelamento}" if nota.justificativa_cancelamento else "")
            + "\nO PDF atualizado segue em anexo, se necessário."
        )
    elif tipo == "carta":
        eventos = [
            e for e in (nota.eventos or [])
            if e.tipo == TipoEvento.CARTA_CORRECAO and e.status == StatusEvento.AUTORIZADO
        ]
        texto = eventos[-1].texto if eventos else ""
        mensagem = (
            f"Olá, {nome}! Foi registrada uma carta de correção na {doc}"
            + (f" emitida por {empresa}" if empresa else "")
            + (f".\nCorreção: {texto}" if texto else ".")
            + (f"\nChave de acesso: {nota.chave_acesso}" if nota.chave_acesso else "")
        )
    else:
        mensagem = (
            f"Olá, {nome}! Sua {doc} foi emitida"
            + (f" por {empresa}" if empresa else "")
            + f".\nValor total: {moeda(nota.total)}"
            + (f"\nChave de acesso: {nota.chave_acesso}" if nota.chave_acesso else "")
            + "\nO PDF da nota segue em anexo."
        )

    telefone = _telefone(nota)
    link = f"https://wa.me/{telefone}?text={quote(mensagem)}" if telefone else ""
    return {"link": link, "mensagem": mensagem, "telefone": telefone, "tipo": tipo}


def cloud_configurada(config: dict[str, str]) -> bool:
    return bool(config.get("whatsapp_token") and config.get("whatsapp_phone_id"))


def enviar_cloud(nota: Nota, config: dict[str, str], tipo: str = "emissao") -> dict:
    """Envia texto pela WhatsApp Cloud API. Não levanta exceção para o chamador da fila."""
    dados = montar_link(nota, config, tipo=tipo)
    if not cloud_configurada(config):
        return {"enviado": False, "motivo": "WhatsApp Cloud API não configurada."}
    if not dados["telefone"]:
        return {"enviado": False, "motivo": "Cliente sem WhatsApp."}
    url = f"{GRAPH_URL}/{config['whatsapp_phone_id']}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": dados["telefone"],
        "type": "text",
        "text": {"body": dados["mensagem"]},
    }
    try:
        resposta = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {config['whatsapp_token']}"},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        log.warning("WhatsApp Cloud falhou (rede) na nota %s: %s", nota.id, exc)
        return {"enviado": False, "motivo": str(exc)}
    if resposta.status_code >= 400:
        detalhe = resposta.text[:300]
        log.warning("WhatsApp Cloud recusou nota %s: %s", nota.id, detalhe)
        return {"enviado": False, "motivo": detalhe or f"HTTP {resposta.status_code}"}
    return {"enviado": True, "motivo": ""}


def tentar_enviar_cloud(nota: Nota, config: dict[str, str], tipo: str = "emissao") -> None:
    if not cloud_configurada(config):
        return
    try:
        enviar_cloud(nota, config, tipo=tipo)
    except Exception:
        log.exception("Falha inesperada no WhatsApp Cloud da nota %s", nota.id)
