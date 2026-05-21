"""
buscar_futuro_b3.py — Coleta preços futuros do boi gordo B3 (Pregão Regular)
Fonte: noticiasagricolas.com.br/cotacoes/boi-gordo/boi-gordo-b3-prego-regular

Usa requests + BeautifulSoup — sem Selenium, roda no Render/Railway.
"""

import json, logging, os, re, requests
from datetime import datetime
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s")
logger = logging.getLogger(__name__)

URL = "https://www.noticiasagricolas.com.br/cotacoes/boi-gordo/boi-gordo-b3-prego-regular"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.noticiasagricolas.com.br/",
}

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def parse_mes_ano(txt: str):
    txt = txt.strip().lower()
    m = re.match(r"(\w+)/(\d{4})", txt)
    if m:
        mes = MESES_PT.get(m.group(1))
        ano = int(m.group(2))
        if mes:
            return mes, ano
    return None, None


def parse_preco(txt: str):
    txt = re.sub(r"[^\d,\.]", "", txt.strip())
    txt = re.sub(r"\.(?=\d{3})", "", txt).replace(",", ".")
    try:
        v = float(txt)
        return round(v, 2) if 50 < v < 1500 else None
    except Exception:
        return None


def buscar_futuros_b3() -> list:
    logger.info(f"Buscando futuros B3 via requests: {URL}")
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Falha ao buscar página: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Primeira tabela com tbody
    tbody = soup.find("table")
    if not tbody:
        logger.error("Tabela não encontrada na página")
        return []

    resultados = []
    for tr in tbody.find_all("tr"):
        cols = tr.find_all("td")
        if len(cols) < 2:
            continue

        mes, ano = parse_mes_ano(cols[0].get_text())
        if not mes or not ano:
            continue

        preco = parse_preco(cols[1].get_text())
        if not preco:
            continue

        variacao = None
        if len(cols) >= 3:
            try:
                variacao = float(cols[2].get_text().strip().replace(",", "."))
            except Exception:
                pass

        resultados.append({
            "mes":          mes,
            "ano":          ano,
            "periodo":      cols[0].get_text().strip(),
            "preco_arroba": preco,
            "variacao_pct": variacao,
        })
        logger.info(f"  {cols[0].get_text().strip()}: R${preco}/arr ({variacao}%)")

    logger.info(f"{len(resultados)} contratos coletados")
    return resultados


def salvar_futuros_json(resultados: list) -> str:
    saida = {
        "atualizado": datetime.now().isoformat(),
        "fonte":      "Notícias Agrícolas · B3 Pregão Regular",
        "contratos":  resultados,
    }
    # Salva em app/futuros_b3.json (quando chamado como script)
    caminho = os.path.join(os.path.dirname(__file__), "app", "futuros_b3.json")
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ Salvo: {caminho}")
    return caminho


def main():
    logger.info("=" * 60)
    logger.info("TIMING CERTO — Coleta preços futuros B3")
    logger.info(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    logger.info("=" * 60)

    resultados = buscar_futuros_b3()
    if resultados:
        salvar_futuros_json(resultados)
        logger.info(f"✅ {len(resultados)} contratos coletados")
    else:
        logger.error("Nenhum dado coletado")


if __name__ == "__main__":
    main()
