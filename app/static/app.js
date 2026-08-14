/* Utilidades compartilhadas por todas as páginas. */

async function api(url, opcoes = {}) {
  const config = { headers: { "Content-Type": "application/json" }, ...opcoes };
  if (config.body && typeof config.body !== "string") {
    config.body = JSON.stringify(config.body);
  }
  const resposta = await fetch(url, config);
  if (!resposta.ok) {
    let detalhe = `Erro ${resposta.status}`;
    try {
      const corpo = await resposta.json();
      if (corpo.detail) {
        detalhe = typeof corpo.detail === "string"
          ? corpo.detail
          : corpo.detail.map((e) => e.msg).join("; ");
      }
    } catch (_) { /* resposta sem corpo JSON */ }
    throw new Error(detalhe);
  }
  if (resposta.status === 204) return null;
  return resposta.json();
}

function toast(mensagem, tipo = "") {
  const item = document.createElement("div");
  item.className = `toast-item ${tipo}`;
  item.textContent = mensagem;
  document.getElementById("toast").appendChild(item);
  setTimeout(() => item.remove(), 4500);
}

function dinheiro(valor) {
  return (valor ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function dataHora(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function escapeHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}

/* Marca o item ativo do menu e atualiza o status de conexão. */
document.addEventListener("DOMContentLoaded", () => {
  const caminho = location.pathname;
  document.querySelectorAll(".sidebar nav a").forEach((a) => {
    const href = a.getAttribute("href");
    if (href === caminho || (href !== "/" && caminho.startsWith(href))) {
      a.classList.add("ativo");
    }
  });
  atualizarStatus();
  setInterval(atualizarStatus, 10000);
});

async function atualizarStatus() {
  const caixa = document.getElementById("status-box");
  if (!caixa) return;
  try {
    const s = await api("/api/status");
    const pendentes = (s.notas.pendente || 0) + (s.notas.processando || 0);
    caixa.innerHTML = `
      <div><span class="status-dot ${s.online ? "online" : "offline"}"></span>
        ${s.online ? "On-line" : "Off-line"}</div>
      <div>${pendentes} nota(s) na fila</div>
      <div class="texto-muted">${s.provedor === "focus_nfe" ? "Focus NFe" : "Emissor simulado"}
        · ${s.ambiente === "producao" ? "produção" : "homologação"}</div>`;
    document.dispatchEvent(new CustomEvent("status", { detail: s }));
  } catch (_) {
    caixa.innerHTML = '<div><span class="status-dot offline"></span>Servidor indisponível</div>';
  }
}
