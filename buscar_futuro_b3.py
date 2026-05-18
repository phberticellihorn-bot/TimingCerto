"""
buscar_futuro_b3.py — Coleta preços futuros do boi gordo B3 (Pregão Regular)
Fonte: noticiasagricolas.com.br/cotacoes/boi-gordo/boi-gordo-b3-prego-regular
Fonte original: B3

Retorna: lista de {mes, ano, preco_arroba, variacao_pct}
Ex: Outubro/2026 → R$ 350,20/arroba

Pode ser chamado:
  - Pelo scraper.py do servidor (via Selenium headless)
  - Pelo atualizar_historico.py localmente
"""

import json, time, logging, os, re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s")
logger = logging.getLogger(__name__)

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}


def criar_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def parse_mes_ano(txt: str):
    """Converte 'Outubro/2026' para (10, 2026)."""
    txt = txt.strip().lower()
    m = re.match(r'(\w+)/(\d{4})', txt)
    if m:
        mes_nome = m.group(1)
        ano = int(m.group(2))
        mes = MESES_PT.get(mes_nome)
        if mes:
            return mes, ano
    return None, None


def parse_preco(txt: str):
    """Converte '336,55' para 336.55."""
    txt = txt.strip().replace("R$", "").strip()
    txt = re.sub(r'\.(?=\d{3})', '', txt).replace(",", ".")
    try:
        v = float(txt)
        return round(v, 2) if 50 < v < 1000 else None
    except:
        return None


def buscar_futuros_b3() -> list:
    """
    Acessa Notícias Agrícolas e coleta preços futuros do boi gordo B3.
    Retorna lista de dicts: {mes, ano, periodo, preco_arroba, variacao_pct}
    """
    url = "https://www.noticiasagricolas.com.br/cotacoes/boi-gordo/boi-gordo-b3-prego-regular"
    logger.info(f"Buscando futuros B3: {url}")

    driver = criar_driver()
    resultados = []

    try:
        driver.get(url)

        # Aguarda tabela carregar
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
            )
        except:
            logger.warning("Timeout aguardando tabela")

        time.sleep(3)

        # Estrutura da tabela:
        # <td>Outubro/2026</td> | <td>350,20</td> | <td>-0,28</td>
        # Pega apenas o primeiro tbody (fechamento mais recente)
        primeiro_tbody = driver.find_element(By.CSS_SELECTOR, "table tbody")
        linhas = primeiro_tbody.find_elements(By.TAG_NAME, "tr")
        logger.info(f"{len(linhas)} linhas encontradas (primeira tabela)")

        for linha in linhas:
            cols = linha.find_elements(By.TAG_NAME, "td")
            if len(cols) < 2:
                continue

            mes, ano = parse_mes_ano(cols[0].text)
            if not mes or not ano:
                continue

            preco = parse_preco(cols[1].text)
            if not preco:
                continue

            variacao = None
            if len(cols) >= 3:
                try:
                    variacao = float(cols[2].text.strip().replace(",", "."))
                except:
                    pass

            resultados.append({
                "mes":          mes,
                "ano":          ano,
                "periodo":      f"{cols[0].text.strip()}",
                "preco_arroba": preco,
                "variacao_pct": variacao,
            })
            logger.info(f"  {cols[0].text.strip()}: R${preco}/arr ({variacao}%)")

    finally:
        driver.quit()

    return resultados


def salvar_futuros_json(resultados: list):
    """Salva futuros_b3.json na pasta app/"""
    saida = {
        "atualizado": datetime.now().isoformat(),
        "fonte":      "Notícias Agrícolas · B3 Pregão Regular",
        "contratos":  resultados,
    }
    caminho = os.path.join(os.path.dirname(__file__), "app", "futuros_b3.json")
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
        caminho = salvar_futuros_json(resultados)
        logger.info(f"\n✅ {len(resultados)} contratos coletados")
        logger.info(f"Arquivo: {caminho}")
        logger.info("Suba o app/futuros_b3.json no GitHub")
    else:
        logger.error("Nenhum dado coletado")


if __name__ == "__main__":
    main()
