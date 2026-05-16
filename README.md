# Timing Certo — Consultoria Estratégica de Venda Pecuária

Sistema web automatizado para apoio à decisão de timing de venda de gado bovino.

## Funcionalidades

- **Preço atual automatizado** — scraping CEPEA/Esalq (atualiza a cada 6h)
- **Histórico 5 anos** — MT, SP e GO com comparativo chuva vs seca
- **Previsão climática** — Open-Meteo API (gratuita, sem autenticação)
- **Calculadora estratégica** — confinamento vs semiconfinamento com recomendação

## Stack

- **Backend:** Python 3.11 + Flask
- **Scraping:** BeautifulSoup4 + Requests
- **Agendamento:** APScheduler (atualiza CEPEA a cada 6h)
- **Clima:** Open-Meteo API (gratuita)
- **Frontend:** HTML/CSS/JS + Chart.js (sem framework)

## Rodar localmente

```bash
pip install -r requirements.txt
python main.py
# Acesse: http://localhost:5000
```

## Deploy no Render (gratuito)

1. Criar conta em https://render.com
2. New → Web Service → conectar repositório GitHub
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn main:app --bind 0.0.0.0:$PORT`
5. Deploy!

## Deploy no Railway (gratuito)

1. Criar conta em https://railway.app
2. New Project → Deploy from GitHub
3. Adicionar variável `PORT=5000`
4. Deploy automático via Procfile

## Fontes de dados

| Dado | Fonte | Atualização |
|---|---|---|
| Preço boi gordo atual | CEPEA/Esalq (scraping) | A cada 6h |
| Histórico 2020–2025 | CEPEA/Esalq (compilado) | Fixo |
| Previsão climática | Open-Meteo API | A cada 3h |
| Mercado futuro | B3 (fase 2) | — |

## Estrutura

```
timing_certo/
├── main.py              # Flask app + rotas
├── app/
│   ├── scraper.py       # CEPEA scraping + histórico + clima
│   └── calculator.py    # Motor de cálculo e recomendação
├── templates/
│   └── index.html       # Frontend completo
├── requirements.txt
└── Procfile             # Render/Railway
```
