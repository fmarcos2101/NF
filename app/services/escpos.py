"""Cupom ESC/POS para impressora térmica (rede, porta 9100 em geral)."""
import socket

from ..models import Nota, StatusNota
from .danfe_nfce import FORMAS
from .formatos import moeda

ESC = b"\x1b"
GS = b"\x1d"
LARGURA = 48


def _txt(texto: str) -> bytes:
    return (texto or "").encode("cp850", errors="replace")


def _linha(texto: str = "", centro: bool = False) -> bytes:
    cmd = ESC + b"a\x01" if centro else ESC + b"a\x00"
    return cmd + _txt(texto[:LARGURA]) + b"\n"


def _sep() -> bytes:
    return _linha("-" * LARGURA)


def _qr(url: str) -> bytes:
    if not url:
        return b""
    data = url.encode("utf-8")
    tamanho = len(data) + 3
    return (
        GS + b"(k\x04\x00\x31\x41\x32\x00"
        + GS + b"(k\x03\x00\x31\x43\x04"
        + GS + b"(k\x03\x00\x31\x45\x31"
        + GS + b"(k" + bytes([tamanho % 256, tamanho // 256, 0x31, 0x50, 0x30]) + data
        + GS + b"(k\x03\x00\x31\x51\x30"
    )


def montar_cupom(nota: Nota, emitente: dict[str, str]) -> bytes:
    empresa = emitente.get("emitente_nome_fantasia") or emitente.get("emitente_razao_social") or "Emitente"
    nfce = getattr(nota, "modelo", 55) == 65
    titulo = f"{'NFC-e' if nfce else 'NF-e'} {nota.numero:09d}  Serie {nota.serie}"
    destinatario = "Consumidor nao identificado"
    if nota.cliente and nota.cliente.nome and nota.cliente.nome != "Consumidor não identificado":
        destinatario = nota.cliente.nome
    cpf = nota.consumidor_cpf or (nota.cliente.cpf_cnpj if nota.cliente else "")

    buf = bytearray()
    buf += ESC + b"@"
    buf += _linha(empresa, centro=True)
    buf += _linha(f"CNPJ {emitente.get('emitente_cnpj', '')}  IE {emitente.get('emitente_ie', '')}", centro=True)
    buf += _linha(titulo, centro=True)
    if (nota.protocolo or "").startswith("SIM"):
        buf += _linha("DOCUMENTO SIMULADO - SEM VALIDADE FISCAL", centro=True)
    if nota.status == StatusNota.CANCELADA:
        buf += _linha("DOCUMENTO CANCELADO", centro=True)
    buf += _sep()
    buf += _linha(destinatario, centro=True)
    if cpf:
        buf += _linha(f"CPF/CNPJ {cpf}", centro=True)
    buf += _sep()
    buf += _linha("ITEM                          QTDE     TOTAL")
    for item in nota.itens:
        desc = item.descricao[:26]
        qtde = f"{item.quantidade:g}"
        total = moeda(item.total)
        buf += _linha(f"{desc:<26} {qtde:>6} {total:>12}"[:LARGURA])
    if nota.desconto:
        buf += _linha(f"{'Desconto':<33} {moeda(nota.desconto):>12}"[:LARGURA])
    buf += _linha(f"{'TOTAL':<33} {moeda(nota.total):>12}"[:LARGURA])
    buf += _sep()
    forma = FORMAS.get(nota.forma_pagamento, nota.forma_pagamento or "")
    if forma:
        buf += _linha(f"Pagamento: {forma}", centro=True)
    if nota.autorizada_em:
        buf += _linha(f"Emissao {nota.autorizada_em:%d/%m/%Y %H:%M}", centro=True)
    if nota.chave_acesso:
        chave = " ".join(nota.chave_acesso[i:i + 4] for i in range(0, len(nota.chave_acesso), 4))
        buf += _linha(chave[:LARGURA], centro=True)
        if len(chave) > LARGURA:
            buf += _linha(chave[LARGURA:], centro=True)
    if nota.qrcode_url:
        buf += ESC + b"a\x01"
        buf += _qr(nota.qrcode_url)
        buf += b"\n"
        buf += _linha("Consulte pela chave ou QR Code", centro=True)
    buf += b"\n\n\n"
    buf += GS + b"V\x00"
    return bytes(buf)


def enviar_impressora(dados: bytes, host: str, porta: int = 9100, timeout: float = 8.0) -> None:
    with socket.create_connection((host, int(porta)), timeout=timeout) as sock:
        sock.sendall(dados)
