"""DANFE da NFC-e em formato de cupom térmico (80 mm) com QR Code."""
from io import BytesIO

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from ..models import Nota, StatusNota
from .formatos import moeda

FORMAS = {
    "01": "Dinheiro",
    "02": "Cheque",
    "03": "Cartão de crédito",
    "04": "Cartão de débito",
    "05": "Crédito loja",
    "10": "Vale alimentação",
    "11": "Vale refeição",
    "17": "PIX",
    "18": "Transferência",
    "90": "Sem pagamento",
    "99": "Outros",
}

LARGURA = 70  # área útil em mm (bobina 80 mm com margens)


def _qr_png(url: str) -> BytesIO | None:
    if not url:
        return None
    try:
        import segno
        buffer = BytesIO()
        segno.make(url, error="m").save(buffer, kind="png", scale=4, border=1)
        buffer.seek(0)
        return buffer
    except Exception:
        return None


def gerar_danfe_nfce(nota: Nota, emitente: dict[str, str], caminho: str) -> None:
    linhas_itens = max(len(nota.itens), 1)
    altura = 90 + linhas_itens * 8 + (18 if nota.status == StatusNota.CANCELADA else 0)
    pdf = FPDF(unit="mm", format=(80, max(altura, 140)))
    pdf.set_margins(5, 5, 5)
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(LARGURA, 5, emitente.get("emitente_nome_fantasia") or emitente.get("emitente_razao_social") or "Emitente",
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("helvetica", "", 7)
    pdf.cell(LARGURA, 4, f"CNPJ {emitente.get('emitente_cnpj', '')}  IE {emitente.get('emitente_ie', '')}",
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    endereco = " ".join(p for p in [
        emitente.get("emitente_logradouro", ""),
        emitente.get("emitente_numero", ""),
        emitente.get("emitente_municipio", ""),
        emitente.get("emitente_uf", ""),
    ] if p)
    if endereco:
        pdf.cell(LARGURA, 4, endereco, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("helvetica", "B", 9)
    pdf.cell(LARGURA, 6, f"NFC-e {nota.numero:09d}  Série {nota.serie}",
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    simulada = (nota.protocolo or "").startswith("SIM")
    if simulada:
        pdf.set_text_color(200, 30, 30)
        pdf.set_font("helvetica", "B", 8)
        pdf.cell(LARGURA, 4, "DOCUMENTO SIMULADO - SEM VALIDADE FISCAL",
                 align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
    if nota.status == StatusNota.CANCELADA:
        pdf.set_text_color(200, 30, 30)
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(LARGURA, 5, "NFC-e CANCELADA", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)

    pdf.set_font("helvetica", "", 7)
    destinatario = "Consumidor não identificado"
    if nota.cliente and nota.cliente.nome and nota.cliente.nome != "Consumidor não identificado":
        destinatario = nota.cliente.nome
    cpf = nota.consumidor_cpf or (nota.cliente.cpf_cnpj if nota.cliente else "")
    pdf.cell(LARGURA, 4, destinatario, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if cpf:
        pdf.cell(LARGURA, 4, f"CPF/CNPJ {cpf}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("helvetica", "B", 7)
    pdf.cell(40, 4, "ITEM", border="B")
    pdf.cell(12, 4, "QTDE", border="B", align="R")
    pdf.cell(18, 4, "TOTAL", border="B", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("helvetica", "", 7)
    for item in nota.itens:
        desc = item.descricao if len(item.descricao) <= 28 else item.descricao[:25] + "..."
        pdf.cell(40, 4, desc)
        pdf.cell(12, 4, f"{item.quantidade:g}", align="R")
        pdf.cell(18, 4, moeda(item.total), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if nota.desconto:
        pdf.cell(52, 4, "Desconto", align="R")
        pdf.cell(18, 4, moeda(nota.desconto), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(52, 6, "TOTAL", align="R")
    pdf.cell(18, 6, moeda(nota.total), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("helvetica", "", 7)
    forma = FORMAS.get(nota.forma_pagamento, nota.forma_pagamento)
    pdf.cell(LARGURA, 4, f"Pagamento: {forma}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if nota.autorizada_em:
        pdf.cell(LARGURA, 4, f"Emissão {nota.autorizada_em:%d/%m/%Y %H:%M}",
                 align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    chave = " ".join(nota.chave_acesso[i:i + 4] for i in range(0, len(nota.chave_acesso), 4))
    if chave:
        pdf.multi_cell(LARGURA, 3.5, chave, align="C")

    qr = _qr_png(nota.qrcode_url)
    if qr:
        pdf.image(qr, x=22, w=36)

    pdf.set_font("helvetica", "", 6)
    pdf.cell(LARGURA, 4, "Consulte pela chave de acesso ou QR Code",
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.output(caminho)
