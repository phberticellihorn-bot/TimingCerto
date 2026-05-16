"""
calculator.py — Motor de cálculo do Timing Certo
Recebe dados do produtor + dados de mercado e retorna recomendação estratégica
"""

from datetime import datetime, timedelta
from app.scraper import HISTORICO_PRECOS, MESES_CHUVA, MESES_NOME


def mes_nome(mes: int) -> str:
    return MESES_NOME[(mes - 1) % 12]


def preco_historico_medio(estado: str, mes: int) -> float:
    """Média histórica de 5 anos para um determinado mês."""
    estado = estado.upper()
    dados = HISTORICO_PRECOS.get(estado, HISTORICO_PRECOS["SP"])
    valores = [precos[mes - 1] for precos in dados.values()]
    return round(sum(valores) / len(valores), 2)


def calcular(payload: dict, preco_atual: float) -> dict:
    """
    Recebe:
      - modalidade: 'confinamento' | 'semi'
      - animais: int
      - peso_atual: float (kg)
      - peso_abate: float (kg)
      - gpd: float (kg/dia)
      - custo_dia: float (R$/cabeça/dia)
      - mes_entrada: int (1–12)
      - estado: str (SP | MT | GO)
    Retorna dict com análise completa.
    """
    modalidade   = payload.get("modalidade", "confinamento")
    animais      = int(payload.get("animais", 100))
    peso_atual   = float(payload.get("peso_atual", 420))
    peso_abate   = float(payload.get("peso_abate", 520))
    gpd          = float(payload.get("gpd", 1.4))
    custo_dia    = float(payload.get("custo_dia", 28))
    mes_entrada  = int(payload.get("mes_entrada", 5))
    estado       = payload.get("estado", "MT").upper()

    # --- Ciclo principal ---
    dias = max(1, round((peso_abate - peso_atual) / gpd))
    meses_ciclo = dias / 30
    mes_abate = int((mes_entrada - 1 + round(meses_ciclo)) % 12) + 1
    arrobas = peso_abate / 15
    custo_total_cab = custo_dia * dias
    custo_lote = custo_total_cab * animais

    chuva_mask = MESES_CHUVA.get(estado, MESES_CHUVA["MT"])
    tem_chuva = chuva_mask[mes_abate - 1]

    # Preço estimado no abate = média histórica do estado naquele mês
    preco_abate = preco_historico_medio(estado, mes_abate)
    receita_lote = arrobas * preco_abate * animais
    lucro_lote = receita_lote - custo_lote

    # --- Comparativo vender agora ---
    arrobas_agora = peso_atual / 15
    receita_agora = arrobas_agora * preco_atual * animais
    diff_arroba = preco_atual - preco_abate
    diff_total = diff_arroba * arrobas * animais

    # --- Comparativo confinamento vs semiconfinamento ---
    gpd_conf, custo_conf = 1.4, 28.0
    gpd_semi, custo_semi = 0.9, 11.0
    dias_conf = max(1, round((peso_abate - peso_atual) / gpd_conf))
    dias_semi = max(1, round((peso_abate - peso_atual) / gpd_semi))
    mes_conf = int((mes_entrada - 1 + round(dias_conf / 30)) % 12) + 1
    mes_semi = int((mes_entrada - 1 + round(dias_semi / 30)) % 12) + 1
    p_conf = preco_historico_medio(estado, mes_conf)
    p_semi = preco_historico_medio(estado, mes_semi)
    lucro_conf = (arrobas * p_conf - gpd_conf * dias_conf * 0 + custo_conf * dias_conf * -1) * animais
    lucro_conf = (arrobas * p_conf * animais) - (custo_conf * dias_conf * animais)
    lucro_semi = (arrobas * p_semi * animais) - (custo_semi * dias_semi * animais)

    # --- Timeline 6 meses ---
    timeline = []
    for i in range(7):
        m = (mes_entrada - 1 + i) % 12 + 1
        p = preco_historico_medio(estado, m)
        timeline.append({
            "mes": MESES_NOME[m - 1],
            "mes_num": m,
            "preco": p,
            "chuva": chuva_mask[m - 1],
            "is_abate": i == round(meses_ciclo),
        })

    melhor_mes = max(timeline, key=lambda x: x["preco"])

    # --- Recomendação ---
    if tem_chuva and diff_total > 5000:
        recomendacao = (
            f"⚠️ Ciclo termina em {mes_nome(mes_abate)}, época de chuvas com preço deprimido "
            f"(R$ {preco_abate:.0f}/arr vs R$ {preco_atual:.0f}/arr hoje). "
            f"Considere antecipar a venda ou travar preço no mercado futuro (B3). "
            f"Diferença estimada: R$ {abs(diff_total/1000):.0f}k no lote."
        )
    elif not tem_chuva:
        recomendacao = (
            f"✅ Ciclo termina em {mes_nome(mes_abate)}, período seco com preço favorável "
            f"(R$ {preco_abate:.0f}/arr). "
            f"Monitore a B3 e considere travar preço se ofertarem acima de "
            f"R$ {preco_abate + 10:.0f}/arroba. "
            f"Custo acumulado estimado: R$ {custo_lote/1000:.0f}k no lote."
        )
    else:
        recomendacao = (
            f"⚠️ Abate previsto em {mes_nome(mes_abate)} — período de chuvas. "
            f"O melhor preço do ciclo ocorre em {melhor_mes['mes']} (R$ {melhor_mes['preco']:.0f}/arr). "
            f"Avalie semiconfinamento para flexibilizar o timing de venda."
        )

    return {
        "ciclo": {
            "dias": dias,
            "meses": round(meses_ciclo, 1),
            "mes_abate": mes_nome(mes_abate),
            "mes_abate_num": mes_abate,
            "tem_chuva": tem_chuva,
        },
        "financeiro": {
            "arrobas_cab": round(arrobas, 1),
            "preco_abate": preco_abate,
            "preco_atual": preco_atual,
            "receita_lote": round(receita_lote),
            "custo_lote": round(custo_lote),
            "lucro_lote": round(lucro_lote),
            "diff_arroba": round(diff_arroba, 2),
            "diff_total": round(diff_total),
        },
        "comparativo": {
            "confinamento": {
                "dias": dias_conf,
                "mes_abate": mes_nome(mes_conf),
                "preco": p_conf,
                "custo_lote": round(custo_conf * dias_conf * animais),
                "lucro_lote": round(lucro_conf),
                "chuva": chuva_mask[mes_conf - 1],
            },
            "semiconfinamento": {
                "dias": dias_semi,
                "mes_abate": mes_nome(mes_semi),
                "preco": p_semi,
                "custo_lote": round(custo_semi * dias_semi * animais),
                "lucro_lote": round(lucro_semi),
                "chuva": chuva_mask[mes_semi - 1],
            },
        },
        "timeline": timeline,
        "melhor_mes": melhor_mes,
        "recomendacao": recomendacao,
        "estado": estado,
        "modalidade": modalidade,
        "animais": animais,
    }
