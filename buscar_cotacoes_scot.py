"""
buscar_cotacoes_scot.py — Coleta preços do boi gordo por estado (Scot Consultoria)
Fonte: scotconsultoria.com.br/cotacoes/boi-gordo/
Tabela: "Boi China a Prazo (R$/@)" — preço bruto 30 dias por UF

Salva: app/cotacoes_scot.json
Roda: GitHub Action diariamente às 19h (após fechamento 18h Scot)
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

URL = "https://www.scotconsultoria.com.br/cotacoes/boi-gordo/"

# UFs de interesse + mapeamento para os estados do app
# ATENÇÃO: match exato para evitar "Mato Grosso do Sul" colidir com "Mato Grosso"
UFS_ALVO = {
    "São Paulo":   "SP",
    "Mato Grosso": "MT",
    "Goiás":       "GO",
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


def parse_preco(txt: str):
    """Converte '353,00' ou '353.00' para 353.0"""
    txt = txt.strip().replace("R$", "").replace("@", "").strip()
    txt = re.sub(r'\.(?=\d{3})', '', txt).replace(",", ".")
    try:
        v = float(txt)
        return round(v, 2) if 100 < v < 800 else None
    except:
        return None


def buscar_cotacoes_scot() -> dict:
    """
    Acessa Scot Consultoria e coleta preço bruto 30 dias por UF.
    Retorna dict: {"SP": 353.0, "MT": 357.0, "GO": 330.0}
    """
    logger.info(f"Buscando cotações Scot: {URL}")
    driver = criar_driver()
    resultados = {}

    try:
        driver.get(URL)

        # Aguarda tabela carregar
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
            )
        except:
            logger.warning("Timeout aguardando tabela — tentando mesmo assim")

        time.sleep(3)

        # Localiza todas as tabelas da página
        tabelas = driver.find_elements(By.CSS_SELECTOR, "table")
        logger.info(f"{len(tabelas)} tabela(s) encontrada(s)")

        for tabela in tabelas:
            # Verifica se é a tabela "Boi China a Prazo"
            texto_tabela = tabela.text.lower()
            if "boi china" not in texto_tabela and "prazo" not in texto_tabela:
                continue

            linhas = tabela.find_elements(By.CSS_SELECTOR, "tbody tr")
            logger.info(f"Tabela 'Boi China a Prazo' — {len(linhas)} linhas")

            for linha in linhas:
                cols = linha.find_elements(By.TAG_NAME, "td")
                if len(cols) < 2:
                    continue

                uf_texto = cols[0].text.strip()
                preco_bruto_txt = cols[1].text.strip()  # coluna "Preço bruto 30 dias"

                # Correspondência EXATA para evitar "Mato Grosso do Sul" casar com "Mato Grosso"
                estado_sigla = None
                for nome_uf, sigla in UFS_ALVO.items():
                    if uf_texto.lower() == nome_uf.lower():
                        estado_sigla = sigla
                        break

                if not estado_sigla:
                    continue

                preco = parse_preco(preco_bruto_txt)
                if preco:
                    resultados[estado_sigla] = preco
                    logger.info(f"  {uf_texto} ({estado_sigla}): R$ {preco}/arr")

            # Achou a tabela certa, pode parar
            if resultados:
                break

        if not resultados:
            logger.error("Nenhuma cotação encontrada — estrutura da página pode ter mudado")

    except Exception as e:
        logger.error(f"Erro ao buscar Scot: {e}")
    finally:
        driver.quit()

    return resultados


def salvar_cotacoes_json(cotacoes: dict) -> str:
    """Salva app/cotacoes_scot.json"""
    saida = {
        "atualizado": datetime.now().isoformat(),
        "fonte":      "Scot Consultoria · Boi China a Prazo · Preço bruto 30 dias",
        "url":        URL,
        "cotacoes":   cotacoes,  # {"SP": 353.0, "MT": 357.0, "GO": 330.0}
    }
    caminho = os.path.join(os.path.dirname(__file__), "app", "cotacoes_scot.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ Salvo: {caminho}")
    return caminho


def main():
    logger.info("=" * 60)
    logger.info("TIMING CERTO — Cotações Scot Consultoria por estado")
    logger.info(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    logger.info("=" * 60)

    cotacoes = buscar_cotacoes_scot()

    if cotacoes:
        caminho = salvar_cotacoes_json(cotacoes)
        logger.info(f"\n✅ {len(cotacoes)} estados coletados: {list(cotacoes.keys())}")
        logger.info(f"Arquivo: {caminho}")
        for estado, preco in cotacoes.items():
            logger.info(f"  {estado}: R$ {preco}/arr")
    else:
        logger.error("❌ Nenhuma cotação coletada")
        # Cria arquivo vazio para evitar erro no servidor
        salvar_cotacoes_json({})


if __name__ == "__main__":
    main()
