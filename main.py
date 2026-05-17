"""
main.py — Flask backend do Timing Certo
Rotas:
  GET  /                        → frontend HTML
  GET  /api/preco/atual         → preço atual boi gordo (CEPEA scraping)
  GET  /api/historico/<estado>  → série 5 anos (SP, MT, GO)
  GET  /api/comparativo/estados → comparativo SP x MT x GO
  GET  /api/chuva/<estado>      → comparativo preço chuva vs seca por ano
  GET  /api/clima/<estado>      → previsão climática 16 dias (Open-Meteo)
  POST /api/calcular            → cálculo e recomendação estratégica
"""

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import os

from app.scraper import (
    status_historico,
    scrape_cepea_atual,
    historico_5anos,
    comparativo_chuva_seca,
    comparativo_estados,
    buscar_clima,
)
from app.calculator import calcular

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# Atualiza preço CEPEA a cada 6h automaticamente
scheduler = BackgroundScheduler()
scheduler.add_job(scrape_cepea_atual, "interval", hours=6, id="atualiza_cepea")
scheduler.start()


# ── Frontend ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── API: Preço atual ────────────────────────────────────────────────────────

@app.route("/api/preco/atual")
def api_preco_atual():
    estado = request.args.get("estado", "SP").upper()
    if estado not in ("SP", "MT", "GO"):
        estado = "SP"
    try:
        dados = scrape_cepea_atual(estado)
        return jsonify({"ok": True, "data": dados})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


@app.route("/api/preco/todos")
def api_preco_todos():
    try:
        from app.scraper import scrape_precos_todos_estados
        dados = scrape_precos_todos_estados()
        return jsonify({"ok": True, "data": dados})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


# ── API: Histórico 5 anos ────────────────────────────────────────────────────

@app.route("/api/historico/<estado>")
def api_historico(estado):
    estado = estado.upper()
    if estado not in ("SP", "MT", "GO"):
        return jsonify({"ok": False, "erro": "Estado inválido. Use SP, MT ou GO."}), 400
    try:
        dados = historico_5anos(estado)
        return jsonify({"ok": True, "estado": estado, "data": dados})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


# ── API: Comparativo estados ─────────────────────────────────────────────────

@app.route("/api/comparativo/estados")
def api_comparativo_estados():
    ano = request.args.get("ano", type=int)
    try:
        dados = comparativo_estados(ano)
        return jsonify({"ok": True, "data": dados})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


# ── API: Chuva vs seca ───────────────────────────────────────────────────────

@app.route("/api/chuva/<estado>")
def api_chuva(estado):
    estado = estado.upper()
    if estado not in ("SP", "MT", "GO"):
        return jsonify({"ok": False, "erro": "Estado inválido."}), 400
    try:
        dados = comparativo_chuva_seca(estado)
        return jsonify({"ok": True, "estado": estado, "data": dados})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


# ── API: Clima ───────────────────────────────────────────────────────────────

@app.route("/api/clima/<estado>")
def api_clima(estado):
    estado = estado.upper()
    if estado not in ("SP", "MT", "GO"):
        return jsonify({"ok": False, "erro": "Estado inválido."}), 400
    try:
        dados = buscar_clima(estado)
        return jsonify({"ok": True, "data": dados})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500


# ── API: Calcular ────────────────────────────────────────────────────────────

@app.route("/api/calcular", methods=["POST"])
def api_calcular():
    payload = request.get_json(force=True, silent=True) or {}
    try:
        preco_info = scrape_cepea_atual()
        preco_atual = preco_info["preco"]
        resultado = calcular(payload, preco_atual)
        resultado["preco_fonte"] = preco_info
        return jsonify({"ok": True, "data": resultado})
    except Exception as e:
        logger.exception("Erro no cálculo")
        return jsonify({"ok": False, "erro": str(e)}), 500


# ── Status geral ─────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    """Mostra o que está automático e o que precisa ser atualizado."""
    preco_info = scrape_cepea_atual("SP")
    hist_info  = status_historico()
    return jsonify({
        "ok": True,
        "dados": {
            "preco_atual": {
                "automatico": preco_info.get("automatico", False),
                "fonte":      preco_info.get("fonte", "desconhecida"),
                "status":     "✅ automático (AgroDoc AI · diário)" if preco_info.get("automatico") else "❌ indisponível — " + preco_info.get("erro", ""),
            },
            "historico": {
                "automatico": False,
                "fonte":      "Agrolink via Selenium (local)",
                "status":     "✅ disponível — " + hist_info.get("mensagem","") if hist_info.get("disponivel") else "❌ não gerado — execute: python atualizar_historico.py",
                "detalhes":   hist_info,
            },
            "clima": {
                "automatico": True,
                "fonte":      "Open-Meteo API",
                "status":     "✅ automático (Open-Meteo · a cada 3h)",
            },
        }
    })


# ── Health check (Render/Railway) ────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
