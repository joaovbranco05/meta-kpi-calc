# Meta KPI Calculator

Aplicação local para consolidar métricas de campanhas da Meta e calcular KPIs
de investimento, leads e matrículas da RCTEC, FECAF Florianópolis e Curso com
Bolsa.

Esta entrega contém as etapas 0 a 7: contrato do MVP, configuração,
infraestrutura SQLite/Alembic, endpoint de saúde, modelos de domínio, dados
fictícios, serviço interno de KPIs, cliente Meta mock-first e serviço interno de
sincronização com agendamento opcional, além da API REST local para conexão,
sincronização, campanhas, Insights, matrículas, dashboard, exportação e painel
Streamlit. Não há integração com BotConversa nesta entrega.

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
integrações comerciais permanecem fora do escopo atual.

## Cliente Meta mock-first

`meta_kpi_calc.services.meta_client.MetaClient` usa um `httpx.Client` injetado e
faz somente requisições `GET`. O token vai exclusivamente no header
`Authorization`; a origem é fixa em `https://graph.facebook.com`, redirects são
desativados por requisição e URLs de `paging.next` nunca são seguidas.

O cliente obtém a conta, lista campanhas e consulta Insights diários no nível da
conta. Campanhas ativas são filtradas localmente por
`effective_status == "ACTIVE"`. A paginação repete o endpoint confiável usando
somente o cursor `after`, detecta repetição e limita cada operação a 100 páginas.

Cada página aceita no máximo três tentativas totais. Somente falhas de
transporte/timeout, HTTP 429 e HTTP 500–599 são repetidas, com espera progressiva
de 1 e 2 segundos ou `Retry-After` inteiro não negativo. Respostas, erros e
informações de uso são validados e sanitizados sem expor token, URL, query,
cursor ou corpo externo. Todos os testes usam `httpx.MockTransport`; nenhuma
chamada real foi realizada.

A versão padrão permanece `v26.0` e configurável. A verificação online da versão
oficial atual não pôde ser concluída nesta execução porque a busca não retornou
resultado útil e a tentativa HTTP recebeu 429; portanto, este documento não
afirma que `v26.0` seja a versão atualmente suportada pela Meta.

Ao criar o `httpx.Client`, mantenha `follow_redirects=False`, embora o cliente
também imponha essa opção em cada requisição. Chamadas reais permanecem fora
desta entrega.

## Sincronização interna e agendamento

`meta_kpi_calc.services.sync_service.SyncService` sincroniza uma janela
inclusiva de até 31 datas. Ele recusa modo demo, credenciais ausentes, datas
futuras e execuções concorrentes no mesmo processo. O dia corrente é aceito e
marcado como parcial. Filtros de campanha e atividade são conjuntivos; uma
resposta vazia termina com sucesso sem consultar Insights.

Cada execução válida registra primeiro um `SyncRun` em `RUNNING`. Depois obtém
os dados mockados, persiste campanhas e Insights em uma única transação atômica
e finaliza o histórico em uma terceira transação. Falhas deixam o run como
`FAILED`, com mensagem fixa e sem token ou resposta externa. Upserts usam as
chaves naturais, reduzem duplicatas mantendo a última ocorrência e preservam
`Campaign.brand`, `Campaign.course` e `CampaignInsight.qualified_leads`.
Datas de campanha com offset explícito são normalizadas para UTC antes do
SQLite, evitando comparação de relógios locais como se fossem instantes.

O lock é local ao processo, não distribuído. O scheduler opcional registra um
único job intervalar `meta-sync`, com `coalesce=True` e `max_instances=1`. O
lifecycle da API inicia e encerra o scheduler somente quando ele está habilitado
e a configuração real está completa. Nesse modo, execute o Uvicorn com
exatamente um worker e sem `--reload`. O mesmo lifecycle fecha apenas o cliente
HTTP criado pela própria aplicação; um cliente injetado continua pertencendo ao
chamador. Nenhuma chamada real à Meta foi realizada; sincronização, scheduler e
lifecycle foram validados somente com mocks.

## API REST local

Além de `GET /health`, a etapa 6 expõe nove operações:

- `GET /api/meta/connection` e `POST /api/meta/sync`;
- `GET /api/campaigns`, `GET /api/campaigns/{campaign_id}` e
  `PATCH /api/campaigns/{campaign_id}/classification`;
- `GET /api/campaigns/{campaign_id}/insights`;
- `POST /api/enrollments`, `GET /api/enrollments` e
  `PUT /api/enrollments/{record_id}`.

As rotas usam a PK interna e também expõem `meta_campaign_id`. Listagens usam
`items`, `total`, `offset` e `limit`, com filtros conjuntivos e ordem estável.
Campos brutos da Meta nunca são retornados. Datas usam ISO e valores monetários
continuam `Decimal` nos schemas. Inteiros dos bodies e `active_only` são
estritos: strings, floats e booleanos usados como contagem são rejeitados sem
coerção. Erros possuem códigos e mensagens fixos, sem ecoar token, payload,
URL ou exceção externa.

Em demo ou sem credenciais completas, o diagnóstico de conexão retorna 200 sem
I/O externo. A verificação Meta ocorre somente por requisição explícita em modo
real configurado. Todos os testes da API usaram mocks; nenhuma conexão real foi
executada.

## Dashboard, exportação e painel

`GET /api/dashboard/summary` exige `date_start` e `date_stop` e aceita os filtros
conjuntivos opcionais `brand`, `campaign_id`, `course` e `effective_status`.
`course` representa a classificação da campanha, não o curso do registro de
matrícula. O endpoint devolve totais, KPIs e avisos já calculados pelo serviço
interno, inclusive métricas não calculáveis como `null`.

`GET /api/export` exige os mesmos filtros, além de `format=csv|xlsx` e
`dataset=performance|enrollments`. CSV contém apenas o dataset solicitado em
UTF-8-SIG; XLSX produz sempre as abas `Resumo`, `Diário`, `Matrículas` e
`Campanhas`. Textos iniciados por `=`, `+`, `-` ou `@` são neutralizados antes da
exportação e campos brutos da Meta não aparecem.

Com a API em execução, inicie o painel local:

```bash
streamlit run frontend/app.py
```

O painel usa exclusivamente `API_BASE_URL` (por padrão
`http://127.0.0.1:8000`), mostra um banner em demonstração e trata API vazia ou
indisponível sem exibir traceback. Não lê SQLite diretamente nem executa chamadas
Meta por conta própria.

As decisões congeladas, a matriz de aceite e o andamento ficam em `docs/`.
