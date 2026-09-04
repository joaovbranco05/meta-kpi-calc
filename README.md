# Meta KPI Calculator

Aplicação local para consolidar métricas de campanhas da Meta e, nas próximas
etapas, calcular KPIs e registrar matrículas da RCTEC, FECAF Florianópolis e
Curso com Bolsa.

Esta entrega contém as etapas 0, 1 e 2: contrato do MVP, configuração,
infraestrutura SQLite/Alembic, endpoint de saúde, modelos de domínio e dados
fictícios para demonstração. Ainda não há sincronização Meta, cálculo de KPIs
ou painel funcional.

## Requisitos

- Python 3.12, 3.13 ou 3.14
- Execução local em `127.0.0.1`

## Instalação

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
```

Não envie nem versione o `.env`. Insira um token da Meta somente quando a etapa
de integração real for iniciada; o endpoint atual funciona sem credenciais.

## Execução

```bash
uvicorn meta_kpi_calc.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

Verifique `http://127.0.0.1:8000/health` ou a documentação em
`http://127.0.0.1:8000/docs`.

## Testes

```bash
pytest
```

## Dados de demonstração

O seed requer `DEMO_MODE=true`, não cria o schema e recusa execução no banco
real. Após aplicar as migrations, execute:

```bash
PYTHONPATH=src python -m meta_kpi_calc.services.demo_seed
```

O conjunto fixo possui três campanhas identificadas com `[DEMO]`, 21 registros
diários de desempenho e três registros de matrícula. O comando é idempotente:
reexecutá-lo atualiza as mesmas chaves naturais sem criar duplicatas.

As decisões congeladas, a matriz de aceite e o andamento ficam em `docs/`.
