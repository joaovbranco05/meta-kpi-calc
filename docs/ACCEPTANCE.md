# Matriz de aceite — etapas 0 a 6

| Requisito | Evidência planejada | Estado inicial |
|---|---|---|
| Raiz e escopo documentados | `docs/DECISIONS.md` | Implementado |
| Python `>=3.12,<3.15` declarado | `pyproject.toml` | Implementado |
| App importa sem token/rede | `tests/test_health.py` | Aprovado pelo QA |
| Health demo e real responde 200 | `tests/test_health.py` | Aprovado pelo QA |
| Falha de banco responde 503 sanitizado | `tests/test_health.py` | Aprovado pelo QA |
| Settings e relações são validadas | `tests/test_config.py` | Aprovado pelo QA |
| Bancos demo e real são separados | `tests/test_config.py` | Aprovado pelo QA |
| Conta Meta aceita número ou `act_` e normaliza | `tests/test_config.py` | Aprovado pelo QA |
| SQLite ativa FK, WAL e timeout | `tests/test_database.py` | Aprovado pelo QA |
| Token-sentinela é redigido | `tests/test_logging.py` | Aprovado pelo QA |
| Alembic sobe e desce o baseline | comandos em `docs/STATUS.md` | Aprovado pelo QA |
| Nenhum modelo de negócio foi antecipado | revisão de árvore/diff | Aprovado pelo QA |

## Etapa 2

| Requisito | Evidência | Estado |
|---|---|---|
| Quatro entidades e enums persistentes | `tests/test_domain_models.py` | Aprovado pelo QA |
| Constraints, FKs, índices e chaves naturais | testes ORM/Core adversariais | Aprovado pelo QA |
| Precisão `Decimal` e JSON preservados | `test_insight_preserves_decimal_and_json` | Aprovado pelo QA |
| Curso recebe trim e rejeita vazio | testes ORM e constraint SQLite | Aprovado pelo QA |
| Cancelamentos podem exceder contratos | teste de persistência dedicado | Aprovado pelo QA |
| Timestamps têm defaults e ordem válida | testes de flush e constraint | Aprovado pelo QA |
| Migration 0002 sobe, desce e coincide com metadata | Alembic fresh + `alembic check` | Aprovado pelo QA |
| Seed possui 3 campanhas e 7 datas por campanha | `tests/test_demo_seed.py` | Aprovado pelo QA |
| Seed executado duas vezes não duplica chaves | teste idempotente e CLI | Aprovado pelo QA |
| Seed recusa banco real antes de criá-lo | teste de isolamento | Aprovado pelo QA |
| SOLID/KISS sem abstrações ou escopo futuro | revisão independente | Aprovado pelo QA |

## Etapa 3

| Requisito | Evidência | Estado |
|---|---|---|
| Onze fórmulas usam `Decimal` e o campo correto de clique | testes puros com valores conhecidos | Aprovado pelo QA |
| Divisor zero retorna `None` para todos os KPIs | teste parametrizado pelos totais zerados | Aprovado pelo QA |
| Resultado usa seis casas e `ROUND_HALF_UP` | casos de 1/3 e empate de arredondamento | Aprovado pelo QA |
| Uma linha preserva métricas Meta separadas | teste de Insight único | Aprovado pelo QA |
| Múltiplas linhas anulam não aditivos e avisam uma vez | teste de agregação aditiva | Aprovado pelo QA |
| Insights e matrículas não sofrem multiplicação cartesiana | cenário adversarial 2 × 2 | Aprovado pelo QA |
| Período inclusivo e filtros conjuntivos funcionam | testes de contenção, campanha e marca | Aprovado pelo QA |
| Divergências de curso são preservadas e auditáveis | teste contextual, deduplicado e ordenado | Aprovado pelo QA |
| Banco vazio retorna zeros tipados e KPIs nulos | teste sem linhas | Aprovado pelo QA |
| SOLID/KISS sem camadas ou escopo antecipado | revisão independente | Aprovado pelo QA e arquiteto |

## Etapa 3.1

| Requisito | Evidência | Estado |
|---|---|---|
| `qualified_leads` nullable, sem default e não negativo | testes ORM/Core e inspeção do schema | Aprovado pelo QA |
| Migration 0003 preserva existentes como `NULL` e é reversível | upgrade fresh, existing row, downgrade e `alembic check` | Aprovado pelo QA |
| Oito novos resultados seguem as fórmulas congeladas | testes puros normais e adversariais | Aprovado pelo QA |
| Desconhecido e zero possuem semânticas distintas | testes de `None`, zero, conjunto misto e vazio | Aprovado pelo QA |
| Líquido zero ou negativo não produz CAC enganoso | testes com cancelamentos iguais e superiores aos contratos | Aprovado pelo QA |
| Inconsistências são preservadas e avisadas por registro | testes com IDs, datas, curso e ordem determinística | Aprovado pelo QA |
| Dinheiro e razões usam `Decimal`, seis casas e `ROUND_HALF_UP` | testes de tipo, terços e arredondamento | Aprovado pelo QA |
| KPIs antigos, não aditivos, filtros e anti-cartesiano não regrediram | suíte completa da etapa 3 | Aprovado pelo QA |
| Seed possui qualificados conhecidos e continua idempotente | `tests/test_demo_seed.py` | Aprovado pelo QA |
| Margem não recebeu interpretação sem contrato de produto | inspeção de totais, KPIs e documentação | Aprovado pelo QA e arquiteto |
| SOLID/KISS sem camadas ou escopo futuro | revisão independente | Aprovado pelo QA e arquiteto |

## Etapa 4

| Requisito | Evidência | Estado |
|---|---|---|
| Cliente usa somente GET, origem fixa e token no header | inspeção de requests mockados | Aprovado pelo QA |
| Redirect externo não é seguido mesmo se habilitado no Client | regressão de HTTP 302 malicioso | Aprovado pelo QA |
| Conta, campanhas e Insights usam paths e parâmetros exatos | testes dos três métodos | Aprovado pelo QA |
| Campanhas ativas são filtradas localmente | teste `active_only` true/false | Aprovado pelo QA |
| Insights preservam Decimal/data e extraem actions configuradas | testes normais e adversariais | Aprovado pelo QA |
| Paginação usa somente `after` e limita 100 páginas | testes multi-page, loop, host e limite | Aprovado pelo QA |
| Retry possui três tentativas totais apenas para falhas transitórias | testes de transporte, timeout e status HTTP | Aprovado pelo QA |
| `Retry-After` inteiro é respeitado e demais valores usam fallback | testes de zero, positivo, negativo, decimal e texto | Aprovado pelo QA |
| JSON, shapes, campos, datas e números inválidos falham sanitizados | matriz adversarial totalmente mockada | Aprovado pelo QA |
| Token, URLs, cursores e corpos externos não vazam | testes de raw, erro, traceback e logs de uso | Aprovado pelo QA |
| Configuração inválida falha antes de I/O com erro público estável | testes de token, conta, versão e action types | Aprovado pelo QA |
| SOLID/KISS sem camadas ou integração antecipada | revisão independente | Aprovado pelo QA e arquiteto |

## Etapa 5

| Requisito | Evidência | Estado |
|---|---|---|
| Período inclusivo, máximo de 31 datas, futuro e timezone são validados antes de I/O | testes de 1/31/32 datas, hoje, ontem e clock | Aprovado pelo QA |
| Modo demo, credenciais e filtro inválido não criam SyncRun nem chamam Meta | testes de guardas pré-I/O | Aprovado pelo QA |
| Execução válida registra RUNNING antes da Meta e termina em transação separada | inspeção persistente de sucesso e falha | Aprovado pelo QA |
| Campanhas e Insights são gravados em uma única transação atômica | falha JSON no commit após lote preparado | Aprovado pelo QA |
| Filtros são conjuntivos e resposta vazia não consulta Insights | testes com activity/ID e lista vazia | Aprovado pelo QA |
| Upsert é idempotente, last-wins e conta chaves únicas | duas execuções e duplicatas na resposta | Aprovado pelo QA |
| Marca, curso e leads qualificados existentes são preservados | teste de atualização com classificação manual | Aprovado pelo QA |
| Métricas, Decimal, raw, datas e IDs são mapeados integralmente | asserções ORM do Insight sincronizado | Aprovado pelo QA |
| Datetimes com offset são normalizados para UTC antes do SQLite | regressões `08:00-03` e offsets distintos | Aprovado pelo QA |
| Falhas externas e de persistência geram estado FAILED sanitizado | testes adversariais de Meta e commit | Aprovado pelo QA |
| Lock é compartilhado, non-blocking e liberado após sucesso/falha | teste concorrente com duas instâncias | Aprovado pelo QA |
| Scheduler disabled retorna None; enabled registra um job sem iniciar | inspeção de timezone, intervalo, coalesce e max_instances | Aprovado pelo QA |
| Nenhuma migration, rede real, API, UI ou lifespan foi antecipado | Alembic check, mocks e revisão do diff | Aprovado pelo QA e arquiteto |
| SOLID/KISS sem camadas ou abstrações especulativas | revisão independente | Aprovado pelo QA e arquiteto |

## Etapa 6

| Requisito | Evidência | Estado |
|---|---|---|
| Health preservado e nove operações REST expostas | inspeção de rotas/OpenAPI e testes HTTP | Aprovado pelo QA |
| Connection não usa I/O em demo/incompleto e usa mock em real | transport sentinela e `MockTransport` | Aprovado pelo QA |
| Sync mapeia resultado e códigos 409/422/502/503 | testes parametrizados de `SyncServiceError` | Aprovado pelo QA |
| Campanhas usam PK local, meta ID, filtros, página e ordem estável | testes list/detail e filtros conjuntivos | Aprovado pelo QA |
| PATCH distingue omitido, null e blank e rejeita extra | matriz de bodies de classificação | Aprovado pelo QA |
| Insights filtram período e não expõem campos raw | teste de período, Decimal/null e sentinela raw | Aprovado pelo QA |
| Matrícula cria, lista e substitui todos os campos | testes POST/GET/PUT e estado persistido | Aprovado pelo QA |
| Conflito natural retorna 409 e faz rollback | colisões POST/PUT com conferência do banco | Aprovado pelo QA |
| Inteiros e active_only não sofrem coerção de body | regressões QA-6-01 e QA-6-02 | Aprovado pelo QA |
| Dinheiro vira Decimal e rejeita bool, não finito e negativo | testes diretos do schema e resposta HTTP | Aprovado pelo QA |
| Erros e validação não ecoam token, payload ou exceção | testes 422/500/502/503 com sentinela | Aprovado pelo QA |
| Sessões fecham em sucesso/falha e DB indisponível retorna 503 | testes de dependência e handler | Aprovado pelo QA |
| Lifecycle respeita ownership e controla scheduler uma vez | testes start/shutdown/close e modo default | Aprovado pelo QA |
| Sem migration, rede real, dashboard, export, UI ou BotConversa | Alembic check, mocks e revisão do diff | Aprovado pelo QA e arquiteto |
| SOLID/KISS sem repository/UoW/Protocol/camada CRUD | revisão independente | Aprovado pelo QA e arquiteto |

## Etapa 7

| Requisito | Evidência | Estado |
|---|---|---|
| Summary reutiliza os KPIs e retorna filtros, totais, KPIs e warnings | testes HTTP com seleção e resultado vazio | Aprovado pelo QA |
| Período, marca, campanha, curso e status são conjuntivos em summary/export | regressões de escopo e filtros inválidos | Aprovado pelo QA |
| `course` é o curso da campanha, sem rateio comercial | revisão do serviço e query de matrículas | Aprovado pelo QA e arquiteto |
| CSV é UTF-8-SIG, específico ao dataset e não expõe raw | teste de BOM, cabeçalho e download | Aprovado pelo QA |
| XLSX reabre com as abas Resumo, Diário, Matrículas e Campanhas | teste OpenPyXL | Aprovado pelo QA |
| Fórmulas textuais são neutralizadas nos arquivos | sentinela `=not-a-formula` em CSV/XLSX | Aprovado pelo QA |
| Streamlit usa REST/HTTPX, mostra demo e tolera API indisponível | revisão e teste import-safe | Aprovado pelo QA |
| QA-7-01: listagens respeitam escopo ativo | regressão de parâmetros e redução por campanhas | Aprovado pelo QA |
| Sem migration, rede real, Meta/BotConversa ou abstrações especulativas | Alembic, mocks e revisão do diff | Aprovado pelo QA e arquiteto |

## Etapa 8

| Requisito | Evidência | Estado |
|---|---|---|
| Suíte inteira não pode abrir conexão TCP, nem localhost | fixture autouse e teste adversarial com erro capturado | Aprovado pelo QA |
| Token-sentinela externo não alcança saída ou persistência | sync mockado, API, logs, banco e CSV | Aprovado pelo QA |
| SQLite aceita duas escritas leves concorrentes | duas Threads, Sessions e Barrier, repetidas pelo QA | Aprovado pelo QA |
| Sync manual bloqueia job no mesmo processo antes de I/O | SyncService real, Events, lock e inspeção de SyncRun | Aprovado pelo QA |
| Seed e ressincronização permanecem idempotentes | regressões existentes e suíte completa | Aprovado pelo QA |
| Demo inicia API e painel sem credenciais | smoke isolado com health, connection, campanhas, summary e export | Aprovado pelo QA |
| Arquivos sensíveis e dados locais permanecem ignorados | `git check-ignore` para `.env`, `.logs` e bancos | Aprovado pelo QA |
| Runbook cobre operação e conexão real sem executá-la | `docs/OPERATIONS.md` e revisão independente | Aprovado pelo QA e arquiteto |
| Sem produção, schema, CI, rede real ou escopo futuro | diff, Alembic e revisão SOLID/KISS | Aprovado pelo QA e arquiteto |

## Etapa 9A

| Requisito | Evidência | Estado |
|---|---|---|
| Migration `0004` cria `commercial_closures`, é reversível e coincide com metadata | upgrade/downgrade, `alembic check` e testes Alembic | Aprovado pelo QA |
| Fechamento por campanha/data é idempotente e aceita somente parcial ou completo | testes REST e persistência | Aprovado pelo QA |
| Cobertura diferencia ausência, parcial e completo | testes de serviço e API para `unknown`, `partial` e `complete` | Aprovado pelo QA |
| Candidatos de cobertura unem Insights, lançamentos e fechamentos | cenário com eventos em dias distintos e Insight multi-dia | Aprovado pelo QA |
| Datas de evento não são excluídas pela vigência da campanha | regressão REST de campanha encerrada | Aprovado pelo QA |
| Filtros acontecem antes da paginação e expõem total estável | regressão REST com registro além da primeira página | Aprovado pelo QA |
| Painel cria ou edita lançamento diário sem ID interno | testes de helpers da jornada, seleção legível e parâmetros HTTP | Aprovado pelo QA |
| Duplicidade abre edição e preserva notas e margem | regressão Streamlit/API de campanha/data/curso | Aprovado pelo QA |
| Zero confirmado e fechamento parcial permanecem distinguíveis | respostas de resumo e apresentação no painel | Aprovado pelo QA |
| Sem matrícula individual, pagamento, integração real ou alteração de fórmula de KPI | revisão de diff, mocks e suíte completa | Aprovado pelo QA e arquiteto |

## Etapa 9B

| Requisito | Evidência | Estado |
|---|---|---|
| Summary informa a última carga de mídia do recorte exato | regressão REST com Insight filtrado | Aprovado pelo QA |
| Comparison inclui campanhas sem Insight e preserva KPI não calculável/cobertura desconhecida | regressão REST com duas campanhas | Aprovado pelo QA |
| Comparison, summary e XLSX usam o mesmo filtro | regressão REST e leitura OpenPyXL da aba `Campanhas` | Aprovado pelo QA |
| Estado local cobre running, completed, failed e not_confirmed sem Meta | testes REST com `SyncRun` e banco vazio | Aprovado pelo QA |
| Período demo usa o menor/maior Insight persistido | regressão do endpoint e helper Streamlit | Aprovado pelo QA |
| Painel não consulta conexão Meta automaticamente | regressão do entrypoint Streamlit; health continua local | Aprovado pelo QA |
| Catálogo cobre todos os KPIs com unidade, fórmula e interpretação | revisão arquitetural e teste de apresentação | Aprovado pelo QA e arquiteto |
| Exportação não oferece arquivo de recorte anterior | regressão do cache por filtros | Aprovado pelo QA e arquiteto |
| Sem migration, matrícula individual, fórmula nova ou integração externa | revisão de diff, mocks e suíte completa | Aprovado pelo QA e arquiteto |

## Etapa 9C

| Requisito | Evidência | Estado |
|---|---|---|
| Aba permite selecionar duas ou mais campanhas e orienta seleção menor | multiselect e validação do endpoint detalhado | Aprovado pelo QA e arquiteto |
| Seleção percorre todas as páginas e mantém filtros globais | teste com 101 campanhas e parâmetros do painel | Aprovado pelo QA e arquiteto |
| Matriz exibe todos os totais e KPIs existentes na ordem selecionada | resposta detalhada, catálogo da matriz e teste REST | Aprovado pelo QA e arquiteto |
| Cada campanha expõe cobertura, última atualização, avisos e motivos de indisponibilidade | tabela de cobertura, avisos detalhados e testes de mídia ausente | Aprovado pelo QA e arquiteto |
| Zero comercial, dado de mídia ausente e margem não agregada permanecem distinguíveis | testes de apresentação e exportação | Aprovado pelo QA e arquiteto |
| Exportação reproduz seleção e recorte e inclui códigos/mensagens de avisos | endpoint XLSX e teste OpenPyXL | Aprovado pelo QA e arquiteto |
| Exportação antiga é removida ao alterar filtros ou reduzir seleção para menos de duas | regressão do cache da comparação | Aprovado pelo QA e arquiteto |
| Comparar e filtrar não consulta Meta implicitamente | revisão do Streamlit, health local e mocks | Aprovado pelo QA e arquiteto |
| Sem migration, nova fórmula, ranking, recomendação ou integração externa | revisão do diff e suíte completa | Aprovado pelo QA e arquiteto |
| Suíte completa e verificações estáticas permanecem aprovadas | `pytest -q` (215), `compileall` e `git diff --check` | Aprovado pelo QA e arquiteto |


## Fase 0 mini-CRM — auditoria e preparação (28/10/2026)

| Critério | Evidência | Resultado |
|---|---|---|
| Auditoria real e inventário A/B/C/D com caminhos/dependências/testes/risco | TECHNICAL_AUDIT; leitura código pelo QA/arquiteto | Aprovado |
| Arquitetura core/CRM/Analytics e roadmap fases 0–5, sem antecipação | ARCHITECTURE, CRM_ROADMAP | Gates QA e arquiteto aprovados |
| Modelo e PostgreSQL propostos sem migration/dado real | CRM_DATA_MODEL; DDL PostgreSQL compilado (não runtime) | Aprovado; validação real futura |
| Lead Ads distinguido de Insights, docs oficiais não presumidas | META_LEAD_ADS_INTEGRATION, limitação 429 | Aprovado; integração real futura |
| Scaffold docstring-only, zero modelos/rotas/deps novos | AST/import CRM; diff e inspeção metadata | Aprovado |
| Contratos existentes preservados | OpenAPI completo idêntico,18 operações | Aprovado |
| Suíte baseline e pós sem regressão | Baseline 215 pass; programador 215 pass em 44,63s; QA 215 pass em 44,29s; 2 warnings conhecidos | Aprovado |
| Import/startup demo e Alembic temporário | Sem criação DB no import; health/conexão/campanhas 200; upgrade/check/downgrade/reupgrade/check | Aprovado |
| Compilação e whitespace | compileall frontend/src/tests; git diff --check | Aprovado |
| Sem escopo externo ou funcional CRM | Nenhum deploy, Meta real, PostgreSQL, migração ou endpoint CRM | Aprovado por inspeção |

A execução intermediária do harness QA com token vazio causou duas falhas de
expectativa sobre defaults; corrigido o harness, sem mudança de produto. Não
é uma falha preexistente ou introduzida. Não foram feitos UI E2E, teste Meta
real, PostgreSQL runtime ou restauração operacional; são gates futuros.

Documentação histórica revelada pela remoção da regra `docs` do gitignore não
é tratada como criada nesta fase. Sem commit, push ou merge. O plano anterior
fica preservado, subordinado à nova prioridade. Próxima implementação somente
após contrato da fase 1, conforme CRM_ROADMAP.


## Gate 2A — Lead Ads técnico local (29/10/2026)

| Critério | Evidência local | Estado |
|---|---|---|
| Fase 1 preservada e verificada | Baseline 228, regressão import/API/ingestão/migrations | Aprovado localmente |
| GET-only, origem/timeouts/paginação/erros seguros | test_lead_ads, MockTransport, TCP bloqueado | Aprovado |
| Handshake/HMAC raw/stream limit/batch autorizado | Assinaturas válidas/adulteradas, oversize, batch inválido | Aprovado |
| Inbox commit antes ACK, replay/crash | Falha de commit e perda de ACK pós-commit com reenvio | Aprovado |
| Claim concorrente e fencing/recuperação | Dois workers/um vencedor, lease expirada, rollback, limite tentativas | Aprovado |
| HTTP fora de transação | Observação de begin/commit durante MockTransport | Aprovado |
| Normalização e replay sem perda comercial | UTC estrito/optional/custom, status e histórico preservados | Aprovado |
| Reconciliação/checkpoint sem truncar/lacuna | Overlap, falha página/cap, restart, lease, startgap rejeitado | Aprovado |
| Segredos/logs/demo/CLI seguros | Redação HTTPX e handler uvicorn real, demo 503, opt-in/caminho relativo | Aprovado |
| Alembic aditivo e regressão Analytics | Migration 0006 preserva 0005, check/downgrade/reupgrade, suíte integral | Aprovado |
| Suíte final | 283 passed, 2 warnings, 61,20s; compileall/diffcheck | Aprovado |
| Integração real 2B | Não executada; checklist no README/integração | Pendente de autorização e evidências reais |

Nenhum teste usa Meta real, segredo ou PII operacional. Não foram realizados
UI E2E, PostgreSQL, deploy, túnel, configuração de app/Página ou BotConversa.
Documentos locais estão ignorados por exclude do checkout; README registra o
essencial versionável. Sem commit/push/merge. Confirmações finais de revisão
são registradas no handoff, sem inferir prontidão operacional a partir de mocks.
