"""Numeração atômica, fila idempotente, contrato do payload Focus e validações."""
import os
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

TMP = tempfile.mkdtemp(prefix="nf-conf-")
os.environ["NF_DATA_DIR"] = TMP


class Confiabilidade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app.database import garantir_schema
        from app.main import app

        garantir_schema()
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()
        cls.client.put("/api/configuracoes", json={
            "emitente_razao_social": "Empresa Teste LTDA",
            "emitente_cnpj": "12345678000195",
            "emitente_uf": "SP",
        })
        cliente = cls.client.post("/api/clientes", json={
            "nome": "Carlos Confiável", "cpf_cnpj": "39053344705",
            "email": "carlos@example.com", "whatsapp": "11977776666",
        }).json()
        produto = cls.client.post("/api/produtos", json={
            "descricao": "Produto confiável", "preco": 25.0,
            "ncm": "61091000", "csosn": "500",
        }).json()
        cls.cliente_id = cliente["id"]
        cls.produto_id = produto["id"]

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    # ---------- numeração ----------

    def test_rascunho_nao_reserva_numero(self):
        rascunho = self.client.post("/api/notas", json={
            "cliente_id": self.cliente_id,
            "itens": [{"produto_id": self.produto_id, "quantidade": 1}],
            "emitir_agora": False,
        }).json()
        self.assertEqual(rascunho["numero"], 0)
        self.assertEqual(rascunho["status"], "RASCUNHO")

        emitida = self.client.post(f"/api/notas/{rascunho['id']}/emitir").json()
        self.assertGreater(emitida["numero"], 0)
        self.assertEqual(emitida["status"], "PENDENTE")

    def test_criacao_invalida_nao_avanca_sequencia(self):
        from app.database import SessionLocal
        from app.services import config as cfg

        db = SessionLocal()
        try:
            antes = int(cfg.obter(db, "nota_proximo_numero") or "1")
        finally:
            db.close()

        r = self.client.post("/api/notas", json={
            "cliente_id": self.cliente_id,
            "itens": [{"produto_id": 99999, "quantidade": 1}],
            "emitir_agora": True,
        })
        self.assertEqual(r.status_code, 400)

        db = SessionLocal()
        try:
            depois = int(cfg.obter(db, "nota_proximo_numero") or "1")
        finally:
            db.close()
        self.assertEqual(antes, depois)

    def test_numeracao_concorrente_sem_duplicidade(self):
        from app.database import SessionLocal
        from app.services import config as cfg

        numeros: list[int] = []
        trava = threading.Lock()

        def reservar():
            db = SessionLocal()
            try:
                n = cfg.proximo_numero_nota(db)
            finally:
                db.close()
            with trava:
                numeros.append(n)

        threads = [threading.Thread(target=reservar) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(numeros), 8)
        self.assertEqual(len(set(numeros)), 8, f"números duplicados: {sorted(numeros)}")

    # ---------- fila ----------

    def test_fila_nao_processa_a_mesma_nota_duas_vezes(self):
        from app.services import fila

        nota = self.client.post("/api/notas", json={
            "cliente_id": self.cliente_id,
            "itens": [{"produto_id": self.produto_id, "quantidade": 1}],
            "emitir_agora": True,
        }).json()

        resultados: list[dict] = []
        trava = threading.Lock()

        def rodar():
            r = fila.processar_fila()
            with trava:
                resultados.append(r)

        with patch.object(fila, "esta_online", lambda forcar=False: True):
            threads = [threading.Thread(target=rodar) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # O worker de fundo também pode ter pegado a nota; o invariante é que
        # ela foi transmitida UMA única vez (tentativas == 1).
        total = sum(r["notas"] for r in resultados)
        self.assertLessEqual(total, 1, f"nota transmitida {total}x: {resultados}")
        atual = self.client.get(f"/api/notas/{nota['id']}").json()
        self.assertEqual(atual["status"], "AUTORIZADA")
        self.assertEqual(atual["tentativas"], 1)

    def test_fila_recupera_processando_travado(self):
        from app.database import SessionLocal
        from app.models import Nota, StatusNota
        from app.services import config as cfg
        from app.services import fila

        db = SessionLocal()
        try:
            nota = Nota(
                cliente_id=self.cliente_id,
                numero=cfg.proximo_numero_nota(db),
                status=StatusNota.PROCESSANDO,  # simulando queda do processo
                total=10.0,
            )
            db.add(nota)
            db.commit()
            nota_id = nota.id
        finally:
            db.close()

        with patch.object(fila, "esta_online", lambda forcar=False: True):
            fila.processar_fila()

        atual = self.client.get(f"/api/notas/{nota_id}").json()
        self.assertIn(atual["status"], ("AUTORIZADA", "REJEITADA"))

    # ---------- payload Focus ----------

    def _nota_para_payload(self, modelo: int):
        from app.database import SessionLocal
        from app.models import Nota

        criada = self.client.post("/api/notas", json={
            "cliente_id": self.cliente_id,
            "itens": [{"produto_id": self.produto_id, "quantidade": 2}],
            "observacoes": "Pedido 42",
            "emitir_agora": True,
        }).json()
        db = SessionLocal()
        try:
            nota = db.get(Nota, criada["id"])
            nota.modelo = modelo  # só em memória, para montar o payload
            _ = nota.cliente, nota.itens  # carrega os relacionamentos
            return nota
        finally:
            db.close()

    def test_payload_focus_tem_campos_obrigatorios(self):
        from app.services.emissores.focus_nfe import EmissorFocusNFe

        emissor = EmissorFocusNFe("tok", "homologacao")
        emitente = {"emitente_cnpj": "12345678000195"}

        nota = self._nota_para_payload(55)
        payload = emissor._payload(nota, emitente)
        self.assertIn("data_emissao", payload)
        self.assertEqual(payload["numero"], nota.numero)
        self.assertEqual(payload["serie"], nota.serie)
        self.assertEqual(payload["items"][0]["icms_situacao_tributaria"], "500")
        self.assertIn("indicador_inscricao_estadual_destinatario", payload)

        nota_nfce = self._nota_para_payload(65)
        payload_nfce = emissor._payload(nota_nfce, emitente)
        self.assertIn("data_emissao", payload_nfce)
        self.assertEqual(payload_nfce["local_destino"], 1)
        self.assertIn("formas_pagamento", payload_nfce)

    def test_focus_422_e_rejeicao_definitiva(self):
        from app.services.emissores.focus_nfe import EmissorFocusNFe

        emissor = EmissorFocusNFe("tok", "homologacao")
        nota = self._nota_para_payload(55)
        resposta = MagicMock()
        resposta.status_code = 422
        resposta.content = b'{"erros": [{"mensagem": "campo obrigatorio ausente"}]}'
        resposta.json.return_value = {
            "erros": [{"mensagem": "campo obrigatorio ausente"}]
        }
        with patch("app.services.emissores.focus_nfe.httpx.post", return_value=resposta):
            resultado = emissor.emitir(nota, {"emitente_cnpj": "12345678000195"})
        self.assertFalse(resultado.autorizada)
        self.assertIn("campo obrigatorio", resultado.motivo)

    def test_focus_500_volta_para_fila(self):
        from app.services.emissores.base import ErroComunicacao
        from app.services.emissores.focus_nfe import EmissorFocusNFe

        emissor = EmissorFocusNFe("tok", "homologacao")
        nota = self._nota_para_payload(55)
        resposta = MagicMock()
        resposta.status_code = 503
        resposta.content = b""
        with patch("app.services.emissores.focus_nfe.httpx.post", return_value=resposta):
            with self.assertRaises(ErroComunicacao):
                emissor.emitir(nota, {"emitente_cnpj": "12345678000195"})

    def test_referencia_unica_por_nota(self):
        from app.database import SessionLocal
        from app.models import Nota

        db = SessionLocal()
        try:
            referencias = [n.referencia for n in db.query(Nota).all()]
        finally:
            db.close()
        self.assertTrue(all(referencias))
        self.assertEqual(len(referencias), len(set(referencias)))

    # ---------- validações ----------

    def test_validacoes_de_cliente(self):
        casos = [
            {"nome": "X"},                                    # nome curto
            {"nome": "Fulano", "tipo": "XX"},                 # tipo inválido
            {"nome": "Fulano", "email": "sem-arroba"},        # e-mail inválido
            {"nome": "Fulano", "uf": "XYZ"},                  # UF inválida
            {"nome": "Fulano", "cep": "123"},                 # CEP curto
        ]
        for caso in casos:
            r = self.client.post("/api/clientes", json=caso)
            self.assertEqual(r.status_code, 422, f"{caso} -> {r.text}")

        r = self.client.post("/api/clientes", json={
            "nome": "Duplicado", "cpf_cnpj": "39053344705",
        })
        self.assertEqual(r.status_code, 409)

    def test_validacoes_de_produto_e_nota(self):
        casos_produto = [
            {"descricao": "Camiseta", "ncm": "123"},           # NCM inválido
            {"descricao": "Camiseta", "cfop": "9999"},         # CFOP inválido
            {"descricao": "Camiseta", "csosn": "999"},         # CSOSN inválido
            {"descricao": "Camiseta", "preco": -5},            # preço negativo
        ]
        for caso in casos_produto:
            r = self.client.post("/api/produtos", json=caso)
            self.assertEqual(r.status_code, 422, f"{caso} -> {r.text}")

        r = self.client.post("/api/notas", json={
            "cliente_id": self.cliente_id,
            "itens": [{"produto_id": self.produto_id, "quantidade": -1}],
        })
        self.assertEqual(r.status_code, 422)

        r = self.client.post("/api/notas", json={
            "cliente_id": self.cliente_id,
            "itens": [{"produto_id": self.produto_id, "quantidade": 1}],
            "desconto": -10,
        })
        self.assertEqual(r.status_code, 422)

        r = self.client.post("/api/notas", json={
            "cliente_id": self.cliente_id,
            "itens": [{"produto_id": self.produto_id, "quantidade": 1}],
            "forma_pagamento": "XX",
        })
        self.assertEqual(r.status_code, 422)

    def test_produto_desativado_nao_entra_na_nota(self):
        produto = self.client.post("/api/produtos", json={
            "descricao": "Descontinuado", "preco": 5.0, "ncm": "61091000",
        }).json()
        self.client.put(f"/api/produtos/{produto['id']}", json={
            "descricao": "Descontinuado", "preco": 5.0,
            "ncm": "61091000", "ativo": 0,
        })
        r = self.client.post("/api/notas", json={
            "cliente_id": self.cliente_id,
            "itens": [{"produto_id": produto["id"], "quantidade": 1}],
        })
        self.assertEqual(r.status_code, 400)

    # ---------- correção de nota rejeitada ----------

    def test_corrigir_nota_rejeitada(self):
        from app.database import SessionLocal
        from app.models import Nota, StatusNota

        nota = self.client.post("/api/notas", json={
            "cliente_id": self.cliente_id,
            "itens": [{"produto_id": self.produto_id, "quantidade": 1}],
            "emitir_agora": False,
        }).json()
        db = SessionLocal()
        try:
            obj = db.get(Nota, nota["id"])
            obj.status = StatusNota.REJEITADA
            obj.motivo_rejeicao = "Rejeição simulada"
            db.commit()
        finally:
            db.close()

        r = self.client.put(f"/api/notas/{nota['id']}", json={
            "cliente_id": self.cliente_id,
            "itens": [{"produto_id": self.produto_id, "quantidade": 3}],
            "desconto": 5,
            "observacoes": "corrigida",
            "emitir_agora": False,
        })
        self.assertEqual(r.status_code, 200, r.text)
        corrigida = r.json()
        self.assertEqual(corrigida["total"], 70.0)  # 3 x 25 - 5
        self.assertEqual(corrigida["observacoes"], "corrigida")
        self.assertEqual(corrigida["motivo_rejeicao"], "")

    # ---------- sessões e configurações ----------

    def test_troca_de_senha_revoga_sessoes_antigas(self):
        from app.database import SessionLocal
        from app.services import auth

        try:
            r = self.client.post("/api/senha", json={"nova": "senha1x"})
            self.assertEqual(r.status_code, 200, r.text)
            ok = self.client.post("/api/login", json={"usuario": "admin", "senha": "senha1x"})
            self.assertEqual(ok.status_code, 200)
            cookies_antigos = dict(self.client.cookies)

            r = self.client.post("/api/senha", json={"nova": "senha2y", "atual": "senha1x"})
            self.assertEqual(r.status_code, 200, r.text)
            # a própria sessão continua válida após a troca
            self.assertEqual(self.client.get("/api/status").status_code, 200)

            # uma sessão criada antes da troca deixa de valer
            self.client.cookies.clear()
            for nome, valor in cookies_antigos.items():
                self.client.cookies.set(nome, valor)
            self.assertEqual(self.client.get("/api/status").status_code, 401)
        finally:
            db = SessionLocal()
            try:
                auth.remover_senha(db)
            finally:
                db.close()
            self.client.cookies.clear()

    def test_config_nao_grava_nada_se_senha_atual_errada(self):
        from app.database import SessionLocal
        from app.services import auth
        from app.services import config as cfg

        try:
            r = self.client.post("/api/senha", json={"nova": "senha3z"})
            self.assertEqual(r.status_code, 200, r.text)
            self.client.post("/api/login", json={"usuario": "admin", "senha": "senha3z"})

            r = self.client.put("/api/configuracoes", json={
                "emitente_razao_social": "NÃO DEVE GRAVAR",
                "auth_senha_nova": "outrasenha",
                "auth_senha_atual": "errada",
            })
            self.assertEqual(r.status_code, 400)

            db = SessionLocal()
            try:
                razao = cfg.obter(db, "emitente_razao_social")
            finally:
                db.close()
            self.assertEqual(razao, "Empresa Teste LTDA")
        finally:
            db = SessionLocal()
            try:
                auth.remover_senha(db)
            finally:
                db.close()
            self.client.cookies.clear()

    # ---------- mensagens e arquivos ----------

    def test_whatsapp_cloud_nao_promete_anexo(self):
        from app.database import SessionLocal
        from app.models import Nota
        from app.services.whatsapp import montar_link

        db = SessionLocal()
        try:
            nota = db.query(Nota).filter(Nota.numero > 0).first()
            manual = montar_link(nota, {}, tipo="emissao", com_anexo=True)
            automatico = montar_link(nota, {}, tipo="emissao", com_anexo=False)
        finally:
            db.close()
        self.assertIn("anexo", manual["mensagem"])
        self.assertNotIn("anexo", automatico["mensagem"])

    def test_backups_no_mesmo_segundo_nao_colidem(self):
        from app.services import backup

        a = backup.criar()
        b = backup.criar()
        self.assertNotEqual(a.name, b.name)
        self.assertTrue(a.exists() and b.exists())


if __name__ == "__main__":
    unittest.main()
