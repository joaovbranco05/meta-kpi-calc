# Meta KPI Calculator

Aplicação local para consolidar métricas de campanhas da Meta e calcular KPIs
de investimento, leads e matrículas da RCTEC, FECAF Florianópolis e Curso com
Bolsa.

Esta entrega contém as etapas 0 a 3.1: contrato do MVP, configuração,
infraestrutura SQLite/Alembic, endpoint de saúde, modelos de domínio, dados
fictícios e serviço interno de KPIs. Ainda não há sincronização Meta, endpoints
de indicadores ou painel funcional.

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
diários de desempenho com leads qualificados conhecidos e três registros de
matrícula. O comando é idempotente: reexecutá-lo atualiza as mesmas chaves
naturais sem criar duplicatas.

## KPIs internos

O módulo `meta_kpi_calc.services.kpi_service` oferece cálculo puro e agregação
por período, campanha e marca. Métricas derivadas usam `Decimal`, seis casas e
`ROUND_HALF_UP`; divisões por zero retornam `None`. Alcance, frequência e
métricas informadas pela Meta só são preservados quando há uma única linha de
Insight. Divergências entre o curso da campanha e o da matrícula são retornadas
como avisos, sem alterar os dados comerciais.

A etapa 3.1 acrescenta `qualified_leads`, taxa de qualificação, CPQL, conversão
de contrato para pagante, taxa de cancelamento, matrículas líquidas, CAC líquido
e receitas esperada e recebida por matrícula pagante. As fórmulas são:

- taxa de qualificação = leads qualificados / leads × 100;
- CPQL = investimento / leads qualificados;
- conversão contrato → pagante = matrículas pagantes / contratadas × 100;
- taxa de cancelamento = cancelamentos / matrículas contratadas × 100;
- matrículas líquidas = matrículas contratadas − cancelamentos;
- CAC líquido = investimento / matrículas líquidas, somente quando o total
  líquido é positivo;
- receita por pagante = receita esperada ou recebida / matrículas pagantes.

`qualified_leads = NULL` significa medição desconhecida; zero significa uma
medição conhecida sem leads qualificados. Em uma agregação, basta uma linha
desconhecida para o total permanecer `None`, acompanhado de aviso, sem soma
parcial. Inconsistências entre qualificados e leads, cancelamentos e contratos,
ou pagantes e contratos são preservadas e sinalizadas com contexto por registro.

CAC contratual, CAC financeiro e CAC líquido são indicadores distintos. Receita
esperada, receita recebida e margem de contribuição também não são equivalentes.
O campo de margem ainda não tem unidade e granularidade formalmente definidas;
por isso, ROAS e ROI sobre margem não são calculados. LTV, coortes, payback e
integrações comerciais permanecem fora do escopo atual. A etapa 4 está pausada.

As decisões congeladas, a matriz de aceite e o andamento ficam em `docs/`.
