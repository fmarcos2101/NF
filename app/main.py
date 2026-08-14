"""Sistema NF — emissão de notas fiscais com fila off-line.

Executar:  uvicorn app.main:app --port 8000
Acessar:   http://localhost:8000
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import models  # noqa: F401 — registra os modelos no metadata
from .database import garantir_schema
from .routers import clientes, configuracoes, notas, produtos
from .services.fila import worker_fila

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    garantir_schema()
    tarefa = asyncio.create_task(worker_fila())
    yield
    tarefa.cancel()


app = FastAPI(title="Sistema NF", lifespan=lifespan)
app.include_router(clientes.router)
app.include_router(produtos.router)
app.include_router(notas.router)
app.include_router(configuracoes.router)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

PAGINAS = {
    "/": ("dashboard.html", "Início"),
    "/clientes": ("clientes.html", "Clientes"),
    "/produtos": ("produtos.html", "Produtos"),
    "/notas": ("notas.html", "Notas fiscais"),
    "/notas/nova": ("nova_nota.html", "Nova nota"),
    "/notas/nova-nfce": ("nova_nfce.html", "Nova NFC-e"),
    "/configuracoes": ("configuracoes.html", "Configurações"),
}

for rota, (template, titulo) in PAGINAS.items():
    def _criar_handler(template=template, titulo=titulo):
        async def pagina(request: Request) -> HTMLResponse:
            return templates.TemplateResponse(
                request, template, {"titulo": titulo}
            )
        return pagina

    app.get(rota, response_class=HTMLResponse, include_in_schema=False)(_criar_handler())


@app.get("/notas/{nota_id}", response_class=HTMLResponse, include_in_schema=False)
async def pagina_nota(request: Request, nota_id: int) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "nota.html", {"titulo": f"Nota {nota_id}", "nota_id": nota_id}
    )
