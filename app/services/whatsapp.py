"""Despacho via WhatsApp sem API: gera um link wa.me com a mensagem pronta.

Ao clicar, o WhatsApp (Web ou aplicativo) abre a conversa com o cliente
com a mensagem preenchida — basta anexar o PDF e enviar. Quando houver
uma conta WhatsApp Business API, este módulo pode ser trocado por envio
automático sem mudar o resto do sistema.
"""
from urllib.parse import quote

from ..models import Nota, StatusEvento, TipoEvento
from .formatos import moeda


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
