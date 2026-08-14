"""Validação de dígitos verificadores de CPF e CNPJ."""
import unittest

from app.services.documentos import cnpj_valido, cpf_valido, validar_cpf_cnpj


class Documentos(unittest.TestCase):
    def test_cpf_valido(self):
        self.assertTrue(cpf_valido("11144477735"))
        self.assertTrue(cpf_valido("111.444.777-35"))
        self.assertFalse(cpf_valido("11111111111"))
        self.assertFalse(cpf_valido("12345678900"))
        self.assertFalse(cpf_valido(""))

    def test_cnpj_valido(self):
        self.assertTrue(cnpj_valido("12345678000195"))
        self.assertTrue(cnpj_valido("12.345.678/0001-95"))
        self.assertFalse(cnpj_valido("12345678000199"))
        self.assertFalse(cnpj_valido("00000000000000"))

    def test_validar_opcional(self):
        self.assertEqual(validar_cpf_cnpj(""), "")
        self.assertEqual(validar_cpf_cnpj("111.444.777-35"), "11144477735")
        with self.assertRaises(ValueError):
            validar_cpf_cnpj("", obrigatorio=True)
        with self.assertRaises(ValueError):
            validar_cpf_cnpj("123")


if __name__ == "__main__":
    unittest.main()
