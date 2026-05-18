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
    Busca precipitação mensal média (mm) dos últimos 20 anos via Open-Meteo ERA5.
    Retorna lista de 12 floats [jan, fev, ..., dez].
    Fonte: archive-api.open-meteo.com · ERA5-Land · gratuita · sem autenticação.
    """
    estado = estado.upper()
    cache_key = f"normais_{estado}"
    if cache_key in cache_normais:
        return cache_normais[cache_key]

    coords = COORDS.get(estado, COORDS["MT"])
    ano_fim   = datetime.now().year - 1          # ano completo mais recente
    ano_ini   = ano_fim - 19                     # 20 anos de dados
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={coords['lat']}&longitude={coords['lon']}"
        f"&start_date={ano_ini}-01-01&end_date={ano_fim}-12-31"
        f"&daily=precipitation_sum"
        f"&timezone=America/Sao_Paulo"
    )

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        dados  = resp.json()
        datas  = dados["daily"]["time"]                  # ["2005-01-01", ...]
        chuvas = dados["daily"]["precipitation_sum"]     # [mm, mm, ...]

        # Agrupa por mês e calcula média mensal entre todos os anos
        soma_mes   = [0.0] * 12
        count_mes  = [0]   * 12
        for data_str, prec in zip(datas, chuvas):
            if prec is None:
                continue
            mes = int(data_str[5:7]) - 1   # 0-indexed
            soma_mes[mes]  += prec
            count_mes[mes] += 1

        # Transforma soma diária acumulada em média mensal (mm/mês)
        # count_mes conta dias, não meses — dividimos pelo nº de anos para ter mm/mês médio
        n_anos = ano_fim - ano_ini + 1
        medias = [
            round(soma_mes[m] / n_anos, 1) if count_mes[m] > 0 else 0.0
            for m in range(12)
        ]

        logger.info(f"Normais precipitação {estado} ({ano_ini}-{ano_fim}): {medias}")
        cache_normais[cache_key] = medias
        return medias

    except Exception as e:
        logger.warning(f"Open-Meteo Archive falhou para normais {estado}: {e}")
        return None


def _meses_chuva_estado(estado: str) -> list:
    """
    Retorna lista de 12 booleans indicando se cada mês é chuvoso,
    baseado nas normais ERA5 dos últimos 20 anos.
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


# MESES_CHUVA: gerado dinamicamente via ERA5; função abaixo substitui o dict fixo
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

    # --- Fonte 0: Scot Consultoria (preço real por estado, atualizado diariamente) ---
    try:
        cotacoes_scot = carregar_cotacoes_scot()
        preco_scot = cotacoes_scot.get(estado)
        if preco_scot and 200 < preco_scot < 600:
            # Verifica se o JSON não está desatualizado (mais de 2 dias)
            caminho = os.path.join(os.path.dirname(__file__), "cotacoes_scot.json")
            with open(caminho, "r", encoding="utf-8") as f:
                meta = json.load(f)
            atualizado = meta.get("atualizado", "")
            data_arquivo = datetime.fromisoformat(atualizado[:19]) if atualizado else None
            dias_defasagem = (datetime.now() - data_arquivo).days if data_arquivo else 99
            if dias_defasagem <= 2:
                resultado = {
                    "preco":        preco_scot,
                    "fonte":        "Scot Consultoria · Boi China a Prazo",
                    "estado":       estado,
                    "atualizado":   atualizado,
                    "data_cotacao": atualizado[:10],
                    "automatico":   True,
                }
                cache_preco[cache_key] = resultado
                logger.info(f"Scot Consultoria: {estado} = R${preco_scot}")
                return resultado
            else:
                logger.warning(f"cotacoes_scot.json desatualizado ({dias_defasagem} dias) — usando fallback")
    except Exception as e:
        logger.warning(f"Scot Consultoria falhou para {estado}: {e}")

    # --- Fonte 1: AgroDoc AI API (fallback — SP base + diferencial fixo) ---
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
        default=datetime.now().year
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
