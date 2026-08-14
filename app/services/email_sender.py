"""Envio da nota (PDF + XML) por e-mail via SMTP."""
import smtplib
from email.message import EmailMessage
from pathlib import Path

from ..models import Nota
from .formatos import moeda


def smtp_configurado(config: dict[str, str]) -> bool:
    return bool(config.get("smtp_host") and config.get("smtp_usuario"))


def enviar_nota_por_email(nota: Nota, config: dict[str, str]) -> None:
    """Envia o DANFE e o XML para o e-mail do cliente. Levanta exceção em falha."""
    destinatario = nota.cliente.email if nota.cliente else ""
    if not destinatario:
        raise ValueError("Cliente sem e-mail cadastrado.")
    if not smtp_configurado(config):
        raise ValueError("SMTP não configurado (Configurações).")

    empresa = config.get("emitente_nome_fantasia") or config.get("emitente_razao_social") or "Sistema NF"
    msg = EmailMessage()
    msg["Subject"] = f"Nota Fiscal Nº {nota.numero:09d} - {empresa}"
    msg["From"] = config.get("smtp_remetente") or config["smtp_usuario"]
    msg["To"] = destinatario
    msg.set_content(
        f"Olá, {nota.cliente.nome}!\n\n"
        f"Sua nota fiscal nº {nota.numero:09d} (série {nota.serie}) foi emitida.\n"
        f"Valor total: {moeda(nota.total)}\n"
        f"Chave de acesso: {nota.chave_acesso}\n\n"
        f"O DANFE (PDF) e o XML estão em anexo.\n\n"
        f"Atenciosamente,\n{empresa}"
    )

    if nota.pdf_path and Path(nota.pdf_path).exists():
        msg.add_attachment(
            Path(nota.pdf_path).read_bytes(),
            maintype="application", subtype="pdf",
            filename=f"NF-{nota.numero:09d}.pdf",
        )
    if nota.xml_path and Path(nota.xml_path).exists():
        msg.add_attachment(
            Path(nota.xml_path).read_bytes(),
            maintype="application", subtype="xml",
            filename=f"NF-{nota.numero:09d}.xml",
        )

    porta = int(config.get("smtp_porta") or 587)
    if porta == 465:
        with smtplib.SMTP_SSL(config["smtp_host"], porta, timeout=30) as smtp:
            smtp.login(config["smtp_usuario"], config["smtp_senha"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(config["smtp_host"], porta, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(config["smtp_usuario"], config["smtp_senha"])
            smtp.send_message(msg)
