"""Despacho via WhatsApp sem API: gera um link wa.me com a mensagem pronta.

Ao clicar, o WhatsApp (Web ou aplicativo) abre a conversa com o cliente
com a mensagem preenchida — basta anexar o PDF e enviar. Quando houver
uma conta WhatsApp Business API, este módulo pode ser trocado por envio
automático sem mudar o resto do sistema.
"""
from urllib.parse import quote

from ..models import Nota
from .formatos import moeda


def montar_link(nota: Nota, config: dict[str, str]) -> dict[str, str]:
    cliente = nota.cliente
    telefone = "".join(c for c in (cliente.whatsapp if cliente else "") if c.isdigit())
    if telefone and not telefone.startswith("55"):
        telefone = "55" + telefone

    empresa = config.get("emitente_nome_fantasia") or config.get("emitente_razao_social") or ""
    mensagem = (
        f"Olá, {cliente.nome if cliente else ''}! "
        f"Sua nota fiscal nº {nota.numero:09d} foi emitida"
        + (f" por {empresa}" if empresa else "")
        + f".\nValor total: {moeda(nota.total)}"
        + (f"\nChave de acesso: {nota.chave_acesso}" if nota.chave_acesso else "")
        + "\nO PDF da nota segue em anexo."
    )
    link = f"https://wa.me/{telefone}?text={quote(mensagem)}" if telefone else ""
    return {"link": link, "mensagem": mensagem, "telefone": telefone}
