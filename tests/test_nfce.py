"""NFC-e e mensagens de WhatsApp para cancelamento/CC-e."""
import os
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="nf-nfce-")
os.environ["NF_DATA_DIR"] = TMP


class FluxoNfceWhatsapp(unittest.TestCase):
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
            "nome": "Marina NFC-e", "cpf_cnpj": "16899535009",
            "email": "marina@example.com", "whatsapp": "11966665555",
        }).json()
        produto = cls.client.post("/api/produtos", json={
            "descricao": "Produto teste", "preco": 10.0, "ncm": "61091000",
        }).json()
        cls.cliente_id = cliente["id"]
        cls.produto_id = produto["id"]

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_emitir_nfce_cupom_e_qr(self):
        r = self.client.post("/api/notas", json={
            "modelo": 65,
            "forma_pagamento": "17",
            "consumidor_cpf": "11144477735",
            "itens": [{"produto_id": self.produto_id, "quantidade": 2}],
            "emitir_agora": True,
        })
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["modelo"], 65)
        self.client.post("/api/notas/processar-fila")
        nota = self.client.get(f"/api/notas/{r.json()['id']}").json()
        self.assertEqual(nota["status"], "AUTORIZADA")
        self.assertEqual(nota["chave_acesso"][20:22], "65")
        self.assertTrue(nota["qrcode_url"])
        pdf = self.client.get(f"/api/notas/{nota['id']}/danfe")
        self.assertEqual(pdf.status_code, 200)
        self.assertGreater(len(pdf.content), 500)

        cce = self.client.post(
            f"/api/notas/{nota['id']}/carta-correcao",
            json={"texto": "Tentativa de carta de correcao em NFC-e."},
        )
        self.assertEqual(cce.status_code, 409)

    def test_whatsapp_cancelamento_e_carta(self):
        criada = self.client.post("/api/notas", json={
            "cliente_id": self.cliente_id,
            "itens": [{"produto_id": self.produto_id, "quantidade": 1}],
            "emitir_agora": True,
        }).json()
        self.client.post("/api/notas/processar-fila")
        self.client.post(
            f"/api/notas/{criada['id']}/carta-correcao",
            json={"texto": "Corrigir o complemento do endereco para sala 3."},
        )
        self.client.post("/api/notas/processar-fila")
        wa = self.client.get(f"/api/notas/{criada['id']}/whatsapp?tipo=carta").json()
        self.assertIn("carta de correção", wa["mensagem"].lower())
        self.assertIn("11966665555", wa["telefone"] or wa["link"])

        self.client.post(
            f"/api/notas/{criada['id']}/cancelar",
            json={"texto": "Emissao em duplicidade do mesmo pedido."},
        )
        self.client.post("/api/notas/processar-fila")
        wa = self.client.get(f"/api/notas/{criada['id']}/whatsapp?tipo=cancelamento").json()
        self.assertIn("cancelada", wa["mensagem"].lower())
        self.assertTrue(wa["link"].startswith("https://wa.me/"))


if __name__ == "__main__":
    unittest.main()
