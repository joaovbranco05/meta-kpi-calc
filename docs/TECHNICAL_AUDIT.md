# Auditoria técnica — Fase 0 do mini-CRM

Referência: 28/10/2026. Baseline `bdf7d8e`, branch `jota/mini_crm`, Python
3.14.6. Esta é uma inspeção do código e de testes locais, sem acessar bancos
operacionais ou serviços reais e sem inspecionar/exibir/alterar credenciais. O prompt atual muda a prioridade:
CRM primeiro, Analytics preservado; não libera implementação funcional.

## Diagnóstico verificável

O produto atual é um monólito local FastAPI + SQLAlchemy síncrono + SQLite,
com Streamlit consumidor REST, HTTPX e APScheduler opcional. Cinco entidades
persistentes existem: `Campaign`, `CampaignInsight`, `EnrollmentRecord`,
`CommercialClosure`, `SyncRun`. Não existem lead individual, pessoa, usuário,
autenticação, atendimento, webhook ou integração BotConversa. `leads` em
`CampaignInsight` é uma contagem agregada de actions; não é uma lista de pessoas.

Implementados e cobertos localmente: configuração demo/real isolada, migrations,
constraints, seed idempotente, fórmulas Decimal, filtros/paginação, lançamentos
diários, cobertura comercial, comparação, CSV/XLSX, erros sanitizados, retry e
sincronização. Integração Meta implementada apenas para conta, campanhas e
Insights: evidência de funcionamento vem de mocks, não de operação real.
Scheduler e concorrência têm testes locais, sem garantia distribuída.

Parciais: segurança cobre segredos e erros, mas não autentica nem autoriza;
qualificados podem ser persistidos/lidos, sem fluxo operacional de entrada;
logging remove tokens, mas não constitui política de tratamento de dados
pessoais. UI tem testes de helpers, estado e propagação de filtros, sem prova
de jornada completa com browser ou usabilidade com funcionária. Não há CI de
Python 3.12/PostgreSQL ou validação de implantação em nuvem nesta entrega.
Documentados mas não executados: refatoração 9D, matrícula individual etapa10,
piloto real e integração comercial de `PLAN-2.md`/`PRODUCT_REVIEW.md`.

## Inventário de reutilização

Caminhos `core/`, `db/`, `api/`, `services/` abaixo são relativos a
`src/meta_kpi_calc/`. A = direta; B = adaptar; C = preservar Analytics;
D = criar futuramente. Um componente compartilhável não ganha APIs CRM agora.

| Caminho/componente | Responsabilidade e dependências | Estado e testes existentes | Classe | Mudança futura / risco de regressão |
|---|---|---|---|---|
| `core/config.py`, `.env.example` | Pydantic Settings, SecretStr, paths, timezone | Validado; `test_config.py` | B | Aceitar PostgreSQL e settings Lead Ads segregadas; risco demo/real, URLs e segredos |
| `core/logging.py` | logging, redação recursiva/formatter | `test_logging.py`, `test_hardening.py` | B | Allowlist de eventos e proteção PII; redação de token não remove telefone/nome livre |
| `db/base.py` | Base ORM e naming conventions SQLAlchemy | Metadata exercitada por modelos/Alembic | A | Reusar Base e nomes; novos modelos devem registrar metadata explicitamente |
| `db/session.py` | Engine, sessões, PRAGMAs e diretório SQLite | `test_database.py`, duas escritas leves | B | Engine por dialeto; PRAGMA/check_same_thread são SQLite; risco concorrência/fechamento |
| `db/models.py:Campaign` | Identidade Meta única, classificação, relações | `test_domain_models.py` | B | Reusar FK opcional em Lead; não exigir campanha sincronizada; risco identidade/atribuição |
| `db/models.py:CampaignInsight` | Métricas diárias e JSON sanitizado | modelos, sync e KPIs | C | Manter; não converter contagem em lead individual; risco dupla contagem |
| `db/models.py:EnrollmentRecord` | Resumo campanha/data/curso, Numeric | modelos/API/KPIs | C | Preservar agregado legado; não reconstruir alunos nem contratos |
| `db/models.py:CommercialClosure` | PARTIAL/COMPLETE campanha/data | KPIs/API/Alembic | C | Preservar ausência como desconhecido; status CRM não altera fechamento |
| `db/models.py:SyncRun` | Execução de mídia, contagens e erro fixo | modelos/sync/scheduler | C | Não usar como inbox de lead; risco confundir reprocessamento e mídia |
| `alembic/`, `alembic.ini` | Autoridade única do schema, 0001→0004 | `test_alembic.py`, metadata/check | B | Migrations aditivas; adaptar PRAGMA por dialeto e testar restore/upgrade; sem alterar histórico |
| `api/app.py`, `api/dependencies.py` | Factory, lifespan, sessão, handlers | health/API/hardening | B | Incluir router CRM e identidade posteriormente; risco auth deixar endpoints antigos abertos |
| `api/routes/health.py` | Saúde local e banco | `test_health.py` | A | Preservar contrato; definir exposição mínima no deploy |
| `api/routes/rest.py`, `api/schemas.py` | 17 operações API, validação, ORM/export | `test_api_rest.py`, hardening | C | Preservar; 1000 linhas em rest.py; dividir só quando mudança justificar, sem refatoração extensa agora |
| `services/meta_client.py` | GET conta/campanhas/Insights; HTTPX, dataclasses | `test_meta_client.py`, MockTransport | C | Manter contrato Analytics; nenhum formulário/lead/webhook; transporte não é API pública compartilhada |
| `services/sync_service.py` | Upsert campanha/Insight, três transações, lock | `test_sync_service.py`, hardening | C | Não virar ingestão CRM; lock é só do processo e terminal SyncRun pode falhar com banco indisponível |
| `services/scheduler.py` | APScheduler intervalar in-process | `test_scheduler.py` | C | Um worker sem reload; não é fila durável nem lock distribuído |
| `services/kpi_service.py` | Cálculo puro Decimal + agregação com Session | `test_kpi_service.py` | C | Fórmulas inalteradas; não juntar CRM aos agregados sem reconciliação/coorte |
| `services/report_service.py`, `report_filters.py` | Relatórios/escopo, mesmas regras de resumo | API e KPIs | C | Preservar períodos e não aditividade; comparação faz agregações por campanha, medir antes de otimizar |
| `services/demo_seed.py`, `fixtures/` | Demo determinística sem rede | `test_demo_seed.py` | C | Novo seed CRM separado e fictício no futuro; nunca tocar modo real |
| `frontend/app.py` | UI Streamlit, HTTPX, pandas, export/state | testes frontend em `test_api_rest.py` | C | 1094 linhas; preservar Analytics; frontend comercial próprio futuro, sem autenticação fictícia |
| `iniciar.sh`, `parar.sh`, `docs/OPERATIONS.md` | Operação local, API/painel/backup | smoke documentado; testes não provam deploy | B | Cloud exige identidade, HTTPS, backup ensaiado, processos e monitoramento |
| `requirements.txt`, `pyproject.toml` | setuptools src layout, Python >=3.12,<3.15, faixas de versões | Ambiente local executável | B | Sem lockfile reprodutível e sem driver PostgreSQL; fixação/CI e driver só quando necessários |
| `tests/`, `tests/conftest.py` | 14 arquivos de teste, fixtures DB migrado, bloqueio TCP | 215 casos parametrizados aprovados no baseline | A | Reusar isolação; subprocessos de migrations usam temporários, não operação real |
| `docs/`, `README.md`, skills locais | Planos, contratos, aceite e runbook | Conteúdo confrontado com código | B | Planos antigos históricos não liberam etapas; números 191/208 são históricos |
| `crm/__init__.py` | Reserva de fronteira apenas por docstring | Import/metadata/OpenAPI e suíte de regressão | D | Scaffold criado nesta fase; nenhuma funcionalidade |
| Futuro `crm/`: Lead/Activity | Submissão, comercial, histórico; SQLAlchemy/Session | Inexistente; testes fase 1 | D | UNIQUE+transação, replay, contato não único, status preservado; risco PII/perda de histórico |
| Futuro `crm/`: Lead Ads/inbox/router | Cliente específico, assinatura, processamento e reconciliação | Inexistente; mocks fase 2 | D | Durabilidade, crash, tokens e associação incompleta; ver plano integração |
| Futura identidade/UI comercial | Login, autorização servidor, sessões, consulta/edição | Inexistente; fase 3 | D | Proteger toda superfície privada, CSRF e acesso aos leads; sem novo framework agora |
| Futuro deploy/PostgreSQL/BI | Produção, backups, SQL e dashboards | Não implementado; fases4/5 | D | Não basta trocar URL; validar migração e exposição antes de produção |

## Superfície REST real

OpenAPI tem **18 operações: 17 `/api` + `/health`**. A contagem inclui métodos
separados para uma mesma URL; docs automáticas do framework não entram nela.

| Métodos | Caminho |
|---|---|
| GET | `/health` |
| GET | `/api/meta/connection`, `/api/meta/sync/status` |
| POST | `/api/meta/sync` |
| GET | `/api/campaigns`, `/api/campaigns/{campaign_id}`, `/api/campaigns/{campaign_id}/insights` |
| PATCH | `/api/campaigns/{campaign_id}/classification` |
| GET, POST | `/api/enrollments` |
| PUT | `/api/enrollments/{record_id}`, `/api/commercial-closures/{campaign_id}/{reference_date}` |
| GET | `/api/dashboard/default-period`, `/api/dashboard/summary`, `/api/dashboard/campaign-comparison` |
| GET | `/api/dashboard/campaign-comparison/detail`, `/api/dashboard/campaign-comparison/export`, `/api/export` |

GET conexão pode consultar Meta em modo real configurado; GETs de painel usam
persistência local. POST sync lê Meta e grava localmente. PATCH/POST/PUT
comerciais escrevem SQLite. A proteção atual é o uso local, não autenticação.
Erros têm envelopes fixos e validação estrita; raw Meta não é exposto na API.

## Riscos e limites

Prioridade antes de acesso remoto: identidade/autorização em servidor,
segredos fora de fonte/logs, HTTPS e backup testado. Antes de ingestão: dados
mínimos, idempotência concorrente e inbox durável. Antes de PostgreSQL: remover
dependências SQLite nas fronteiras, ensaiar cópia/restore e reconciliar PK/FK,
Decimal, datas e JSON. `DateTime(timezone=True)` não garante que SQLite devolva
o offset; migração precisa definir UTC e rejeitar interpretação ambígua.
Nenhuma dessas lacunas foi corrigida funcionalmente nesta fase.

Faixas de dependências não fixam ambiente; Python3.12 não foi validado.
Retry HTTP e mensagens sanitizadas não resolvem expiração de token, permissão
revogada, replay de webhook ou retenção de PII. A versão configurada `v26.0`
não foi confirmada como suportada atualmente pela Meta.

| Risco | Evidência | Prioridade e tratamento futuro |
|---|---|---|
| R1 acesso privado sem identidade | `api/routes/rest.py:61`, `api/app.py:100` | Alto caso exposto remotamente; uso localhost é escopo atual; fase 3 protege API inteira |
| R2 PostgreSQL bloqueado | `core/config.py:70`, `db/session.py:19`, `alembic/env.py:39` | Bloqueador de migração, não defeito SQLite; fase 4 adapta fronteiras |
| R3 durabilidade e concorrência | `sync_service.py:18`, `:199`, `:253`, `:313` | Lock local e três transações: dados podem persistir antes de falha terminal; não reutilizar como inbox |
| R4 logging não remove PII | `core/logging.py:12` | Alto antes de ingestão real; eventos Lead Ads por allowlist, sem raw/contato |
| R5 espera HTTP e readiness | `meta_client.py:274`, `:434`; `api/routes/health.py:30` | Retry-After sem teto pode bloquear worker; health só SELECT1; definir orçamento e readiness de deploy |

## Alterações limitadas e rastreabilidade

Criados quatro documentos CRM/auditoria e pacote CRM somente com docstring;
atualizada arquitetura e, após gates, índices de README/STATUS/DECISIONS/ACCEPTANCE.
Nenhum arquivo existente foi movido. Rotas, models, migrations, dependências,
KPIs e credenciais permanecem sem alterações.

Descoberta Git: `.gitignore` ignorava `docs` inteiro. Removida somente essa regra
para permitir versionar os entregáveis. Os documentos históricos preexistentes
agora aparecem como não rastreados; isso não significa que foram criados nesta
execução. Históricos: `ACCEPTANCE.md`, `ARCHITECTURE.md`, `DECISIONS.md`,
`OPERATIONS.md`, `PLAN.md`, `PLAN-2.md`, `PRODUCT_REVIEW.md`, `STATUS.md`.
Criados agora: `TECHNICAL_AUDIT.md`, `CRM_ROADMAP.md`, `CRM_DATA_MODEL.md`,
`META_LEAD_ADS_INTEGRATION.md`. Não houve `git add`, commit, push ou merge.

## Evidência de validação

Baseline coordenador: `.venv/bin/python -m pytest -q` → **215 passed, 2 warnings**
em 45,26s. Avisos preexistentes Starlette/FastAPI/AnyIO, sem falha do projeto.
QA independente: import da aplicação não criou arquivo SQLite; Alembic em
banco temporário fez upgrade head, check, downgrade base, reupgrade e check;
head `0004_commercial_closures`, cinco tabelas de domínio. TestClient demo
com TCP bloqueado: health/conexão/campanhas 200, Meta client e scheduler ausentes.

QA também compilou DDL PostgreSQL de cinco tabelas e três índices ORM sem erro,
sem driver/engine/rede: apenas compatibilidade sintática parcial.
`.venv/bin/python -m pip check` → No broken requirements found. O pacote próprio
não está instalado nesse venv; instalação isolada via pip não foi validada.
`pyproject.toml` não declara runtime dependencies; o fluxo usa requirements.txt.
`/health` testa SELECT1, não o schema Alembic.

Após o scaffold: `.venv/bin/python -m pytest -q` → **215 passed, 2 warnings**
em 44,63s; `.venv/bin/python -m compileall -q frontend src tests` e
`git diff --check` concluídos sem erros. QA pós confirmou AST CRM somente
docstring, import da aplicação sem criar DB e Alembic head/check temporário.
OpenAPI completo idêntico ao baseline (SHA256
`88b68c3270e6a49e72f18964c34c4e758b59f8b140fc00ab23b7ddb30aa3e07f`).
QA independente pós: 215 passed, 2 warnings em 44,29s, TCP bloqueado,
Settings.env_file desabilitado e variáveis token/conta removidas. Uma execução
intermediária do harness QA teve 213 passed / 2 failed porque token vazio foi
injetado como SecretStr('') em vez de ausência; corrigido no harness, sem
alterar produto. Não foi falha do runtime nem regressão introduzida.
Gates base QA e arquiteto aprovados; índices atualizados após ambos.
Não houve Meta real, PostgreSQL real, UI E2E, deploy, leitura de dados pessoais
ou teste de recuperação de backup operacional. Testes locais não provam esses
comportamentos em produção.
