"""
atualizar_historico.py — Coleta automática do histórico de preços do boi gordo
Fonte: Agrolink.com.br (boi gordo 15kg — MT, SP, GO)

Correções v2:
  - Lê TODAS as linhas da tabela (não só 12)
  - Extrai mês/ano de cada linha individualmente (tag <th>)
  - Não replica valores entre anos
  - Ordem correta (jan→dez por ano)

Como usar:
  1. pip install selenium webdriver-manager
  2. python atualizar_historico.py
  3. Suba o app/historico.json no GitHub
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

ESTADOS    = {"MT": "mt", "SP": "sp", "GO": "go"}
ANO_INICIO = 2020
ANO_FIM    = datetime.now().year
MESES_NOME = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
MESES_CHUVA = {
    "MT": [True,True,True,False,False,False,False,False,True,True,True,True],
    "SP": [True,True,True,False,False,False,False,False,True,True,True,True],
    "GO": [True,True,True,False,False,False,False,False,True,True,True,True],
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
    """Converte '347,1245' ou '347.12' para float."""
    txt = txt.strip().replace("R$","").strip()
    txt = re.sub(r'\.(?=\d{3})', '', txt).replace(",", ".")
    try:
        v = float(txt)
        return round(v, 2) if 50 < v < 1000 else None
    except:
        return None


def parse_mes_ano(txt: str):
    """Converte '5/2026' ou '05/2026' para (mes_int, ano_int)."""
    txt = txt.strip()
    m = re.match(r'^(\d{1,2})/(\d{4})$', txt)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def coletar_estado(driver, sigla: str, url_param: str) -> dict:
    """
    Acessa Agrolink e lê TODAS as linhas da tabela de histórico.
    Estrutura real do Agrolink:
      <th class="text-center">5/2026</th>   ← mês/ano
      <td class="text-center">347,1245</td>  ← estadual
      <td class="text-center">337,6396</td>  ← nacional
    Retorna: {2020: [jan,fev,...,dez], 2021: [...], ...}
    """
    url = f"https://www.agrolink.com.br/cotacoes/historico/{url_param}/boi-gordo-15kg"
    logger.info(f"Acessando {sigla}: {url}")
    driver.get(url)

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
        )
    except:
        logger.warning(f"{sigla}: timeout aguardando tabela")

    time.sleep(3)

    linhas = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    logger.info(f"{sigla}: {len(linhas)} linhas encontradas na tabela")

    dados_brutos = {}

    for linha in linhas:
        th_els = linha.find_elements(By.TAG_NAME, "th")
        td_els = linha.find_elements(By.TAG_NAME, "td")

        # Mês/ano vem do <th>
        mes_ano_txt = th_els[0].text if th_els else ""
        mes_ano = parse_mes_ano(mes_ano_txt)
        if not mes_ano:
            continue
        mes, ano = mes_ano

        if ano < ANO_INICIO or ano > ANO_FIM:
            continue

        # Preço estadual vem do primeiro <td>
        preco = parse_preco(td_els[0].text) if td_els else None
        if preco is None and len(td_els) >= 2:
            preco = parse_preco(td_els[1].text)

        if preco:
            dados_brutos[(ano, mes)] = preco
            logger.info(f"  {sigla} {mes:02d}/{ano}: R${preco}")

    if not dados_brutos:
        logger.error(f"{sigla}: nenhum dado extraído — verifique a estrutura da tabela")
        return {}

    historico = {}
    for ano in range(ANO_INICIO, ANO_FIM + 1):
        precos_ano = [dados_brutos.get((ano, mes), 0) for mes in range(1, 13)]
        if any(p > 0 for p in precos_ano):
            historico[ano] = precos_ano

    return historico


def calcular_medias(historico_estados: dict) -> dict:
    medias = {}
    for estado, historico in historico_estados.items():
        medias_mensais = []
        for mes_idx in range(12):
            valores = [
                historico[ano][mes_idx]
                for ano in historico
                if len(historico[ano]) > mes_idx and historico[ano][mes_idx] > 0
            ]
            medias_mensais.append(round(sum(valores)/len(valores), 2) if valores else 0)

        chuva_mask = MESES_CHUVA.get(estado, MESES_CHUVA["MT"])
        pc = [p for p,c in zip(medias_mensais, chuva_mask) if c and p > 0]
        ps = [p for p,c in zip(medias_mensais, chuva_mask) if not c and p > 0]
        medias[estado] = {
            "mensais":     medias_mensais,
            "media_chuva": round(sum(pc)/len(pc), 2) if pc else 0,
            "media_seca":  round(sum(ps)/len(ps), 2) if ps else 0,
        }
    return medias


def gerar_comparativo(historico_estados: dict) -> dict:
    resultado = {}
    for estado, historico in historico_estados.items():
        chuva_mask = MESES_CHUVA.get(estado, MESES_CHUVA["MT"])
        resultado[estado] = []
        for ano in sorted(historico.keys()):
            precos = historico[ano]
            if len(precos) < 12:
                continue
            pc = [p for p,c in zip(precos, chuva_mask) if c and p > 0]
            ps = [p for p,c in zip(precos, chuva_mask) if not c and p > 0]
            if pc and ps:
                resultado[estado].append({
                    "ano":         ano,
                    "media_chuva": round(sum(pc)/len(pc), 2),
                    "media_seca":  round(sum(ps)/len(ps), 2),
                    "diferenca":   round(sum(ps)/len(ps) - sum(pc)/len(pc), 2),
                })
    return resultado


def gerar_series(historico_estados: dict) -> dict:
    series = {}
    for estado, historico in historico_estados.items():
        chuva_mask = MESES_CHUVA.get(estado, MESES_CHUVA["MT"])
        series[estado] = []
        for ano in sorted(historico.keys()):
            for mes_idx, preco in enumerate(historico[ano]):
                if preco and preco > 0:
                    series[estado].append({
                        "ano":      ano,
                        "mes":      mes_idx + 1,
                        "mes_nome": MESES_NOME[mes_idx],
                        "periodo":  f"{MESES_NOME[mes_idx]}/{ano}",
                        "preco":    preco,
                        "chuva":    chuva_mask[mes_idx],
                    })
    return series


def salvar_json(historico_estados: dict):
    saida = {
        "atualizado":             datetime.now().isoformat(),
        "fonte":                  "Agrolink.com.br — boi gordo 15kg — ESTADUAL",
        "historico":              historico_estados,
        "medias_mensais":         calcular_medias(historico_estados),
        "comparativo_chuva_seca": gerar_comparativo(historico_estados),
        "series":                 gerar_series(historico_estados),
    }
    caminho = os.path.join(os.path.dirname(__file__), "app", "historico.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ Salvo: {caminho}")
    return caminho


def main():
    logger.info("=" * 60)
    logger.info("TIMING CERTO — Atualização de histórico v2")
    logger.info(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    logger.info(f"Estados: {list(ESTADOS.keys())} | Anos: {ANO_INICIO}–{ANO_FIM}")
    logger.info("=" * 60)

    driver = criar_driver()
    historico_completo = {}

    try:
        for sigla, url_param in ESTADOS.items():
            logger.info(f"\n{'─'*40}\nColetando: {sigla}")
            historico = coletar_estado(driver, sigla, url_param)
            if historico:
                historico_completo[sigla] = historico
                total = sum(1 for a in historico.values() for p in a if p > 0)
                logger.info(f"✅ {sigla} — {len(historico)} anos — {total} meses com dados")
            else:
                logger.warning(f"⚠️ {sigla} — sem dados")
            time.sleep(2)
    finally:
        driver.quit()

    if historico_completo:
        salvar_json(historico_completo)
        logger.info(f"\n{'='*60}")
        logger.info("CONCLUÍDO!")
        logger.info("=" * 60)
    else:
        logger.error("Nenhum dado coletado.")


if __name__ == "__main__":
    main()
