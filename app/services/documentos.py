"""Validação de CPF e CNPJ (dígitos verificadores)."""


def so_digitos(valor: str) -> str:
    return "".join(c for c in (valor or "") if c.isdigit())


def _todos_iguais(digitos: str) -> bool:
    return len(set(digitos)) == 1


def _dv(digitos: str, pesos: list[int]) -> str:
    soma = sum(int(d) * p for d, p in zip(digitos, pesos))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def cpf_valido(valor: str) -> bool:
    n = so_digitos(valor)
    if len(n) != 11 or _todos_iguais(n):
        return False
    d1 = _dv(n[:9], list(range(10, 1, -1)))
    d2 = _dv(n[:9] + d1, list(range(11, 1, -1)))
    return n[-2:] == d1 + d2


def cnpj_valido(valor: str) -> bool:
    n = so_digitos(valor)
    if len(n) != 14 or _todos_iguais(n):
        return False
    d1 = _dv(n[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _dv(n[:12] + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return n[-2:] == d1 + d2


def validar_cpf_cnpj(valor: str, obrigatorio: bool = False) -> str:
    """Retorna os dígitos se válido. String vazia é aceita se não for obrigatório.

    Levanta ValueError com mensagem em português.
    """
    n = so_digitos(valor)
    if not n:
        if obrigatorio:
            raise ValueError("Informe o CPF ou CNPJ.")
        return ""
    if len(n) == 11:
        if not cpf_valido(n):
            raise ValueError("CPF inválido.")
        return n
    if len(n) == 14:
        if not cnpj_valido(n):
            raise ValueError("CNPJ inválido.")
        return n
    raise ValueError("Informe um CPF (11 dígitos) ou CNPJ (14 dígitos) válido.")
