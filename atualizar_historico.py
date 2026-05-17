"""
atualizar_historico.py — Coleta automática do histórico de preços do boi gordo
Fonte: Agrolink.com.br (boi gordo 15kg — MT, SP, GO)

Como usar:
  1. Instale as dependências: pip install selenium webdriver-manager
  2. Execute: python atualizar_historico.py
  3. O arquivo historico.json será gerado/atualizado na pasta app/
  4. Suba o historico.json atualizado no GitHub
  5. O Render usará os dados novos automaticamente

Frequência recomendada: 1x por mês
"""

import json
import time
import logging
import os
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s — %(levelname)s — %(message)s"
)
logger = logging.getLogger(__name__)

# ── Configuração ─────────────────────────────────────────────────────────────

ESTADOS = {
    "MT": "mt",
    "SP": "sp",
    "GO": "go",
}

ANO_INICIO = 2020
ANO_FIM = datetime.now().year

MESES_CHUVA = {
    "MT": [True,True,True,False,False,False,False,False,True,True,True,True],
    "SP": [True,True,True,False,False,False,False,False,True,True,True,True],
    "GO": [True,True,True,False,False,False,False,False,True,True,True,True],
}

MESES_NOME = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]

# ── Driver ────────────────────────────────────────────────────────────────────

def criar_driver():
    """Cria driver Chrome headless."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


# ── Scraping Agrolink ─────────────────────────────────────────────────────────

def coletar_historico_estado(driver, estado_sigla: str, estado_url: str) -> dict:
    """
    Acessa Agrolink e coleta histórico mensal de preços por ano.
    Retorna: { 2020: [jan, fev, ..., dez], 2021: [...], ... }
    """
    url = f"https://www.agrolink.com.br/cotacoes/historico/{estado_url}/boi-gordo-15kg"
    logger.info(f"Coletando {estado_sigla} — {url}")

    historico = {}

    try:
        driver.get(url)
        time.sleep(3)  # aguarda JS carregar

        wait = WebDriverWait(driver, 15)

        # Tenta localizar o seletor de ano (geralmente um <select> ou botões)
        try:
            select_ano = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "select[name*='ano'], select#ano, .select-ano"))
            )
            anos_disponiveis = [opt.get_attribute("value") for opt in Select(select_ano).options if opt.get_attribute("value")]
        except:
            # Se não tiver seletor de ano, tenta pegar todos os anos da tabela diretamente
            anos_disponiveis = [str(a) for a in range(ANO_INICIO, ANO_FIM + 1)]

        for ano_str in anos_disponiveis:
            ano = int(ano_str)
            if ano < ANO_INICIO or ano > ANO_FIM:
                continue

            logger.info(f"  {estado_sigla} — coletando {ano}...")

            # Seleciona o ano se houver dropdown
            try:
                select_el = driver.find_element(By.CSS_SELECTOR, "select[name*='ano'], select#ano, .select-ano")
                Select(select_el).select_by_value(str(ano))
                time.sleep(2)
            except:
                pass

            # Busca a tabela de preços
            precos_ano = extrair_precos_tabela(driver, ano)
            if precos_ano:
                historico[ano] = precos_ano
                logger.info(f"  ✅ {estado_sigla}/{ano}: {precos_ano}")
            else:
                logger.warning(f"  ⚠️ {estado_sigla}/{ano}: tabela não encontrada")

    except Exception as e:
        logger.error(f"Erro coletando {estado_sigla}: {e}")

    return historico


def extrair_precos_tabela(driver, ano: int) -> list:
    """
    Tenta extrair 12 valores mensais da tabela de preços na página atual.
    Retorna lista de 12 floats [jan, fev, ..., dez] ou None se falhar.
    """
    estrategias = [
        # Estratégia 1: tabela com classe comum no Agrolink
        "table.table-cotacoes tbody tr",
        "table.cotacoes tbody tr",
        ".tabela-historico tbody tr",
        "table tbody tr",
    ]

    for seletor in estrategias:
        try:
            linhas = driver.find_elements(By.CSS_SELECTOR, seletor)
            precos = []

            for linha in linhas:
                cols = linha.find_elements(By.TAG_NAME, "td")
                for col in cols:
                    txt = col.text.strip()
                    # Limpa e converte
                    txt_limpo = txt.replace("R$", "").replace(".", "").replace(",", ".").strip()
                    try:
                        valor = float(txt_limpo)
                        if 100 < valor < 700:  # faixa realista R$/arroba
                            precos.append(round(valor, 2))
                    except:
                        continue

            # Espera exatamente 12 valores (um por mês)
            if len(precos) == 12:
                return precos
            # Se tiver mais, pega os 12 primeiros
            if len(precos) > 12:
                return precos[:12]

        except Exception:
            continue

    # Estratégia alternativa: busca todos os números da página
    try:
        elementos = driver.find_elements(By.XPATH, "//*[contains(@class,'preco') or contains(@class,'valor') or contains(@class,'cotacao')]")
        precos = []
        for el in elementos:
            txt = el.text.strip().replace("R$","").replace(".","").replace(",",".").strip()
            try:
                v = float(txt)
                if 100 < v < 700:
                    precos.append(round(v, 2))
            except:
                continue
        if len(precos) >= 12:
            return precos[:12]
    except:
        pass

    return None


# ── Pós-processamento ─────────────────────────────────────────────────────────

def calcular_medias(historico_estados: dict) -> dict:
    """
    Calcula médias mensais históricas e comparativo chuva/seca.
    Usado pelo calculador para estimar preço no mês de abate.
    """
    medias = {}

    for estado, historico in historico_estados.items():
        medias_mensais = []
        for mes_idx in range(12):
            valores = [
                historico[ano][mes_idx]
                for ano in historico
                if len(historico[ano]) > mes_idx and historico[ano][mes_idx] > 0
            ]
            media = round(sum(valores) / len(valores), 2) if valores else 0
            medias_mensais.append(media)

        chuva_mask = MESES_CHUVA.get(estado, MESES_CHUVA["MT"])
        precos_chuva = [p for p, c in zip(medias_mensais, chuva_mask) if c and p > 0]
        precos_seca  = [p for p, c in zip(medias_mensais, chuva_mask) if not c and p > 0]

        medias[estado] = {
            "mensais": medias_mensais,
            "media_chuva": round(sum(precos_chuva)/len(precos_chuva), 2) if precos_chuva else 0,
            "media_seca":  round(sum(precos_seca)/len(precos_seca), 2)  if precos_seca  else 0,
        }

    return medias


def gerar_comparativo_chuva_seca(historico_estados: dict) -> dict:
    """Gera comparativo chuva vs seca por ano e estado — usado nos gráficos."""
    resultado = {}

    for estado, historico in historico_estados.items():
        chuva_mask = MESES_CHUVA.get(estado, MESES_CHUVA["MT"])
        resultado[estado] = []

        for ano in sorted(historico.keys()):
            precos = historico[ano]
            if len(precos) < 12:
                continue
            pc = [p for p, c in zip(precos, chuva_mask) if c and p > 0]
            ps = [p for p, c in zip(precos, chuva_mask) if not c and p > 0]
            if pc and ps:
                mc = round(sum(pc)/len(pc), 2)
                ms = round(sum(ps)/len(ps), 2)
                resultado[estado].append({
                    "ano": ano,
                    "media_chuva": mc,
                    "media_seca": ms,
                    "diferenca": round(ms - mc, 2),
                })

    return resultado


# ── Salvar JSON ───────────────────────────────────────────────────────────────

def salvar_json(historico_estados: dict):
    """
    Salva historico.json na pasta app/ com todos os dados processados.
    Este arquivo é carregado pelo scraper.py em vez do histórico hardcoded.
    """
    medias = calcular_medias(historico_estados)
    comparativo = gerar_comparativo_chuva_seca(historico_estados)

    # Gera série completa para os gráficos
    series = {}
    for estado, historico in historico_estados.items():
        series[estado] = []
        chuva_mask = MESES_CHUVA.get(estado, MESES_CHUVA["MT"])
        for ano in sorted(historico.keys()):
            for mes_idx, preco in enumerate(historico[ano]):
                if preco > 0:
                    series[estado].append({
                        "ano": ano,
                        "mes": mes_idx + 1,
                        "mes_nome": MESES_NOME[mes_idx],
                        "periodo": f"{MESES_NOME[mes_idx]}/{ano}",
                        "preco": preco,
                        "chuva": chuva_mask[mes_idx],
                    })

    saida = {
        "atualizado": datetime.now().isoformat(),
        "fonte": "Agrolink.com.br — boi gordo 15kg",
        "historico": historico_estados,
        "medias_mensais": medias,
        "comparativo_chuva_seca": comparativo,
        "series": series,
    }

    caminho = os.path.join(os.path.dirname(__file__), "app", "historico.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    logger.info(f"✅ historico.json salvo em {caminho}")
    logger.info(f"   Estados: {list(historico_estados.keys())}")
    logger.info(f"   Anos: {sorted(list(historico_estados.get('MT', {}).keys()))}")

    return caminho


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("TIMING CERTO — Atualização de histórico de preços")
    logger.info(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    logger.info(f"Estados: {list(ESTADOS.keys())} | Anos: {ANO_INICIO}–{ANO_FIM}")
    logger.info("=" * 60)

    driver = criar_driver()
    historico_completo = {}

    try:
        for sigla, url_param in ESTADOS.items():
            logger.info(f"\n{'─'*40}")
            logger.info(f"Coletando estado: {sigla}")
            historico = coletar_historico_estado(driver, sigla, url_param)

            if historico:
                historico_completo[sigla] = {int(k): v for k, v in historico.items()}
                logger.info(f"✅ {sigla} — {len(historico)} anos coletados")
            else:
                logger.warning(f"⚠️ {sigla} — sem dados, mantendo histórico anterior")

            time.sleep(2)  # pausa entre estados

    finally:
        driver.quit()
        logger.info("\nDriver encerrado")

    if historico_completo:
        caminho = salvar_json(historico_completo)
        logger.info(f"\n{'='*60}")
        logger.info("CONCLUÍDO COM SUCESSO!")
        logger.info(f"Arquivo: {caminho}")
        logger.info("Próximo passo: suba o historico.json no GitHub")
        logger.info("O Render usará os dados atualizados automaticamente")
        logger.info("=" * 60)
    else:
        logger.error("Nenhum dado coletado — verifique a conexão e o site")


if __name__ == "__main__":
    main()
