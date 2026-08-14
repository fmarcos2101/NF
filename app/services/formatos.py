"""Formatação de valores no padrão brasileiro."""


def moeda(valor: float) -> str:
    texto = f"{valor:,.2f}".replace(",", "\0").replace(".", ",").replace("\0", ".")
    return f"R$ {texto}"
