"""Emissão real de NF-e/NFC-e via API da Focus NFe (https://focusnfe.com.br).

A Focus NFe cuida do certificado digital, assinatura do XML, comunicação
com a SEFAZ e contingência. O sistema envia um JSON com os dados da nota
e acompanha o resultado. Requer um token de API (Configurações).

Regras de tratamento de resposta:

- Erro de rede, HTTP 5xx e 429 → ``ErroComunicacao`` (o item volta à fila).
- HTTP 4xx no envio → rejeição definitiva com a mensagem retornada.
- Autorização só é reconhecida com status final explícito da Focus
  ("autorizado", "cancelado", "registrado"...). Respostas em processamento
  levantam ``ErroComunicacao`` para nova tentativa.
- Downloads de XML/PDF validam o status HTTP antes de salvar o conteúdo.
"""
from datetime import datetime

import httpx

from ...models import Nota
from .base import EmissorBase, ErroComunicacao, ResultadoEmissao, ResultadoEvento

URLS = {
    "producao": "https://api.focusnfe.com.br",
    "homologacao": "https://homologacao.focusnfe.com.br",
}

STATUS_PROCESSANDO = {
    "processando_autorizacao",
    "processando_cancelamento",
    "processando",
}


class EmissorFocusNFe(EmissorBase):
    def __init__(self, token: str, ambiente: str = "homologacao") -> None:
        self.token = token
        self.base_url = URLS.get(ambiente, URLS["homologacao"])

    def _recurso(self, nota: Nota) -> str:
        return "nfce" if getattr(nota, "modelo", 55) == 65 else "nfe"

    def _referencia(self, nota: Nota) -> str:
        # Referência única por token exigida pela Focus. O UUID gerado na
        # criação da nota evita colisões mesmo se o banco for restaurado
        # e os IDs forem reutilizados.
        return getattr(nota, "referencia", "") or f"nota-{nota.id}"

    def _baixar(self, caminho: str) -> str:
        """Baixa um arquivo relativo da Focus. Retorna '' se não for 200."""
        if not caminho:
            return ""
        try:
            resposta = httpx.get(
                f"{self.base_url}{caminho}", auth=(self.token, ""), timeout=30
            )
        except httpx.HTTPError:
            return ""
        if resposta.status_code != 200:
            return ""
        return resposta.text

    def _baixar_bytes(self, caminho: str) -> bytes:
        if not caminho:
            return b""
        try:
            resposta = httpx.get(
                f"{self.base_url}{caminho}", auth=(self.token, ""), timeout=30
            )
        except httpx.HTTPError:
            return b""
        if resposta.status_code != 200:
            return b""
        return resposta.content

    @staticmethod
    def _motivo(dados: dict, resposta) -> str:
        if isinstance(dados.get("erros"), list) and dados["erros"]:
            partes = []
            for erro in dados["erros"]:
                if isinstance(erro, dict):
                    partes.append(erro.get("mensagem") or str(erro))
                else:
                    partes.append(str(erro))
            return "; ".join(partes)
        return (
            dados.get("mensagem_sefaz")
            or dados.get("mensagem")
            or f"HTTP {resposta.status_code}"
        )

    def _payload(self, nota: Nota, emitente: dict[str, str]) -> dict:
        cliente = nota.cliente
        doc_cliente = "".join(
            c
            for c in ((nota.consumidor_cpf or "") or (cliente.cpf_cnpj if cliente else ""))
            if c.isdigit()
        )
        nfce = getattr(nota, "modelo", 55) == 65
        payload = {
            "natureza_operacao": "Venda ao consumidor" if nfce else "Venda de mercadoria",
            "data_emissao": datetime.now().astimezone().isoformat(timespec="seconds"),
            "tipo_documento": 1,
            "finalidade_emissao": 1,
            "presenca_comprador": 1 if nfce else 9,
            "consumidor_final": 1,
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
                    "icms_situacao_tributaria": getattr(item, "csosn", "") or "102",
                    "icms_origem": 0,
                    "pis_situacao_tributaria": "07",
                    "cofins_situacao_tributaria": "07",
                }
                for i, item in enumerate(nota.itens)
            ],
        }
        if nota.numero:
            payload["numero"] = nota.numero
            payload["serie"] = nota.serie
        if nota.observacoes:
            payload["informacoes_adicionais_contribuinte"] = nota.observacoes

        if nfce:
            payload["local_destino"] = 1  # NFC-e é sempre operação interna
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
        payload["cep_destinatario"] = "".join(
            c for c in (cliente.cep if cliente else "") if c.isdigit()
        )
        if len(doc_cliente) == 11:
            payload["cpf_destinatario"] = doc_cliente
            payload["indicador_inscricao_estadual_destinatario"] = 9
        else:
            payload["cnpj_destinatario"] = doc_cliente
            ie = (cliente.ie if cliente else "").strip()
            if ie:
                payload["inscricao_estadual_destinatario"] = ie
                payload["indicador_inscricao_estadual_destinatario"] = 1
            else:
                payload["indicador_inscricao_estadual_destinatario"] = 9
        return payload

    def _montar_autorizacao(self, dados: dict) -> ResultadoEmissao:
        xml = self._baixar(dados.get("caminho_xml_nota_fiscal", ""))
        pdf = self._baixar_bytes(
            dados.get("caminho_danfe") or dados.get("caminho_danfe_nfce") or ""
        )
        return ResultadoEmissao(
            autorizada=True,
            chave_acesso=(dados.get("chave_nfe") or dados.get("chave_nfce") or "")
            .replace("NFe", "")
            .replace("NFCe", ""),
            protocolo=str(dados.get("numero_protocolo", "")),
            xml=xml,
            qrcode_url=dados.get("qrcode_url") or dados.get("url_consulta_nf") or "",
            danfe_pdf=pdf,
        )

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
        except httpx.HTTPError as exc:
            raise ErroComunicacao(str(exc)) from exc

        if resposta.status_code == 429 or resposta.status_code >= 500:
            raise ErroComunicacao(f"Focus NFe indisponível ({resposta.status_code})")

        dados = resposta.json() if resposta.content else {}
        status = dados.get("status", "")

        # 409: referência já usada neste token — consulta o estado real.
        if resposta.status_code >= 400 and resposta.status_code != 409:
            return ResultadoEmissao(
                autorizada=False, motivo=self._motivo(dados, resposta)
            )

        # NFC-e é síncrona: o próprio POST costuma trazer o resultado final.
        if status == "autorizado":
            return self._montar_autorizacao(dados)
        if status in ("erro_autorizacao", "denegado", "erro", "cancelado"):
            return ResultadoEmissao(
                autorizada=False, motivo=self._motivo(dados, resposta)
            )

        # NF-e (assíncrona) ou 409: consulta a referência.
        try:
            consulta = httpx.get(
                f"{self.base_url}/v2/{recurso}/{referencia}",
                auth=(self.token, ""),
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise ErroComunicacao(str(exc)) from exc
        if consulta.status_code == 429 or consulta.status_code >= 500:
            raise ErroComunicacao(f"Focus NFe indisponível ({consulta.status_code})")
        if consulta.status_code >= 400:
            # POST aceito mas consulta ainda não disponível: tenta de novo depois.
            raise ErroComunicacao(
                f"Consulta indisponível na Focus (HTTP {consulta.status_code})."
            )

        dados = consulta.json() if consulta.content else {}
        status = dados.get("status", "")
        if status == "autorizado":
            return self._montar_autorizacao(dados)
        if status in STATUS_PROCESSANDO or not status:
            raise ErroComunicacao(
                "Nota ainda em processamento na SEFAZ; nova tentativa em instantes."
            )
        return ResultadoEmissao(autorizada=False, motivo=self._motivo(dados, consulta))

    def cancelar(self, nota: Nota, justificativa: str) -> ResultadoEvento:
        if not self.token:
            return ResultadoEvento(
                autorizado=False,
                motivo="Token da Focus NFe não configurado (Configurações).",
            )
        try:
            resposta = httpx.request(
                "DELETE",
                f"{self.base_url}/v2/{self._recurso(nota)}/{self._referencia(nota)}",
                json={"justificativa": justificativa},
                auth=(self.token, ""),
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise ErroComunicacao(str(exc)) from exc
        if resposta.status_code == 429 or resposta.status_code >= 500:
            raise ErroComunicacao(f"Focus NFe indisponível ({resposta.status_code})")
        dados = resposta.json() if resposta.content else {}
        status = dados.get("status", "")
        if status in STATUS_PROCESSANDO:
            raise ErroComunicacao(
                "Cancelamento ainda em processamento; nova tentativa em instantes."
            )
        if resposta.status_code < 400 and status == "cancelado":
            return ResultadoEvento(
                autorizado=True,
                protocolo=str(dados.get("numero_protocolo", "")),
                xml=self._baixar(dados.get("caminho_xml_cancelamento", "")),
            )
        return ResultadoEvento(
            autorizado=False, motivo=self._motivo(dados, resposta)
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
        if resposta.status_code == 429 or resposta.status_code >= 500:
            raise ErroComunicacao(f"Focus NFe indisponível ({resposta.status_code})")
        dados = resposta.json() if resposta.content else {}
        status = dados.get("status", "")
        if status in STATUS_PROCESSANDO:
            raise ErroComunicacao(
                "Carta de correção ainda em processamento; nova tentativa em instantes."
            )
        if resposta.status_code < 400 and status in ("autorizado", "registrado"):
            return ResultadoEvento(
                autorizado=True,
                protocolo=str(dados.get("numero_protocolo", "")),
                sequencia=int(
                    dados.get("numero_carta_correcao") or dados.get("numero") or 0
                ),
                xml=self._baixar(dados.get("caminho_xml_carta_correcao", "")),
            )
        return ResultadoEvento(
            autorizado=False, motivo=self._motivo(dados, resposta)
        )

    def inutilizar(
        self,
        emitente: dict[str, str],
        modelo: int,
        serie: int,
        ano: int,
        numero_inicial: int,
        numero_final: int,
        justificativa: str,
    ) -> ResultadoEvento:
        if not self.token:
            return ResultadoEvento(
                autorizado=False,
                motivo="Token da Focus NFe não configurado (Configurações).",
            )
        recurso = "nfce" if modelo == 65 else "nfe"
        cnpj = "".join(c for c in emitente.get("emitente_cnpj", "") if c.isdigit())
        try:
            resposta = httpx.post(
                f"{self.base_url}/v2/{recurso}/inutilizacao",
                json={
                    "cnpj": cnpj,
                    "ano": ano,
                    "serie": str(serie),
                    "numero_inicial": str(numero_inicial),
                    "numero_final": str(numero_final),
                    "justificativa": justificativa,
                },
                auth=(self.token, ""),
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise ErroComunicacao(str(exc)) from exc
        if resposta.status_code == 429 or resposta.status_code >= 500:
            raise ErroComunicacao(f"Focus NFe indisponível ({resposta.status_code})")
        dados = resposta.json() if resposta.content else {}
        status = dados.get("status", "")
        if status in STATUS_PROCESSANDO:
            raise ErroComunicacao(
                "Inutilização ainda em processamento; nova tentativa em instantes."
            )
        if resposta.status_code < 400 and status == "autorizado":
            return ResultadoEvento(
                autorizado=True,
                protocolo=str(
                    dados.get("numero_protocolo") or dados.get("protocolo") or ""
                ),
                xml=self._baixar(
                    dados.get("caminho_xml") or dados.get("caminho_xml_inutilizacao") or ""
                ),
            )
        return ResultadoEvento(
            autorizado=False, motivo=self._motivo(dados, resposta)
        )
