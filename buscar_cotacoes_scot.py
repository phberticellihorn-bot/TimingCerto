"""
buscar_cotacoes_scot.py — Coleta preços do boi gordo por estado (Scot Consultoria)
Fonte: scotconsultoria.com.br/cotacoes/boi-gordo/
Tabela: "Boi China a Prazo (R$/@)" — preço bruto 30 dias por UF

Salva: app/cotacoes_scot.json
Roda: GitHub Action diariamente às 21:44 BRT
"""

import json, logging, os, re, time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s")
logger = logging.getLogger(__name__)

URL = "https://www.scotconsultoria.com.br/cotacoes/boi-gordo/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

# UFs de interesse + mapeamento para os estados do app
# ATENÇÃO: match exato para evitar "Mato Grosso do Sul" colidir com "Mato Grosso"
UFS_ALVO = {
    "São Paulo":   "SP",
    "Mato Grosso": "MT",
    "Goiás":       "GO",
}


def parse_preco(txt: str):
    """Converte '353,00' ou '353.00' para 353.0"""
    txt = txt.strip().replace("R$", "").replace("@", "").strip()
    txt = re.sub(r'\.(?=\d{3})', '', txt).replace(",", ".")
    try:
        v = float(txt)
        return round(v, 2) if 100 < v < 800 else None
    except Exception:
        return None


def buscar_cotacoes_scot() -> dict:
    """
    Acessa Scot Consultoria e coleta preço bruto 30 dias por UF.
    Retorna dict: {"SP": 353.0, "MT": 357.0, "GO": 330.0}
    Tenta até 3 vezes com backoff em caso de falha temporária.
    """
    logger.info(f"Buscando cotações Scot: {URL}")

    html = None
    for tentativa in range(1, 4):
        try:
            response = requests.get(URL, headers=HEADERS, timeout=30)
            response.raise_for_status()
            html = response.text
            logger.info(f"Página obtida com sucesso (tentativa {tentativa}, status {response.status_code}, {len(html)} chars)")
            break
        except requests.RequestException as e:
            logger.warning(f"Tentativa {tentativa}/3 falhou: {e}")
            if tentativa < 3:
                time.sleep(5 * tentativa)

    if not html:
        logger.error("Não foi possível obter a página após 3 tentativas")
        return {}

    soup = BeautifulSoup(html, "html.parser")
    tabelas = soup.find_all("table")
    logger.info(f"{len(tabelas)} tabela(s) encontrada(s) no HTML")

    resultados = {}

    for tabela in tabelas:
        texto_tabela = tabela.get_text().lower()
        if "boi china" not in texto_tabela and "prazo" not in texto_tabela:
            continue

        linhas = tabela.select("tbody tr")
        logger.info(f"Tabela 'Boi China a Prazo' — {len(linhas)} linhas")

        for linha in linhas:
            cols = linha.find_all("td")
            if len(cols) < 2:
                continue

            uf_texto = cols[0].get_text(strip=True)
            preco_bruto_txt = cols[1].get_text(strip=True)

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

        if resultados:
            break

    # Fallback: se não achou tabela "boi china", loga o HTML para diagnóstico
    if not resultados:
        logger.error("Nenhuma cotação encontrada — estrutura da página pode ter mudado")
        logger.debug(f"HTML recebido (primeiros 2000 chars):\n{html[:2000]}")

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
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
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
        salvar_cotacoes_json({})


if __name__ == "__main__":
    main()
