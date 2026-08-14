"""Emissão real de NF-e via API da Focus NFe (https://focusnfe.com.br).

A Focus NFe cuida do certificado digital, assinatura do XML, comunicação
com a SEFAZ e contingência. O sistema envia um JSON com os dados da nota
e consulta o resultado. Requer um token de API (Configurações).
"""
import httpx

from ...models import Nota
from .base import EmissorBase, ErroComunicacao, ResultadoEmissao, ResultadoEvento

URLS = {
    "producao": "https://api.focusnfe.com.br",
    "homologacao": "https://homologacao.focusnfe.com.br",
}


class EmissorFocusNFe(EmissorBase):
    def __init__(self, token: str, ambiente: str = "homologacao") -> None:
        self.token = token
        self.base_url = URLS.get(ambiente, URLS["homologacao"])

    def _recurso(self, nota: Nota) -> str:
        return "nfce" if getattr(nota, "modelo", 55) == 65 else "nfe"

    def _payload(self, nota: Nota, emitente: dict[str, str]) -> dict:
        cliente = nota.cliente
        doc_cliente = "".join(c for c in ((nota.consumidor_cpf or "") or (cliente.cpf_cnpj if cliente else "")) if c.isdigit())
        nfce = getattr(nota, "modelo", 55) == 65
        payload = {
            "natureza_operacao": "Venda ao consumidor" if nfce else "Venda de mercadoria",
            "tipo_documento": 1,
            "finalidade_emissao": 1,
            "presenca_comprador": 1,
            "cnpj_emitente": "".join(
                c for c in emitente.get("emitente_cnpj", "") if c.isdigit()
            ),
            "valor_frete": 0.0,
            "valor_desconto": nota.desconto,
            "valor_total": nota.total,
            "modalidade_frete": 9,
            "items": [
                {
                    "numero_item": i + 1,
                    "codigo_produto": str(item.produto_id or i + 1),
                    "descricao": item.descricao,
                    "codigo_ncm": item.ncm,
                    "cfop": item.cfop,
                    "unidade_comercial": item.unidade,
                    "quantidade_comercial": item.quantidade,
                    "valor_unitario_comercial": item.preco_unitario,
                    "valor_unitario_tributavel": item.preco_unitario,
                    "unidade_tributavel": item.unidade,
                    "quantidade_tributavel": item.quantidade,
                    "valor_bruto": item.total,
                    "icms_situacao_tributaria": "102",
                    "icms_origem": 0,
                    "pis_situacao_tributaria": "07",
                    "cofins_situacao_tributaria": "07",
                }
                for i, item in enumerate(nota.itens)
            ],
        }
        if nfce:
            payload["formas_pagamento"] = [{
                "forma_pagamento": nota.forma_pagamento or "01",
                "valor_pagamento": nota.total,
            }]
            if cliente and cliente.nome and cliente.nome != "Consumidor não identificado":
                payload["nome_destinatario"] = cliente.nome
            if len(doc_cliente) == 11:
                payload["cpf_destinatario"] = doc_cliente
            elif len(doc_cliente) == 14:
                payload["cnpj_destinatario"] = doc_cliente
            return payload

        payload["nome_destinatario"] = cliente.nome if cliente else ""
        payload["logradouro_destinatario"] = cliente.logradouro if cliente else ""
        payload["numero_destinatario"] = cliente.numero if cliente else ""
        payload["bairro_destinatario"] = cliente.bairro if cliente else ""
        payload["municipio_destinatario"] = cliente.municipio if cliente else ""
        payload["uf_destinatario"] = cliente.uf if cliente else ""
        payload["cep_destinatario"] = "".join(c for c in (cliente.cep if cliente else "") if c.isdigit())
        if len(doc_cliente) == 11:
            payload["cpf_destinatario"] = doc_cliente
        else:
            payload["cnpj_destinatario"] = doc_cliente
        return payload

    def emitir(self, nota: Nota, emitente: dict[str, str]) -> ResultadoEmissao:
        if not self.token:
            return ResultadoEmissao(
                autorizada=False,
                motivo="Token da Focus NFe não configurado (Configurações).",
            )
        referencia = self._referencia(nota)
        recurso = self._recurso(nota)
        try:
            resposta = httpx.post(
                f"{self.base_url}/v2/{recurso}?ref={referencia}",
                json=self._payload(nota, emitente),
                auth=(self.token, ""),
                timeout=30,
            )
            consulta = httpx.get(
                f"{self.base_url}/v2/{recurso}/{referencia}",
                auth=(self.token, ""),
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise ErroComunicacao(str(exc)) from exc

        if resposta.status_code >= 500 or consulta.status_code >= 500:
            raise ErroComunicacao(f"Focus NFe indisponível ({resposta.status_code})")

        dados = consulta.json()
        status = dados.get("status", "")
        if status == "autorizado":
            xml = ""
            caminho_xml = dados.get("caminho_xml_nota_fiscal", "")
            if caminho_xml:
                try:
                    xml = httpx.get(
                        f"{self.base_url}{caminho_xml}",
                        auth=(self.token, ""),
                        timeout=30,
                    ).text
                except httpx.HTTPError:
                    pass
            return ResultadoEmissao(
                autorizada=True,
                chave_acesso=(dados.get("chave_nfe") or dados.get("chave_nfce") or "").replace("NFe", "").replace("NFCe", ""),
                protocolo=str(dados.get("numero_protocolo", "")),
                xml=xml,
                qrcode_url=dados.get("qrcode_url") or dados.get("url_consulta_nf") or "",
            )
        if status in ("processando_autorizacao", ""):
            raise ErroComunicacao("Nota ainda em processamento na SEFAZ; nova tentativa em instantes.")
        return ResultadoEmissao(
            autorizada=False,
            motivo=dados.get("mensagem_sefaz") or dados.get("mensagem") or f"Status: {status}",
        )

    def _referencia(self, nota: Nota) -> str:
        return f"nota-{nota.id}"

    def cancelar(self, nota: Nota, justificativa: str) -> ResultadoEvento:
        if not self.token:
            return ResultadoEvento(
                autorizado=False,
                motivo="Token da Focus NFe não configurado (Configurações).",
            )
        try:
            resposta = httpx.delete(
                f"{self.base_url}/v2/{self._recurso(nota)}/{self._referencia(nota)}",
                json={"justificativa": justificativa},
                auth=(self.token, ""),
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise ErroComunicacao(str(exc)) from exc
        if resposta.status_code >= 500:
            raise ErroComunicacao(f"Focus NFe indisponível ({resposta.status_code})")
        dados = resposta.json() if resposta.content else {}
        status = dados.get("status", "")
        if status == "cancelado" or resposta.status_code in (200, 202):
            xml = ""
            caminho_xml = dados.get("caminho_xml_cancelamento", "")
            if caminho_xml:
                try:
                    xml = httpx.get(
                        f"{self.base_url}{caminho_xml}",
                        auth=(self.token, ""),
                        timeout=30,
                    ).text
                except httpx.HTTPError:
                    pass
            if status in ("cancelado", "") and resposta.status_code < 400:
                return ResultadoEvento(
                    autorizado=True,
                    protocolo=str(dados.get("numero_protocolo", "")),
                    xml=xml,
                )
        if status in ("processando_cancelamento", "processando_autorizacao"):
            raise ErroComunicacao("Cancelamento ainda em processamento; nova tentativa em instantes.")
        return ResultadoEvento(
            autorizado=False,
            motivo=dados.get("mensagem_sefaz") or dados.get("mensagem") or f"Status: {status or resposta.status_code}",
        )

    def carta_correcao(self, nota: Nota, texto: str) -> ResultadoEvento:
        if getattr(nota, "modelo", 55) == 65:
            return ResultadoEvento(
                autorizado=False,
                motivo="NFC-e não admite carta de correção. Cancele e emita outra.",
            )
        if not self.token:
            return ResultadoEvento(
                autorizado=False,
                motivo="Token da Focus NFe não configurado (Configurações).",
            )
        try:
            resposta = httpx.post(
                f"{self.base_url}/v2/nfe/{self._referencia(nota)}/carta_correcao",
                json={"correcao": texto},
                auth=(self.token, ""),
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise ErroComunicacao(str(exc)) from exc
        if resposta.status_code >= 500:
            raise ErroComunicacao(f"Focus NFe indisponível ({resposta.status_code})")
        dados = resposta.json() if resposta.content else {}
        status = dados.get("status", "")
        if resposta.status_code < 400 and status not in ("erro_autorizacao", "erro"):
            xml = ""
            caminho_xml = dados.get("caminho_xml_carta_correcao", "")
            if caminho_xml:
                try:
                    xml = httpx.get(
                        f"{self.base_url}{caminho_xml}",
                        auth=(self.token, ""),
                        timeout=30,
                    ).text
                except httpx.HTTPError:
                    pass
            return ResultadoEvento(
                autorizado=True,
                protocolo=str(dados.get("numero_protocolo", "")),
                sequencia=int(dados.get("numero_carta_correcao") or dados.get("numero") or 0),
                xml=xml,
            )
        return ResultadoEvento(
            autorizado=False,
            motivo=dados.get("mensagem_sefaz") or dados.get("mensagem") or f"Status: {status or resposta.status_code}",
        )
