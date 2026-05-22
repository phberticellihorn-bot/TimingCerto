"""
calculator.py — Motor de cálculo do Timing Certo
Recebe dados do produtor + dados de mercado e retorna recomendação estratégica
"""

from datetime import datetime, timedelta
from app.scraper import preco_historico_medio, _get_meses_chuva, MESES_NOME


def mes_nome(mes: int) -> str:
    return MESES_NOME[(mes - 1) % 12]


# preco_historico_medio importado do scraper.py


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
    custo_fixo_cab = float(payload.get("custo_fixo_cab", 0))
    mes_entrada  = int(payload.get("mes_entrada", 5))
    estado       = payload.get("estado", "MT").upper()

    # --- Ciclo principal ---
    dias = max(1, round((peso_abate - peso_atual) / gpd))
    meses_ciclo = dias / 30
    mes_abate = int((mes_entrada - 1 + round(meses_ciclo)) % 12) + 1
    arrobas = peso_abate / 15
    custo_total_cab = custo_dia * dias + custo_fixo_cab
    custo_lote = custo_total_cab * animais

    chuva_mask = _get_meses_chuva(estado)
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
    lucro_conf = (arrobas * p_conf * animais) - ((custo_conf * dias_conf + custo_fixo_cab) * animais)
    lucro_semi = (arrobas * p_semi * animais) - ((custo_semi * dias_semi + custo_fixo_cab) * animais)

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

    # --- Recomendação estratégica aprofundada ---
    b3_disponivel = False  # será sobreposto pelo frontend com preço B3 real

    # Ponto de equilíbrio: preço mínimo para cobrir custos
    preco_break_even = custo_lote / (arrobas * animais) if animais and arrobas else 0

    # Melhor mês do ciclo (excluindo meses de chuva se houver alternativa seca)
    meses_secos = [t for t in timeline if not t["chuva"]]
    melhor_geral = max(timeline, key=lambda x: x["preco"])
    melhor_seco  = max(meses_secos, key=lambda x: x["preco"]) if meses_secos else melhor_geral

    # Margem atual: vender hoje vs no abate planejado
    margem_planejada = lucro_lote / animais  # lucro por cabeça no plano atual
    receita_agora_total = (peso_atual / 15) * preco_atual * animais
    lucro_agora = receita_agora_total - custo_lote  # hipotético se vendesse hoje sem terminar

    # Diferença de preço entre abate planejado e melhor mês seco
    ganho_mudar_timing = (melhor_seco["preco"] - preco_abate) * arrobas * animais

    linhas = []

    # 1. Situação do ciclo
    situacao_chuva = "⚠️ período de chuvas" if tem_chuva else "✅ período seco"
    linhas.append(
        f"Ciclo de {dias} dias termina em {mes_nome(mes_abate)} ({situacao_chuva}, "
        f"preço hist. R$ {preco_abate:.0f}/arr). "
        f"Ponto de equilíbrio do lote: R$ {preco_break_even:.0f}/arr."
    )

    # 2. Análise do preço atual vs abate
    if preco_atual > preco_abate + 5:
        linhas.append(
            f"O preço de hoje (R$ {preco_atual:.0f}/arr) está R$ {preco_atual - preco_abate:.0f}/arr "
            f"acima da média histórica de {mes_nome(mes_abate)} — o mercado está favorável agora."
        )
    elif preco_atual < preco_abate - 5:
        linhas.append(
            f"O preço de hoje (R$ {preco_atual:.0f}/arr) está R$ {preco_abate - preco_atual:.0f}/arr "
            f"abaixo da média de {mes_nome(mes_abate)} — terminar o ciclo tende a ser vantajoso."
        )
    else:
        linhas.append(
            f"O preço de hoje (R$ {preco_atual:.0f}/arr) está próximo da média histórica "
            f"de {mes_nome(mes_abate)} (R$ {preco_abate:.0f}/arr) — sem vantagem clara em antecipar."
        )

    # 3. Recomendação de timing
    if tem_chuva and melhor_seco["mes"] != mes_nome(mes_abate):
        if ganho_mudar_timing > 3000:
            linhas.append(
                f"🔁 Melhor oportunidade do ciclo: {melhor_seco['mes']} "
                f"(R$ {melhor_seco['preco']:.0f}/arr, período seco). "
                f"Ajustar GPD ou peso de abate para antecipar/atrasar o abate pode gerar "
                f"R$ {ganho_mudar_timing/1000:.0f}k a mais no lote."
            )
        else:
            linhas.append(
                f"O mês de maior preço do ciclo é {melhor_seco['mes']} "
                f"(R$ {melhor_seco['preco']:.0f}/arr), mas o ganho de R$ {ganho_mudar_timing:.0f} "
                f"não justifica mudança de estratégia."
            )
    elif not tem_chuva:
        linhas.append(
            f"✅ Timing favorável — {mes_nome(mes_abate)} é período seco, "
            f"preços tendem a ser mais firmes. Mantenha o plano."
        )

    # 4. Estratégia de travamento B3
    preco_trava_sugerido = max(preco_abate, preco_break_even) + 15
    linhas.append(
        f"📌 Estratégia B3: monitore contratos de {mes_nome(mes_abate)}. "
        f"Se o futuro superar R$ {preco_trava_sugerido:.0f}/arr, considere travar parte do lote "
        f"para garantir margem acima do break-even."
    )

    # 5. Comparativo confinamento vs semiconfinamento
    if lucro_conf > lucro_semi + 5000:
        linhas.append(
            f"🏆 Confinamento é superior no cenário atual: "
            f"R$ {(lucro_conf - lucro_semi)/1000:.0f}k a mais no lote vs semiconfinamento, "
            f"pelo abate em {mes_nome(mes_conf)} vs {mes_nome(mes_semi)}."
        )
    elif lucro_semi > lucro_conf + 5000:
        linhas.append(
            f"🏆 Semiconfinamento é superior no cenário atual: "
            f"R$ {(lucro_semi - lucro_conf)/1000:.0f}k a mais no lote, "
            f"com abate em {mes_nome(mes_semi)} e menor custo diário."
        )
    else:
        linhas.append(
            f"Confinamento e semiconfinamento têm resultado similar no cenário atual "
            f"(diferença de R$ {abs(lucro_conf - lucro_semi)/1000:.1f}k). "
            f"Prefira semiconfinamento se o capital de giro for limitado."
        )

    # 6. Alerta de margem
    if margem_planejada < 0:
        linhas.append(
            f"🚨 Atenção: com os parâmetros informados, o lote projeta prejuízo de "
            f"R$ {abs(margem_planejada):.0f}/cabeça. Revise custo diário ou peso de abate."
        )
    elif margem_planejada < 200:
        linhas.append(
            f"⚠️ Margem apertada: R$ {margem_planejada:.0f}/cabeça. "
            f"Qualquer queda de preço pode comprometer o resultado — considere hedge na B3."
        )

    recomendacao = " ".join(linhas)

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
                "custo_lote": round((custo_conf * dias_conf + custo_fixo_cab) * animais),
                "lucro_lote": round(lucro_conf),
                "chuva": chuva_mask[mes_conf - 1],
            },
            "semiconfinamento": {
                "dias": dias_semi,
                "mes_abate": mes_nome(mes_semi),
                "preco": p_semi,
                "custo_lote": round((custo_semi * dias_semi + custo_fixo_cab) * animais),
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
