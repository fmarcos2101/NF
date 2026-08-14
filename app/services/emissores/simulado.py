"""Emissor simulado: autoriza a nota localmente, sem falar com a SEFAZ.

Útil para desenvolver, demonstrar e treinar o uso do sistema sem
certificado digital nem credenciais. Gera uma chave de acesso com o
formato real (44 dígitos) e um XML simplificado, mas SEM validade fiscal.
"""
import random
from datetime import datetime
from xml.sax.saxutils import escape

from ...models import Nota
from .base import EmissorBase, ResultadoEmissao

UF_CODIGOS = {
    "AC": "12", "AL": "27", "AM": "13", "AP": "16", "BA": "29", "CE": "23",
    "DF": "53", "ES": "32", "GO": "52", "MA": "21", "MG": "31", "MS": "50",
    "MT": "51", "PA": "15", "PB": "25", "PE": "26", "PI": "22", "PR": "41",
    "RJ": "33", "RN": "24", "RO": "11", "RR": "14", "RS": "43", "SC": "42",
    "SE": "28", "SP": "35", "TO": "17",
}


def _digito_verificador(chave43: str) -> str:
    """Dígito verificador da chave de acesso (módulo 11)."""
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = 0
    for i, digito in enumerate(reversed(chave43)):
        soma += int(digito) * pesos[i % 8]
    resto = soma % 11
    return "0" if resto in (0, 1) else str(11 - resto)


def _montar_chave(nota: Nota, emitente: dict[str, str]) -> str:
    agora = datetime.now()
    uf = UF_CODIGOS.get(emitente.get("emitente_uf", ""), "35")
    cnpj = "".join(c for c in emitente.get("emitente_cnpj", "") if c.isdigit())
    cnpj = cnpj.zfill(14)[:14]
    chave43 = (
        f"{uf}"
        f"{agora:%y%m}"
        f"{cnpj}"
        f"55"                          # modelo NF-e
        f"{nota.serie:03d}"
        f"{nota.numero:09d}"
        f"1"                           # forma de emissão normal
        f"{random.randint(0, 99999999):08d}"
    )
    return chave43 + _digito_verificador(chave43)


def _montar_xml(nota: Nota, emitente: dict[str, str], chave: str) -> str:
    itens = "".join(
        f"""
    <det nItem="{i + 1}">
      <prod>
        <xProd>{escape(item.descricao)}</xProd>
        <NCM>{item.ncm}</NCM>
        <CFOP>{item.cfop}</CFOP>
        <uCom>{item.unidade}</uCom>
        <qCom>{item.quantidade:.4f}</qCom>
        <vUnCom>{item.preco_unitario:.2f}</vUnCom>
        <vProd>{item.total:.2f}</vProd>
      </prod>
    </det>"""
        for i, item in enumerate(nota.itens)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- DOCUMENTO SIMULADO - SEM VALIDADE FISCAL -->
<NFe>
  <infNFe Id="NFe{chave}">
    <ide><nNF>{nota.numero}</nNF><serie>{nota.serie}</serie></ide>
    <emit>
      <xNome>{escape(emitente.get('emitente_razao_social', ''))}</xNome>
      <CNPJ>{emitente.get('emitente_cnpj', '')}</CNPJ>
    </emit>
    <dest>
      <xNome>{escape(nota.cliente.nome if nota.cliente else '')}</xNome>
    </dest>{itens}
    <total><vNF>{nota.total:.2f}</vNF></total>
  </infNFe>
</NFe>
"""


class EmissorSimulado(EmissorBase):
    def emitir(self, nota: Nota, emitente: dict[str, str]) -> ResultadoEmissao:
        if not emitente.get("emitente_razao_social") or not emitente.get("emitente_cnpj"):
            return ResultadoEmissao(
                autorizada=False,
                motivo="Preencha a razão social e o CNPJ do emitente em Configurações.",
            )
        chave = _montar_chave(nota, emitente)
        return ResultadoEmissao(
            autorizada=True,
            chave_acesso=chave,
            protocolo=f"SIM{datetime.now():%Y%m%d%H%M%S}",
            xml=_montar_xml(nota, emitente, chave),
        )
