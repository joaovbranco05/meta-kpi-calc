# Plano de implementação do Meta KPI Calculator com 3 agentes

## Resumo

Construir o MVP no repositório `meta-kpi-calc/`, usando FastAPI, SQLite/SQLAlchemy, Streamlit e APScheduler. O sistema funcionará inicialmente em modo demonstração, sem credenciais, e ficará preparado para leitura da Meta Marketing API e futura expansão para leads/BotConversa.

A versão padrão será `v26.0`, atualmente indicada pelo [SDK oficial da Meta](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/apiconfig.py), mas permanecerá configurável.

BotConversa, Kanban e ingestão individual de leads ficam fora deste MVP.

## Colaboração dos três agentes

- **Pensador/arquiteto:** define o contrato e critérios de aceite de cada etapa, mantém `docs/DECISIONS.md` e impede desvios de escopo.
- **Programador:** único responsável por editar código, executar testes e entregar cada incremento.
- **QA/revisor:** revisa código, tenta quebrar o incremento, registra defeitos com severidade e passos de reprodução.

Fluxo obrigatório por etapa:

1. Pensador entrega contrato e invariantes.
2. Programador implementa um incremento pequeno.
3. Programador informa arquivos, interfaces, comandos e testes executados.
4. QA revisa e executa testes independentes.
5. Defeitos retornam ao programador.
6. QA executa regressão.
7. Pensador valida aderência e libera a próxima etapa.

Cada handoff deverá registrar: etapa, alterações, interfaces afetadas, testes e resultados, riscos pendentes e próximo gate. Os agentes não editarão os mesmos arquivos simultaneamente.

## Etapas de implementação

### 0. Raiz e contrato

- Adotar `meta-kpi-calc/` como raiz canônica, pois é o repositório com remote configurado.
- Declarar Python `>=3.12,<3.15`; executar localmente no Python 3.14 disponível.
- Fixar contratos REST, regras de agregação, modelo de dados e matriz de aceite.
- Criar documentação curta de decisões e andamento para preservar contexto entre etapas.

**Gate:** nenhuma decisão de interface ou regra de negócio pendente.

### 1. Scaffold, configuração e segurança

- Criar pacotes de backend, frontend, testes, fixtures e documentação.
- Configurar Pydantic Settings, logging sanitizado, FastAPI, SQLAlchemy e health check.
- Adicionar `.gitignore`, `.env.example`, `requirements.txt` e baseline do Alembic.
- Configurar SQLite com WAL, foreign keys e `busy_timeout`.
- Manter banco de demonstração fisicamente separado do banco real.
- Usar bind local `127.0.0.1`; não incluir autenticação própria neste MVP local.

Configurações adicionais:

- `DEMO_MODE=true`
- `DEMO_DATABASE_URL=sqlite:///./data/meta_kpi_demo.db`
- `SCHEDULER_ENABLED=false`
- `SYNC_LOOKBACK_DAYS=7`
- `MAX_SYNC_DAYS=31`
- `API_BASE_URL=http://127.0.0.1:8000`

**Gate:** API importa e `/health` responde sem token ou chamada externa.

### 2. Banco e modo demonstração

Implementar:

- `Campaign`, com `meta_campaign_id` único e marca enum: `RCTEC`, `FECAF`, `CURSO_COM_BOLSA`, `NAO_CLASSIFICADA`.
- `CampaignInsight`, com unicidade `(campaign_id, date_start, date_stop)`, valores financeiros `Numeric/Decimal` e JSON bruto.
- `EnrollmentRecord` como resumo diário, com unicidade `(campaign_id, reference_date, course)`.
- `SyncRun`, com estados `RUNNING`, `SUCCESS` e `FAILED`.

Regras:

- Curso da campanha pode ser nulo; não será inferido pelo nome.
- Curso da matrícula será obrigatório, livre, normalizado com `trim` e não vazio.
- Contagens e valores monetários não podem ser negativos.
- Não impor `cancelamentos <= contratadas`, pois os números podem representar coortes diferentes.
- Fixtures terão três campanhas, sete datas, cursos distintos, matrículas, receitas, zero leads e zero matrículas.
- Seed será idempotente e o painel exibirá banner permanente no modo demonstração.

**Gate:** executar o seed duas vezes não cria duplicatas nem mistura dados reais e fictícios.

### 3. KPIs e agregações

- Calcular todos os KPIs definidos no prompt usando `Decimal`.
- Denominador zero produzirá `null`.
- Somar apenas investimento, impressões, cliques, leads, matrículas e receitas.
- Recalcular CTR, CPC e CPM dos totais, identificando-os como métricas calculadas.
- Preservar separadamente CTR, CPC e CPM informados pela Meta.
- `reach` e `frequency` só serão retornados quando o grupo possuir exatamente uma linha de Insight; em agregados maiores serão `null` com warning.
- Agregar Insights e matrículas em subconsultas separadas antes do join, evitando multiplicação cartesiana.
- Quando o curso da matrícula divergir da campanha, usar o curso da matrícula nos KPIs comerciais e emitir alerta de divergência.

**Gate:** testes de todas as fórmulas, precisão monetária, divergência de curso e divisão por zero.

### 4. Cliente Meta mock-first

Criar `MetaClient` HTTPX somente leitura para:

- Normalizar `123` e `act_123` para `act_123`.
- Testar conexão e obter conta, nome, moeda, timezone e status.
- Listar campanhas e filtrar `effective_status=ACTIVE`.
- Consultar Insights no nível da conta com `level=campaign`, `time_increment=1` e período explícito.
- Extrair leads somente dos tipos configurados em `META_LEAD_ACTION_TYPES`.
- Processar paginação pelo cursor `after`, sem reutilizar ou registrar `paging.next`.
- Detectar cursor repetido, página excessiva, host inesperado e resposta malformada.
- Aplicar timeout e até três tentativas somente para transporte, timeout, HTTP 429 e 5xx.
- Respeitar `Retry-After`; não repetir erros 4xx permanentes.
- Registrar informações sanitizadas de uso da API sem token ou query string.

**Gate:** mocks comprovam paginação, retries limitados, uso exclusivo de GET e ausência do token em logs, erros e respostas.

### 5. Sincronização e agendamento

- Centralizar endpoint e scheduler em `SyncService.run_sync()`.
- Aceitar intervalo inclusivo de até 31 datas; períodos maiores retornam 422 sem truncamento.
- Bloquear datas futuras no timezone configurado.
- Aceitar a data atual, sinalizando que ela é parcial.
- Usar `active_only=true` por padrão e filtro opcional `meta_campaign_id`; filtros serão conjuntivos.
- Fazer upsert de campanhas e Insights.
- Criar `SyncRun` antes do processamento em transação separada.
- Persistir campanhas e Insights de forma atômica; uma falha intermediária faz rollback completo.
- Finalizar o `SyncRun` em transação separada, inclusive em falhas.
- Impedir sincronizações concorrentes no mesmo processo.
- Scheduler revisará sete datas, de `hoje-6` até `hoje`, com `max_instances=1` e coalescência.
- Scheduler ativo exigirá Uvicorn com um worker e sem `--reload`.

**Gate:** repetir a mesma janela atualiza valores sem aumentar linhas; falha na paginação não deixa dados parciais.

### 6. API REST

Implementar os endpoints solicitados, usando PK interna nas rotas e expondo sempre `meta_campaign_id`:

- `GET /health`
- `GET /api/meta/connection`
- `POST /api/meta/sync`
- `GET /api/campaigns`
- `GET /api/campaigns/{campaign_id}`
- `PATCH /api/campaigns/{campaign_id}/classification`
- `GET /api/campaigns/{campaign_id}/insights`
- `POST /api/enrollments`
- `GET /api/enrollments`
- `PUT /api/enrollments/{record_id}`
- `GET /api/dashboard/summary`
- `GET /api/export`

Contratos adicionais:

- Sincronização será síncrona e devolverá o `SyncRun`.
- Falha externa devolverá 502 com identificador da execução e mensagem sanitizada.
- Sync real sem credenciais devolverá 503.
- Lançamento duplicado de matrícula devolverá 409 indicando o uso de PUT.
- Listagens aceitarão paginação e filtros consistentes.
- `/api/meta/connection` será um diagnóstico seguro com `mode`, `configured` e `connected`.

**Gate:** testes contratuais para respostas 200, 404, 409, 422, 502 e 503.

### 7. Exportação e painel Streamlit

Exportação:

- `GET /api/export?format=csv|xlsx&dataset=performance|enrollments`.
- Reutilizar exatamente os filtros do dashboard.
- CSV em UTF-8-SIG.
- XLSX com abas `Resumo`, `Diário`, `Matrículas` e `Campanhas`.
- Neutralizar células iniciadas por `=`, `+`, `-` ou `@`.
- Definir MIME, nome e `Content-Disposition` corretos.

Streamlit:

- Consumir somente a API REST, nunca o SQLite diretamente.
- Criar seções de visão geral, campanhas, comparação, matrículas, sincronizações e configurações não sensíveis.
- Implementar filtros por período, marca, curso, campanha e status.
- Permitir classificação de campanha e cadastro/correção de matrículas.
- Exibir BRL, datas brasileiras, dados incompletos, divergências de curso e métricas não calculáveis.
- Tratar API indisponível e resultados vazios sem quebrar a interface.

**Gate:** teste ponta a ponta em demonstração e reabertura dos arquivos exportados com Pandas/OpenPyXL.

### 8. Hardening, documentação e conexão real

- Executar suíte completa sem acesso real à rede.
- Fazer varredura de segredos e teste com token-sentinela.
- Testar concorrência leve do SQLite e conflito entre sync manual e scheduler.
- Documentar instalação, migrações, API, painel, demo, scheduler e limitações.
- Documentar a conexão real somente após o modo demonstração estar aprovado.
- Nunca solicitar token pelo chat; o usuário o inserirá diretamente no `.env`.
- Registrar como evolução futura novas tabelas de leads, atribuição e BotConversa, conectadas pelos IDs externos já preservados.

**Gate final:** API e painel iniciam, demo funciona sem credenciais, todos os testes passam, não há segredos e a ressincronização permanece idempotente.

## Plano de testes

- **Unitários:** configurações, ID `act_`, datas, actions/leads, KPIs, Decimal, sanitização e CSV seguro.
- **Banco:** constraints, migrations, seeds, upserts, rollback, matrículas, isolamento demo/real e concorrência.
- **MetaClient:** paginação vazia/cíclica, timeout, 429, 5xx, 400 sem retry, JSON inválido e campos ausentes.
- **API:** endpoints, filtros, paginação, validações, códigos de erro e downloads.
- **Streamlit:** navegação, filtros, formulários, modo demo, API offline, pt-BR e warnings.
- **Segurança:** token ausente de logs, banco, traceback, respostas, exportações e documentação.
- **Compatibilidade:** Python 3.14 local e Python 3.12 em CI quando o ambiente estiver disponível.

## Assumptions e decisões fixadas

- O repositório aninhado `meta-kpi-calc/` será a única raiz de implementação.
- O modo demonstração será o padrão e usará banco separado.
- A matrícula será um resumo diário por campanha e curso.
- Divergências usarão o curso informado na matrícula, com alerta.
- Sincronizações manuais serão síncronas e limitadas a 31 dias.
- O scheduler revisará uma janela móvel de sete dias.
- Alcance e frequência não serão somados em agregações.
- Alembic será incluído desde o início para permitir evolução sem reconstrução do banco.
- BotConversa, contatos, Kanban, mensagens e ingestão individual de leads permanecerão fora do MVP.
