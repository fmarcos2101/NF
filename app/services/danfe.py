"""Geração do DANFE simplificado (PDF) para impressão e envio ao cliente."""
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from ..models import Nota

LARGURA = 190  # área útil em mm (A4 com margens de 10)


def _linha(pdf: FPDF, altura: float = 4) -> None:
    pdf.ln(altura)


def _rotulo_valor(pdf: FPDF, rotulo: str, valor: str, largura: float = 63) -> None:
    pdf.set_font("helvetica", "", 7)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(largura, 3.5, rotulo, new_x=XPos.LEFT, new_y=YPos.NEXT)
    pdf.set_font("helvetica", "B", 9)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(largura, 5, valor or "-", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_y(pdf.get_y() - 3.5)


def gerar_danfe(nota: Nota, emitente: dict[str, str], caminho: str) -> None:
    pdf = FPDF(format="A4")
    pdf.set_margins(10, 10, 10)
    pdf.set_auto_page_break(True, margin=12)
    pdf.add_page()

    simulada = nota.protocolo.startswith("SIM")

    # Cabeçalho
    pdf.set_font("helvetica", "B", 14)
    pdf.cell(LARGURA / 2, 7, emitente.get("emitente_razao_social", "") or "Emitente",
             new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(LARGURA / 2, 7, f"DANFE - NF-e Nº {nota.numero:09d}  Série {nota.serie}",
             align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("helvetica", "", 9)
    endereco_emit = ", ".join(
        p for p in [
            emitente.get("emitente_logradouro", ""),
            emitente.get("emitente_numero", ""),
            emitente.get("emitente_bairro", ""),
            f"{emitente.get('emitente_municipio', '')}/{emitente.get('emitente_uf', '')}",
        ] if p and p != "/"
    )
    pdf.cell(LARGURA, 5, f"CNPJ: {emitente.get('emitente_cnpj', '')}   IE: {emitente.get('emitente_ie', '')}",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if endereco_emit:
        pdf.cell(LARGURA, 5, endereco_emit, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    _linha(pdf, 2)
    pdf.set_draw_color(60, 60, 60)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    _linha(pdf, 3)

    if simulada:
        pdf.set_font("helvetica", "B", 10)
        pdf.set_text_color(200, 30, 30)
        pdf.cell(LARGURA, 6, "DOCUMENTO SIMULADO - SEM VALIDADE FISCAL",
                 align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0)
        _linha(pdf, 2)

    # Chave de acesso e protocolo
    _rotulo_valor(pdf, "CHAVE DE ACESSO", " ".join(
        nota.chave_acesso[i:i + 4] for i in range(0, len(nota.chave_acesso), 4)
    ), largura=126)
    _rotulo_valor(pdf, "PROTOCOLO", nota.protocolo, largura=32)
    _rotulo_valor(pdf, "EMISSÃO", f"{nota.autorizada_em:%d/%m/%Y %H:%M}" if nota.autorizada_em else "", largura=32)
    pdf.ln(10)

    # Destinatário
    cliente = nota.cliente
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(LARGURA, 6, "DESTINATÁRIO", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    _rotulo_valor(pdf, "NOME / RAZÃO SOCIAL", cliente.nome if cliente else "", largura=126)
    _rotulo_valor(pdf, "CPF/CNPJ", cliente.cpf_cnpj if cliente else "", largura=64)
    pdf.ln(10)
    if cliente:
        endereco = ", ".join(p for p in [
            cliente.logradouro, cliente.numero, cliente.bairro,
            f"{cliente.municipio}/{cliente.uf}" if cliente.municipio else "",
            cliente.cep,
        ] if p)
        _rotulo_valor(pdf, "ENDEREÇO", endereco, largura=LARGURA)
        pdf.ln(10)

    # Itens
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(LARGURA, 6, "PRODUTOS / SERVIÇOS", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("helvetica", "B", 8)
    pdf.set_fill_color(235, 238, 245)
    colunas = [("DESCRIÇÃO", 74), ("NCM", 18), ("CFOP", 12), ("UN", 10),
               ("QTDE", 18), ("VL. UNIT.", 28), ("VL. TOTAL", 30)]
    for titulo, largura in colunas:
        pdf.cell(largura, 6, titulo, border=1, fill=True, align="C")
    pdf.ln()
    pdf.set_font("helvetica", "", 8)
    for item in nota.itens:
        descricao = item.descricao if len(item.descricao) <= 48 else item.descricao[:45] + "..."
        pdf.cell(74, 6, descricao, border=1)
        pdf.cell(18, 6, item.ncm, border=1, align="C")
        pdf.cell(12, 6, item.cfop, border=1, align="C")
        pdf.cell(10, 6, item.unidade, border=1, align="C")
        pdf.cell(18, 6, f"{item.quantidade:g}", border=1, align="R")
        pdf.cell(28, 6, f"R$ {item.preco_unitario:,.2f}", border=1, align="R")
        pdf.cell(30, 6, f"R$ {item.total:,.2f}", border=1, align="R")
        pdf.ln()

    # Totais
    _linha(pdf, 3)
    pdf.set_font("helvetica", "", 9)
    if nota.desconto:
        pdf.cell(160, 6, "Desconto:", align="R")
        pdf.cell(30, 6, f"R$ {nota.desconto:,.2f}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(160, 8, "VALOR TOTAL DA NOTA:", align="R")
    pdf.cell(30, 8, f"R$ {nota.total:,.2f}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Observações
    if nota.observacoes:
        _linha(pdf, 4)
        pdf.set_font("helvetica", "B", 9)
        pdf.cell(LARGURA, 5, "INFORMAÇÕES COMPLEMENTARES", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("helvetica", "", 9)
        pdf.multi_cell(LARGURA, 5, nota.observacoes)

    pdf.output(caminho)
