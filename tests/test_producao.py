"""Inutilização, XML do mês, ESC/POS, login e validação de documentos na API."""
import os
import tempfile
import unittest
import zipfile
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock, patch

TMP = tempfile.mkdtemp(prefix="nf-prod-")
os.environ["NF_DATA_DIR"] = TMP


class Producao(unittest.TestCase):
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
            "nome": "Maria Teste", "cpf_cnpj": "11144477735",
            "email": "maria@example.com", "whatsapp": "11988887777",
        }).json()
        produto = cls.client.post("/api/produtos", json={
            "descricao": "Produto teste", "preco": 10.0, "ncm": "61091000",
        }).json()
        cls.cliente_id = cliente["id"]
        cls.produto_id = produto["id"]
        nota = cls.client.post("/api/notas", json={
            "cliente_id": cls.cliente_id,
            "itens": [{"produto_id": cls.produto_id, "quantidade": 1}],
            "emitir_agora": True,
        }).json()
        cls.client.post("/api/notas/processar-fila")
        cls.nota_id = nota["id"]

    @classmethod
    def tearDownClass(cls):
        from app.database import SessionLocal
        from app.services import auth
        db = SessionLocal()
        try:
            auth.remover_senha(db)
        finally:
            db.close()
        cls._ctx.__exit__(None, None, None)

    def test_rejeita_cpf_cnpj_invalido(self):
        r = self.client.post("/api/clientes", json={"nome": "Inválido", "cpf_cnpj": "11111111111"})
        self.assertEqual(r.status_code, 400)
        r = self.client.put("/api/configuracoes", json={"emitente_cnpj": "12345678000199"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/notas", json={
            "modelo": 65,
            "consumidor_cpf": "12345678900",
            "itens": [{"produto_id": self.produto_id, "quantidade": 1}],
        })
        self.assertEqual(r.status_code, 400)

    def test_inutilizacao_na_fila(self):
        r = self.client.post("/api/inutilizacoes", json={
            "modelo": 55,
            "serie": 1,
            "numero_inicial": 90,
            "numero_final": 92,
            "justificativa": "Falha ao gravar a nota no sistema.",
        })
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["status"], "PENDENTE")
        fila = self.client.post("/api/notas/processar-fila").json()
        self.assertGreaterEqual(fila["inutilizacoes"], 1)
        lista = self.client.get("/api/inutilizacoes").json()
        item = next(i for i in lista if i["id"] == r.json()["id"])
        self.assertEqual(item["status"], "AUTORIZADA")
        xml = self.client.get(f"/api/inutilizacoes/{item['id']}/xml")
        self.assertEqual(xml.status_code, 200)
        self.assertIn(b"INUTILIZA", xml.content.upper())

    def test_inutilizacao_fica_na_fila_offline(self):
        from app.services import fila

        r = self.client.post("/api/inutilizacoes", json={
            "modelo": 65,
            "serie": 1,
            "numero_inicial": 3,
            "numero_final": 3,
            "justificativa": "Numero pulado na serie da NFC-e.",
        })
        self.assertEqual(r.status_code, 201)
        original = fila.URL_TESTE_CONEXAO
        fila.URL_TESTE_CONEXAO = "https://endereco-inexistente.invalid"
        fila._estado["verificado_em"] = 0
        resultado = fila.processar_fila()
        fila.URL_TESTE_CONEXAO = original
        fila._estado["verificado_em"] = 0
        self.assertEqual(resultado["inutilizacoes"], 0)
        item = self.client.get("/api/inutilizacoes").json()
        alvo = next(i for i in item if i["id"] == r.json()["id"])
        self.assertEqual(alvo["status"], "PENDENTE")
        resultado = fila.processar_fila()
        self.assertGreaterEqual(resultado["inutilizacoes"], 1)

    def test_xml_do_mes(self):
        agora = datetime.now()
        r = self.client.get(f"/api/contabilidade/xml?ano={agora.year}&mes={agora.month}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.content.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(r.content)) as zf:
            nomes = zf.namelist()
        self.assertTrue(any(n.endswith(".xml") for n in nomes))

    def test_escpos(self):
        r = self.client.get(f"/api/notas/{self.nota_id}/escpos")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"\x1b@"))
        self.assertGreater(len(r.content), 40)
        sem_host = self.client.post(f"/api/notas/{self.nota_id}/imprimir")
        self.assertEqual(sem_host.status_code, 400)

    def test_whatsapp_cloud_sem_config(self):
        from app.database import SessionLocal
        from app.models import Nota
        from app.services.whatsapp import enviar_cloud

        db = SessionLocal()
        try:
            nota = db.get(Nota, self.nota_id)
            r = enviar_cloud(nota, {}, tipo="emissao")
            self.assertFalse(r["enviado"])
        finally:
            db.close()

    def test_whatsapp_cloud_envia(self):
        from app.database import SessionLocal
        from app.models import Nota
        from app.services import config as cfg
        from app.services.whatsapp import enviar_cloud

        db = SessionLocal()
        try:
            cfg.gravar(db, {"whatsapp_token": "tok", "whatsapp_phone_id": "123"})
            nota = db.get(Nota, self.nota_id)
            fake = MagicMock()
            fake.status_code = 200
            fake.text = "{}"
            with patch("app.services.whatsapp.httpx.post", return_value=fake) as mock:
                r = enviar_cloud(nota, cfg.obter_todas(db), tipo="emissao")
            self.assertTrue(r["enviado"])
            mock.assert_called_once()
            cfg.gravar(db, {"whatsapp_token": "", "whatsapp_phone_id": ""})
        finally:
            db.close()

    def test_login_protege_o_painel(self):
        from app.database import SessionLocal
        from app.services import auth

        try:
            r = self.client.post("/api/senha", json={"nova": "secret1"})
            self.assertEqual(r.status_code, 200, r.text)
            self.client.cookies.clear()
            bloqueado = self.client.get("/api/status")
            self.assertEqual(bloqueado.status_code, 401)
            pagina = self.client.get("/notas", follow_redirects=False)
            self.assertEqual(pagina.status_code, 302)
            self.assertTrue(pagina.headers["location"].endswith("/login"))
            errado = self.client.post("/api/login", json={"usuario": "admin", "senha": "errada"})
            self.assertEqual(errado.status_code, 401)
            ok = self.client.post("/api/login", json={"usuario": "admin", "senha": "secret1"})
            self.assertEqual(ok.status_code, 200)
            status = self.client.get("/api/status")
            self.assertEqual(status.status_code, 200)
            self.assertTrue(status.json()["auth_ativa"])
            self.client.post("/api/logout")
        finally:
            db = SessionLocal()
            try:
                auth.remover_senha(db)
            finally:
                db.close()
            self.client.cookies.clear()
        livre = self.client.get("/api/status")
        self.assertEqual(livre.status_code, 200)


if __name__ == "__main__":
    unittest.main()
