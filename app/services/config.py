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
    # Acesso
    "auth_usuario": "admin",
    "auth_senha_hash": "",
    "auth_sessao_versao": "1",  # trocar a senha invalida as sessões antigas
    # Impressora térmica (ESC/POS, porta 9100 em geral)
    "impressora_host": "",
    "impressora_porta": "9100",
    # WhatsApp Cloud API (envio automático)
    "whatsapp_token": "",
    "whatsapp_phone_id": "",
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
    """Reserva e retorna o próximo número da sequência de forma atômica.

    O incremento acontece em um único UPDATE dentro de uma transação própria,
    de modo que duas emissões simultâneas nunca recebem o mesmo número
    (o SQLite serializa a escrita).
    """
    from sqlalchemy import text

    from ..database import engine

    chave = "nfce_proximo_numero" if modelo == 65 else "nota_proximo_numero"
    padrao = PADROES.get(chave, "1")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO configuracoes (chave, valor) "
            "SELECT :chave, :padrao "
            "WHERE NOT EXISTS (SELECT 1 FROM configuracoes WHERE chave = :chave)"
        ), {"chave": chave, "padrao": padrao})
        linha = conn.execute(text(
            "UPDATE configuracoes "
            "SET valor = CAST(CAST(valor AS INTEGER) + 1 AS TEXT) "
            "WHERE chave = :chave "
            "RETURNING CAST(valor AS INTEGER) - 1"
        ), {"chave": chave}).fetchone()
    db.expire_all()
    return int(linha[0])
