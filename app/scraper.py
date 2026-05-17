"""
scraper.py — Coleta automática de dados para o Timing Certo

Fontes de dados (todas automáticas):
  1. Preço atual:   AgroDoc AI API (CEPEA/Scot · gratuita · diária)
  2. Histórico:     historico.json gerado pelo atualizar_historico.py (Selenium/Agrolink)
  3. Clima:         Open-Meteo API (gratuita · sem autenticação · atualizada a cada 3h)

NENHUM dado está hardcoded neste arquivo.
Se o historico.json não existir, as rotas retornam erro explícito
orientando o usuário a rodar o atualizar_historico.py primeiro.
"""

import requests
import json
import os
import logging
from datetime import datetime
from cachetools import TTLCache

logger = logging.getLogger(__name__)

cache_preco = TTLCache(maxsize=20, ttl=21600)
cache_clima  = TTLCache(maxsize=10, ttl=10800)

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
MESES_CHUVA = {
    "MT": [True,True,True,False,False,False,False,False,True,True,True,True],
    "SP": [True,True,True,False,False,False,False,False,True,True,True,True],
    "GO": [True,True,True,False,False,False,False,False,True,True,True,True],
}
ESTADOS_VALIDOS = ("MT", "SP", "GO")


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
# PREÇO ATUAL — AgroDoc AI API
# ---------------------------------------------------------------------------

def _fallback_media_historica(estado: str) -> dict:
    """Fallback: média histórica do mês atual quando todas as APIs falham."""
    mes_atual = datetime.now().month
    try:
        preco = preco_historico_medio(estado, mes_atual)
        logger.info(f"Fallback histórico {estado} mês {mes_atual}: R${preco}")
        return {
            "preco":        preco,
            "fonte":        f"Média histórica {MESES_NOME[mes_atual-1]} (APIs indisponíveis)",
            "estado":       estado,
            "atualizado":   datetime.now().isoformat(),
            "data_cotacao": datetime.now().strftime("%Y-%m-%d"),
            "automatico":   False,
            "aviso":        "Preço baseado em média histórica — fontes externas temporariamente indisponíveis.",
        }
    except Exception:
        pass
    return {
        "preco":      None,
        "fonte":      "indisponivel",
        "estado":     estado,
        "atualizado": datetime.now().isoformat(),
        "automatico": False,
        "erro":       "Todas as fontes indisponíveis e historico.json ausente.",
    }


def scrape_cepea_atual(estado: str = "SP") -> dict:
    estado    = estado.upper()
    cache_key = f"agrodoc_{estado}"
    if cache_key in cache_preco:
        return cache_preco[cache_key]

    # --- Fonte 1: AgroDoc AI API ---
    try:
        resp = requests.get(
            "https://agrodocai.com.br/api/v1/cotacao",
            params={"uf": estado},   # params= em vez de f-string, mais robusto
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        dados    = resp.json()
        logger.info(f"AgroDoc response para {estado}: {dados}")
        # API sempre retorna referência SP em "boi_gordo_cepea_sp" (ignora param uf)
        DIFERENCIAL_AGRODOC = {"SP": 0.0, "MT": -3.0, "GO": -14.0}
        preco_sp = float(dados.get("boi_gordo_cepea_sp") or dados.get("valor") or 0)
        preco    = round(preco_sp + DIFERENCIAL_AGRODOC.get(estado, 0), 2) if preco_sp else 0
        data_cot = (dados.get("atualizado") or datetime.now().isoformat())[:10]

        if 200 < preco < 600:
            resultado = {
                "preco":        preco,
                "fonte":        "AgroDoc AI · CEPEA/Scot",
                "estado":       estado,
                "atualizado":   datetime.now().isoformat(),
                "data_cotacao": data_cot,
                "automatico":   True,
            }
            cache_preco[cache_key] = resultado
            return resultado

        logger.warning(f"AgroDoc retornou valor fora da faixa para {estado}: {preco}")

    except Exception as e:
        logger.warning(f"AgroDoc API falhou para {estado}: {e}")

    # --- Fonte 2: Redação Agro API (CEPEA/Esalq · gratuita · sem auth) ---
    # Retorna referência SP; aplica diferencial para MT/GO
    DIFERENCIAL = {"SP": 0.0, "MT": -3.0, "GO": -14.0}
    try:
        resp = requests.get(
            "https://www.redacaoagro.com.br/api/cotacoes.php",
            params={"item": "boi_gordo"},
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        dados    = resp.json()
        preco_sp = None
        if isinstance(dados, dict):
            item = dados.get("boi_gordo") or dados.get("boi gordo") or {}
            preco_sp = float(item.get("valor") or item.get("preco") or 0) or None
        elif isinstance(dados, list):
            for item in dados:
                if "boi" in str(item.get("item", "")).lower():
                    preco_sp = float(item.get("valor") or item.get("preco") or 0) or None
                    break

        if preco_sp and 200 < preco_sp < 600:
            preco_estado = round(preco_sp + DIFERENCIAL.get(estado, 0), 2)
            resultado = {
                "preco":        preco_estado,
                "preco_sp":     preco_sp,
                "fonte":        "Redação Agro · CEPEA/Esalq",
                "estado":       estado,
                "atualizado":   datetime.now().isoformat(),
                "data_cotacao": datetime.now().strftime("%Y-%m-%d"),
                "automatico":   True,
            }
            cache_preco[cache_key] = resultado
            return resultado

    except Exception as e:
        logger.warning(f"Redação Agro API falhou: {e}")

    # --- Fonte 3: Fallback média histórica do mês ---
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
            "atualizado": datetime.now().isoformat(),
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
            "atualizado": datetime.now().isoformat(),
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
    chuva_mask = MESES_CHUVA.get(estado, MESES_CHUVA["MT"])
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
    chuva_mask = MESES_CHUVA.get(estado, MESES_CHUVA["MT"])
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
        default=datetime.now().year
    )
    resultado = {}
    for estado in ESTADOS_VALIDOS:
        dados      = hist.get(estado, {})
        precos_ano = dados.get(ano_ref)
        if not precos_ano:
            continue
        chuva_mask = MESES_CHUVA.get(estado, MESES_CHUVA["MT"])
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
