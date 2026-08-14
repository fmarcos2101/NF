"""Leitura e gravação das configurações (emitente, SMTP, provedor de emissão)."""
from sqlalchemy.orm import Session

from ..models import Configuracao

# Chaves conhecidas e seus valores padrão
PADROES = {
    # Emitente
    "emitente_razao_social": "",
    "emitente_nome_fantasia": "",
    "emitente_cnpj": "",
    "emitente_ie": "",
    "emitente_regime": "simples_nacional",
    "emitente_logradouro": "",
    "emitente_numero": "",
    "emitente_bairro": "",
    "emitente_municipio": "",
    "emitente_uf": "",
    "emitente_cep": "",
    # Emissão
    "emissao_provedor": "simulado",  # simulado | focus_nfe
    "emissao_ambiente": "homologacao",  # homologacao | producao
    "focus_nfe_token": "",
    # E-mail (SMTP)
    "smtp_host": "",
    "smtp_porta": "587",
    "smtp_usuario": "",
    "smtp_senha": "",
    "smtp_remetente": "",
    # Nota
    "nota_serie": "1",
    "nota_proximo_numero": "1",
    "nfce_serie": "1",
    "nfce_proximo_numero": "1",
    "backup_intervalo_horas": "24",
}


def obter_todas(db: Session) -> dict[str, str]:
    valores = dict(PADROES)
    for cfg in db.query(Configuracao).all():
        valores[cfg.chave] = cfg.valor
    return valores


def obter(db: Session, chave: str) -> str:
    cfg = db.get(Configuracao, chave)
    if cfg is not None:
        return cfg.valor
    return PADROES.get(chave, "")


def gravar(db: Session, valores: dict[str, str]) -> None:
    for chave, valor in valores.items():
        if chave not in PADROES:
            continue
        cfg = db.get(Configuracao, chave)
        if cfg is None:
            cfg = Configuracao(chave=chave, valor=str(valor))
            db.add(cfg)
        else:
            cfg.valor = str(valor)
    db.commit()


def proximo_numero_nota(db: Session, modelo: int = 55) -> int:
    """Retorna e incrementa o número sequencial (NF-e e NFC-e têm sequências próprias)."""
    chave = "nfce_proximo_numero" if modelo == 65 else "nota_proximo_numero"
    numero = int(obter(db, chave) or "1")
    gravar(db, {chave: str(numero + 1)})
    return numero
