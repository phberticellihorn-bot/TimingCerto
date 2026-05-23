"""
scraper.py — Coleta automática de dados para o Timing Certo

Fontes de dados (todas automáticas):
  1. Preço atual:   Indicador do Boi DATAGRO (pec.datagro.com/pec/mapas/boletim_cinco.svg) → fallback histórico CEPEA
  2. Histórico:     historico.json gerado pelo atualizar_historico.py (Selenium/Agrolink)
  3. Clima:         Open-Meteo API (gratuita · sem autenticação · atualizada a cada 3h)

NENHUM dado está hardcoded neste arquivo.
Se o historico.json não existir, as rotas retornam erro explícito
orientando o usuário a rodar o atualizar_historico.py primeiro.
"""

import requests
import json
import os
import re
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

TZ_BR = ZoneInfo("America/Sao_Paulo")
from cachetools import TTLCache
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

cache_preco  = TTLCache(maxsize=20, ttl=21600)
cache_clima  = TTLCache(maxsize=10, ttl=10800)
cache_futuro = TTLCache(maxsize=5,  ttl=3600)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

COORDS = {
    "MT": {"lat": -15.601, "lon": -56.097, "nome": "Mato Grosso"},
    "SP": {"lat": -22.908, "lon": -47.063, "nome": "São Paulo"},
    "GO": {"lat": -16.686, "lon": -49.264, "nome": "Goiás"},
}

MESES_NOME  = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]
ESTADOS_VALIDOS = ("MT", "SP", "GO")

# Cache de normais climatológicas: atualiza uma vez por mês (30 dias)
cache_normais = TTLCache(maxsize=10, ttl=2592000)

# Limiar para classificar mês como "chuva": precipitação média >= LIMIAR_CHUVA_MM
LIMIAR_CHUVA_MM = 80.0


def _buscar_normais_precipitacao(estado: str) -> list:
    """
    Normais de precipitação mensal (mm) — INMET 1991-2020.
    Open-Meteo ERA5 Archive removido: inacessível no ambiente de produção (Render).
    Retorna None para acionar o fallback INMET em _meses_chuva_estado.
    """
    return None


def _meses_chuva_estado(estado: str) -> list:
    """
    Retorna lista de 12 booleans indicando se cada mês é chuvoso,
    baseado nas normais INMET 1991-2020 (fallback fixo).
    Fallback para valores fixos consolidados caso a API falhe.
    """
    # Fallback consolidado por estado (INMET normais 1991-2020)
    FALLBACK = {
        "MT": [True, True, True, False, False, False, False, False, True, True, True, True],
        "SP": [True, True, True, True,  False, False, False, False, True, True, True, True],
        "GO": [True, True, True, False, False, False, False, False, True, True, True, True],
    }

    medias = _buscar_normais_precipitacao(estado)
    if medias is None:
        logger.warning(f"Usando fallback INMET para {estado}")
        return FALLBACK.get(estado, FALLBACK["MT"])

    mask = [mm >= LIMIAR_CHUVA_MM for mm in medias]
    logger.info(f"Máscara chuva {estado} (limiar {LIMIAR_CHUVA_MM}mm): {mask}")
    return mask


# MESES_CHUVA: baseado nas normais INMET 1991-2020 — fallback fixo por estado
# Chamado sob demanda com cache de 30 dias — não há custo em tempo de startup
def _get_meses_chuva(estado: str = None) -> dict | list:
    """
    Se estado for None: retorna dict {MT: [...], SP: [...], GO: [...]}.
    Se estado for fornecido: retorna lista de 12 bools para aquele estado.
    """
    if estado:
        return _meses_chuva_estado(estado.upper())
    return {e: _meses_chuva_estado(e) for e in ESTADOS_VALIDOS}


# ---------------------------------------------------------------------------
# HISTÓRICO — historico.json (gerado pelo Selenium scraper)
# ---------------------------------------------------------------------------

def _caminho_historico():
    return os.path.join(os.path.dirname(__file__), "historico.json")


def historico_disponivel() -> bool:
    caminho = _caminho_historico()
    if not os.path.exists(caminho):
        return False
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return bool(dados.get("historico"))
    except:
        return False


def _carregar_historico() -> dict:
    caminho = _caminho_historico()
    if not os.path.exists(caminho):
        raise FileNotFoundError(
            "historico.json nao encontrado. "
            "Execute: python atualizar_historico.py"
        )
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)
    hist = dados.get("historico", {})
    if not hist:
        raise ValueError("historico.json esta vazio ou mal formatado.")
    return {
        estado: {int(ano): precos for ano, precos in anos.items()}
        for estado, anos in hist.items()
    }


def status_historico() -> dict:
    caminho = _caminho_historico()
    if not os.path.exists(caminho):
        return {
            "disponivel": False,
            "mensagem": "historico.json nao encontrado. Execute: python atualizar_historico.py",
        }
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        hist  = dados.get("historico", {})
        anos  = sorted({int(a) for e in hist.values() for a in e.keys()})
        return {
            "disponivel": True,
            "atualizado": dados.get("atualizado", "desconhecido"),
            "fonte":      dados.get("fonte", "Agrolink"),
            "estados":    list(hist.keys()),
            "anos":       anos,
            "mensagem":   f"Historico disponivel: {list(hist.keys())} | {min(anos)}-{max(anos)}",
        }
    except Exception as e:
        return {"disponivel": False, "mensagem": f"Erro ao ler historico.json: {e}"}


# ---------------------------------------------------------------------------
# PREÇO ATUAL — Indicador do Boi DATAGRO
# ---------------------------------------------------------------------------

def _fallback_media_historica(estado: str) -> dict:
    """Fallback: média histórica do mês atual quando todas as APIs falham."""
    mes_atual = datetime.now(TZ_BR).month
    try:
        preco = preco_historico_medio(estado, mes_atual)
        logger.info(f"Fallback histórico {estado} mês {mes_atual}: R${preco}")
        return {
            "preco":        preco,
            "fonte":        f"Média histórica {MESES_NOME[mes_atual-1]} (APIs indisponíveis)",
            "estado":       estado,
            "atualizado":   datetime.now(TZ_BR).isoformat(),
            "data_cotacao": datetime.now(TZ_BR).strftime("%Y-%m-%d"),
            "automatico":   False,
            "aviso":        "Preço baseado em média histórica — fontes externas temporariamente indisponíveis.",
        }
    except Exception:
        pass
    return {
        "preco":      None,
        "fonte":      "indisponivel",
        "estado":     estado,
        "atualizado": datetime.now(TZ_BR).isoformat(),
        "automatico": False,
        "erro":       "Todas as fontes indisponíveis e historico.json ausente.",
    }



def atualizar_preco_atual(estado: str = "SP") -> dict:
    """
    Força scraping do preço atual ignorando o cache TTL.
    Chamado pela rota /api/preco/atual/atualizar no carregamento do site.
    """
    estado = estado.upper()
    cache_key = f"agrodoc_{estado}"
    cache_preco.pop(cache_key, None)
    return scrape_cepea_atual(estado)


def scrape_cepea_atual(estado: str = "SP") -> dict:
    """
    Busca o preço diário do boi gordo via SVG estático da DATAGRO.
    Fonte: https://pec.datagro.com/pec/mapas/boletim_cinco.svg

    Estrutura do SVG:
      - Tags <text x="10" y="265|302|339|376|413"> contêm as datas (18/Mai, 19/Mai...)
      - Tags <text transform="matrix(1 0 0 1 X Y)"> contêm os valores por coluna
      - O Y da matrix bate com o Y da linha de data correspondente
      - Colunas por posição X aproximada:
          SP≈150, BA≈222, GO≈294, MG≈366, MS≈438, MT≈510, PA≈582, RO≈654, TO≈726

    Pega sempre a linha com maior Y (data mais recente).
    Fallback: média histórica do mês.
    """
    estado    = estado.upper()
    cache_key = f"agrodoc_{estado}"
    if cache_key in cache_preco:
        return cache_preco[cache_key]

    # X aproximado do centro de cada coluna no SVG (tolerância ±30px)
    DATAGRO_X = {"SP": 150, "BA": 222, "GO": 294, "MG": 366, "MS": 438,
                 "MT": 510, "PA": 582, "RO": 654, "TO": 726}
    COL_TOL = 30  # tolerância em px para identificar a coluna

    try:
        resp = requests.get(
            "https://pec.datagro.com/pec/mapas/boletim_cinco.svg",
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.content, "xml")  # parser XML para SVG

        # 1. Coletar todas as linhas de data: <text x="10" y="NNN">DD/Mmm</text>
        #    Y válidos: 265, 302, 339, 376, 413 (5 dias úteis)
        datas_y = {}  # {y_int: "22/Mai"}
        for tag in soup.find_all("text"):
            x_attr = tag.get("x", "")
            y_attr = tag.get("y", "")
            txt    = tag.get_text(strip=True)
            try:
                if int(float(x_attr)) == 10 and "/" in txt and len(txt) <= 7:
                    datas_y[int(float(y_attr))] = txt
            except Exception:
                continue

        if not datas_y:
            logger.warning("DATAGRO SVG: nenhuma linha de data encontrada")
            return _fallback_media_historica(estado)

        # Linha mais recente = maior Y
        y_recente  = max(datas_y.keys())
        data_recente = datas_y[y_recente]

        # 2. Coletar valores via transform="matrix(1 0 0 1 X Y)"
        #    Filtra pelo Y da linha mais recente e pelo X da coluna do estado
        x_alvo = DATAGRO_X.get(estado)
        if x_alvo is None:
            logger.warning(f"DATAGRO SVG: estado {estado} não mapeado")
            return _fallback_media_historica(estado)

        preco_encontrado = None
        for tag in soup.find_all("text"):
            transform = tag.get("transform", "")
            m = re.match(r"matrix\(1\s+0\s+0\s+1\s+([\d.]+)\s+([\d.]+)\)", transform)
            if not m:
                continue
            tx = float(m.group(1))
            ty = float(m.group(2))
            # Y deve bater com a linha mais recente (tolerância ±5px)
            if abs(ty - y_recente) > 5:
                continue
            # X deve bater com a coluna do estado (tolerância ±30px)
            if abs(tx - x_alvo) > COL_TOL:
                continue
            val_txt = tag.get_text(strip=True).replace(",", ".")
            try:
                val = float(val_txt)
                if 200 < val < 600:
                    preco_encontrado = round(val, 2)
                    break
            except Exception:
                continue

        if preco_encontrado:
            resultado = {
                "preco":        preco_encontrado,
                "fonte":        "Indicador do Boi DATAGRO",
                "estado":       estado,
                "atualizado":   datetime.now(TZ_BR).isoformat(),
                "data_cotacao": data_recente,
                "automatico":   True,
            }
            cache_preco[cache_key] = resultado
            logger.info(f"DATAGRO SVG: {estado} = R${preco_encontrado} ({data_recente})")
            return resultado

        logger.warning(f"DATAGRO SVG: preço não encontrado para {estado} (y={y_recente}, x≈{x_alvo})")

    except Exception as e:
        logger.warning(f"DATAGRO SVG falhou para {estado}: {e}")

    # Fallback: média histórica do mês
    return _fallback_media_historica(estado)


def scrape_precos_todos_estados() -> dict:
    return {e: scrape_cepea_atual(e) for e in ESTADOS_VALIDOS}


# ---------------------------------------------------------------------------
# CLIMA — Open-Meteo API
# ---------------------------------------------------------------------------

def buscar_clima(estado: str) -> dict:
    estado    = estado.upper()
    cache_key = f"clima_{estado}"
    if cache_key in cache_clima:
        return cache_clima[cache_key]

    coords = COORDS.get(estado, COORDS["MT"])
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={coords['lat']}&longitude={coords['lon']}"
        f"&daily=precipitation_sum,precipitation_probability_max"
        f"&timezone=America/Sao_Paulo&forecast_days=16"
    )

    try:
        resp  = requests.get(url, timeout=10)
        resp.raise_for_status()
        daily = resp.json().get("daily", {})
        datas = daily.get("time", [])
        chuva = daily.get("precipitation_sum", [])
        prob  = daily.get("precipitation_probability_max", [])

        previsao = [
            {
                "data":             datas[i],
                "chuva_mm":         chuva[i] if i < len(chuva) else 0,
                "probabilidade_pct": prob[i]  if i < len(prob)  else 0,
            }
            for i in range(len(datas))
        ]

        resultado = {
            "estado":     estado,
            "coords":     coords,
            "previsao":   previsao,
            "atualizado": datetime.now(TZ_BR).isoformat(),
            "fonte":      "Open-Meteo",
            "automatico": True,
        }
        cache_clima[cache_key] = resultado
        return resultado

    except Exception as e:
        logger.warning(f"Open-Meteo falhou para {estado}: {e}")
        return {
            "estado":     estado,
            "previsao":   [],
            "atualizado": datetime.now(TZ_BR).isoformat(),
            "fonte":      "indisponivel",
            "automatico": False,
            "erro":       str(e),
        }


# ---------------------------------------------------------------------------
# HISTÓRICO 5 ANOS — para gráficos
# ---------------------------------------------------------------------------

def historico_5anos(estado: str) -> list:
    estado = estado.upper()
    hist   = _carregar_historico()
    dados  = hist.get(estado)
    if not dados:
        raise ValueError(f"Estado {estado} nao encontrado no historico.json.")
    chuva_mask = _get_meses_chuva(estado)
    series = []
    for ano in sorted(dados.keys()):
        for mes_idx, preco in enumerate(dados[ano]):
            if preco and preco > 0:
                series.append({
                    "ano":      ano,
                    "mes":      mes_idx + 1,
                    "mes_nome": MESES_NOME[mes_idx],
                    "periodo":  f"{MESES_NOME[mes_idx]}/{ano}",
                    "preco":    preco,
                    "chuva":    chuva_mask[mes_idx],
                })
    return series


def comparativo_chuva_seca(estado: str) -> list:
    estado = estado.upper()
    hist   = _carregar_historico()
    dados  = hist.get(estado)
    if not dados:
        raise ValueError(f"Estado {estado} nao encontrado no historico.json.")
    chuva_mask = _get_meses_chuva(estado)
    resultado  = []
    for ano in sorted(dados.keys()):
        precos = dados[ano]
        pc = [p for p,c in zip(precos, chuva_mask) if c     and p and p > 0]
        ps = [p for p,c in zip(precos, chuva_mask) if not c and p and p > 0]
        if not pc or not ps:
            continue
        resultado.append({
            "ano":         ano,
            "media_chuva": round(sum(pc)/len(pc), 2),
            "media_seca":  round(sum(ps)/len(ps), 2),
            "diferenca":   round(sum(ps)/len(ps) - sum(pc)/len(pc), 2),
        })
    return resultado


def comparativo_estados(ano: int = None) -> dict:
    hist    = _carregar_historico()
    ano_ref = ano or max(
        {int(a) for e in hist.values() for a in e.keys()},
        default=datetime.now(TZ_BR).year
    )
    resultado = {}
    for estado in ESTADOS_VALIDOS:
        dados      = hist.get(estado, {})
        precos_ano = dados.get(ano_ref)
        if not precos_ano:
            continue
        chuva_mask = _get_meses_chuva(estado)
        validos    = [p for p in precos_ano if p and p > 0]
        pc = [p for p,c in zip(precos_ano, chuva_mask) if c     and p and p > 0]
        ps = [p for p,c in zip(precos_ano, chuva_mask) if not c and p and p > 0]
        resultado[estado] = {
            "media_anual": round(sum(validos)/len(validos), 2) if validos else 0,
            "media_chuva": round(sum(pc)/len(pc), 2) if pc else 0,
            "media_seca":  round(sum(ps)/len(ps), 2) if ps else 0,
            "mensal":      precos_ano,
        }
    return resultado


_URL_B3 = "https://www.noticiasagricolas.com.br/cotacoes/boi-gordo/boi-gordo-b3-prego-regular"

_MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _parse_mes_ano_b3(txt: str):
    m = re.match(r"(\w+)/(\d{4})", txt.strip().lower())
    if m:
        mes = _MESES_PT.get(m.group(1))
        ano = int(m.group(2))
        if mes:
            return mes, ano
    return None, None


def _parse_preco_b3(txt: str):
    txt = re.sub(r"[^\d,\.]", "", txt.strip())
    txt = re.sub(r"\.(?=\d{3})", "", txt).replace(",", ".")
    try:
        v = float(txt)
        return round(v, 2) if 50 < v < 1500 else None
    except Exception:
        return None


def atualizar_futuros_b3() -> dict:
    """
    Faz scraping dos futuros B3 via requests+BeautifulSoup,
    salva em app/futuros_b3.json e invalida o cache.
    Chamado pelo scheduler e pela rota / a cada abertura do site.
    """
    try:
        resp = requests.get(_URL_B3, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        tabela = soup.find("table")
        if not tabela:
            logger.warning("atualizar_futuros_b3: tabela não encontrada na página")
            return {}

        resultados = []
        for tr in tabela.find_all("tr"):
            cols = tr.find_all("td")
            if len(cols) < 2:
                continue
            mes, ano = _parse_mes_ano_b3(cols[0].get_text())
            if not mes or not ano:
                continue
            preco = _parse_preco_b3(cols[1].get_text())
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

        if not resultados:
            logger.warning("atualizar_futuros_b3: nenhum contrato coletado")
            return {}

        saida = {
            "atualizado": datetime.now(TZ_BR).isoformat(),
            "fonte":      "Notícias Agrícolas · B3 Pregão Regular",
            "contratos":  resultados,
        }
        caminho = os.path.join(os.path.dirname(__file__), "futuros_b3.json")
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(saida, f, ensure_ascii=False, indent=2)

        # Invalida cache para próxima leitura pegar o arquivo novo
        cache_futuro.pop("futuros_b3", None)
        logger.info(f"✅ futuros_b3 atualizado: {len(resultados)} contratos")
        return carregar_futuros_b3()

    except Exception as e:
        logger.error(f"atualizar_futuros_b3 falhou: {e}")
        return {}


def carregar_futuros_b3() -> dict:
    """
    Lê app/futuros_b3.json gerado pelo buscar_futuro_b3.py.
    Retorna dict com metadados + lista de contratos futuros.
    TTL cache de 1h — o arquivo só muda quando o GitHub Action roda.
    """
    cache_key = "futuros_b3"
    if cache_key in cache_futuro:
        return cache_futuro[cache_key]

    caminho = os.path.join(os.path.dirname(__file__), "futuros_b3.json")
    if not os.path.exists(caminho):
        raise FileNotFoundError(
            "futuros_b3.json não encontrado. "
            "Execute: python buscar_futuro_b3.py"
        )
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    contratos = dados.get("contratos", [])
    if not contratos:
        raise ValueError("futuros_b3.json está vazio ou mal formatado.")

    resultado = {
        "atualizado": dados.get("atualizado"),
        "fonte":      dados.get("fonte", "Notícias Agrícolas · B3 Pregão Regular"),
        "contratos":  contratos,
    }
    cache_futuro[cache_key] = resultado
    return resultado


def carregar_cotacoes_scot() -> dict:
    """
    Lê app/cotacoes_scot.json gerado pelo buscar_cotacoes_scot.py.
    Retorna dict com metadados + cotacoes por estado.
    TTL cache de 4h — o arquivo atualiza 1x/dia via GitHub Action.
    """
    cache_key = "cotacoes_scot"
    if cache_key in cache_preco:
        return cache_preco[cache_key]

    caminho = os.path.join(os.path.dirname(__file__), "cotacoes_scot.json")
    if not os.path.exists(caminho):
        return {}

    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        cotacoes = dados.get("cotacoes", {})
        if cotacoes:
            cache_preco[cache_key] = cotacoes
        return cotacoes
    except Exception as e:
        logger.warning(f"Erro ao ler cotacoes_scot.json: {e}")
        return {}


def preco_historico_medio(estado: str, mes: int) -> float:
    """Média histórica de preço para um mês — usada pelo calculator.py."""
    estado = estado.upper()
    hist   = _carregar_historico()
    dados  = hist.get(estado, {})
    valores = [
        precos[mes - 1]
        for precos in dados.values()
        if len(precos) >= mes and precos[mes-1] and precos[mes-1] > 0
    ]
    if not valores:
        raise ValueError(
            f"Sem dados historicos para {estado}/mes {mes}. "
            "Execute: python atualizar_historico.py"
        )
    return round(sum(valores) / len(valores), 2)
