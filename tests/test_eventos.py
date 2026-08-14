"""Fluxo de cancelamento/CC-e na fila off-line, isolado em um diretório temporário."""
import os
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="nf-test-")
os.environ["NF_DATA_DIR"] = TMP


class FluxoEventos(unittest.TestCase):
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
        cls.client.post("/api/clientes", json={
            "nome": "Maria Teste", "cpf_cnpj": "11144477735",
            "email": "maria@example.com", "whatsapp": "11988887777",
        })
        cls.client.post("/api/produtos", json={
            "descricao": "Produto teste", "preco": 10.0, "ncm": "61091000",
        })
        nota = cls.client.post("/api/notas", json={
            "cliente_id": 1,
            "itens": [{"produto_id": 1, "quantidade": 2}],
            "emitir_agora": True,
        }).json()
        cls.client.post("/api/notas/processar-fila")
        cls.nota_id = nota["id"]

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_carta_correcao_e_cancelamento(self):
        r = self.client.post(
            f"/api/notas/{self.nota_id}/carta-correcao",
            json={"texto": "A"},
        )
        self.assertEqual(r.status_code, 422)

        r = self.client.post(
            f"/api/notas/{self.nota_id}/carta-correcao",
            json={"texto": "Corrigir o complemento do endereco para bloco B."},
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["status"], "PENDENTE")

        fila = self.client.post("/api/notas/processar-fila").json()
        self.assertGreaterEqual(fila["eventos"], 1)
        nota = self.client.get(f"/api/notas/{self.nota_id}").json()
        self.assertEqual(nota["eventos"][0]["status"], "AUTORIZADO")
        self.assertEqual(nota["status"], "AUTORIZADA")

        r = self.client.post(
            f"/api/notas/{self.nota_id}/cancelar",
            json={"texto": "Emissao em duplicidade do mesmo pedido."},
        )
        self.assertEqual(r.status_code, 201)
        self.client.post("/api/notas/processar-fila")
        nota = self.client.get(f"/api/notas/{self.nota_id}").json()
        self.assertEqual(nota["status"], "CANCELADA")
        self.assertTrue(nota["cancelada_em"])

        r = self.client.post(
            f"/api/notas/{self.nota_id}/cancelar",
            json={"texto": "Nova tentativa de cancelamento da nota."},
        )
        self.assertEqual(r.status_code, 409)

    def test_duplicar_e_backup(self):
        r = self.client.post(f"/api/notas/{self.nota_id}/duplicar")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["status"], "RASCUNHO")
        self.assertEqual(len(r.json()["itens"]), 1)

        backup = self.client.post("/api/backups").json()
        self.assertTrue(backup["nome"].startswith("nf-backup-"))
        down = self.client.get(f"/api/backups/{backup['nome']}")
        self.assertEqual(down.status_code, 200)
        self.assertGreater(len(down.content), 100)

    def test_evento_fica_na_fila_offline(self):
        from app.services import fila
        from app.database import SessionLocal
        from app.models import Cliente, Nota, NotaItem, Produto, StatusNota
        from app.services import config as cfg

        db = SessionLocal()
        cliente = db.query(Cliente).first()
        produto = db.query(Produto).first()
        nota = Nota(
            cliente_id=cliente.id,
            numero=cfg.proximo_numero_nota(db),
            status=StatusNota.AUTORIZADA,
            total=produto.preco,
            chave_acesso="35260812345678000199550010000000991111111111",
        )
        nota.itens.append(NotaItem(
            produto_id=produto.id, descricao=produto.descricao,
            ncm=produto.ncm, cfop=produto.cfop, unidade=produto.unidade,
            quantidade=1, preco_unitario=produto.preco, total=produto.preco,
        ))
        db.add(nota)
        db.commit()
        nota_id = nota.id
        db.close()

        r = self.client.post(
            f"/api/notas/{nota_id}/cancelar",
            json={"texto": "Cancelamento enquanto o sistema esta offline."},
        )
        self.assertEqual(r.status_code, 201)

        original = fila.URL_TESTE_CONEXAO
        fila.URL_TESTE_CONEXAO = "https://endereco-inexistente.invalid"
        fila._estado["verificado_em"] = 0
        resultado = fila.processar_fila()
        fila.URL_TESTE_CONEXAO = original
        fila._estado["verificado_em"] = 0
        self.assertEqual(resultado["eventos"], 0)
        nota = self.client.get(f"/api/notas/{nota_id}").json()
        self.assertEqual(nota["status"], "AUTORIZADA")
        self.assertEqual(nota["eventos"][0]["status"], "PENDENTE")

        resultado = fila.processar_fila()
        self.assertEqual(resultado["eventos"], 1)
        nota = self.client.get(f"/api/notas/{nota_id}").json()
        self.assertEqual(nota["status"], "CANCELADA")


if __name__ == "__main__":
    unittest.main()
