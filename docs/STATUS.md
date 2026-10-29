# Status do projeto

## Prioridade vigente — Fase 2B.2, busca direta controlada (29/10/2026)

Implementado `fetch-lead` na CLI existente. O comando exige `--allow-network` e
um `--lead-id`; chama somente `GET /{lead-id}`, exige `form_id` mapeado a Página
allowlisted, normaliza os campos conhecidos e persiste por `ingest_lead()`. O
resumo não imprime PII, a transação preserva status comercial e replay idêntico
não cria atividade espúria. O fluxo não lista leads do formulário nem inicia
reconciliação, webhook ou worker.

### Tentativa real

- Autorização explícita recebida para a lead fictícia `1799753681047061`, com
  uso da credencial Lead Ads nova configurada localmente. Nenhum segredo foi
  impresso ou alterado.
- As duas primeiras tentativas receberam **HTTP 401 Unauthorized**. Após a
  atualização local do `.env`, foram feitas mais duas chamadas, sempre apenas
  `GET /v26.0/1799753681047061`; ambas receberam **HTTP 200 OK**. O token não foi
  impresso nem alterado pelo agente.
- Primeira resposta 200: `created`, `history_created=true`, `activity_type=IMPORTED`,
  `unmapped_fields=0`, delta de leads `+1`. Segunda resposta 200: `already_existed`,
  `history_created=false`, `activity_type=null`, delta `0`.
- Banco confirmado: `data/meta_kpi.db`, revisão Alembic `0006_lead_ads_inbox`.
  Após replay: integrity `ok`, 1 lead total, alvo presente, os cinco campos
  conhecidos preenchidos, associação com formulário/Página conferida, status
  comercial `NEW` e exatamente uma atividade `IMPORTED`. Assim, só o ID pedido
  foi importado; nenhum outro lead foi consultado ou persistido.
- Backups consistentes via SQLite Backup API foram verificados antes de cada
  execução: `data/meta_kpi.before-fetch-lead-20261029T134314.db`,
  `data/meta_kpi.before-fetch-lead-retry-20261029T134849.db`,
  `data/meta_kpi.before-fetch-lead-retry2-20261029T135040.db` e
  `data/meta_kpi.before-fetch-lead-replay-20261029T135101.db` (237568 bytes cada,
  revisão 0006, quick_check `ok`).
- Configuração não secreta da tentativa foi passada somente ao processo:
  `LEAD_ADS_ENABLED=true`, `LEAD_ADS_API_VERSION=v26.0`, allowlist da Página e
  mapping formulário→Página. O token não foi lido/imprimido no terminal.

### Validação automatizada

`.venv/bin/python -m pytest -q` — **294 testes aprovados, 2 avisos conhecidos**;
testes com mock cobrem criação, cinco campos, autorização do form/Página,
401/403, 404, resposta malformada, falha de commit com rollback e reimportação
idempotente preservando status comercial. TCP real bloqueado na suíte.
`git diff --check` passou. A execução real teve duas respostas 401 e, após a
atualização local da credencial, duas respostas 200 (criação e replay idempotente).

### Próximo passo

O teste direto foi concluído, incluindo replay idempotente. Próxima etapa, em
trabalho separado: preparar configuração `leadgen` com HTTPS temporário limitado
ao path do webhook, HMAC e worker/inbox explícito. Webhook, túnel,
reconciliação e deploy ainda não foram configurados nem executados; nunca expor
endpoints privados do CRM.

## Snapshot da entrega da Fase 2A (29/10/2026)

Estado: implementação técnica local concluída e validada com mocks/bancos
SQLite temporários. Gate 2B real NÃO EXECUTADO e sem autorização automática.
A prioridade CRM preserva Analytics; autenticação, UI comercial, PostgreSQL,
Supabase, túnel, deploy, BotConversa e mensagens seguem fora deste incremento.

### Gate prévio da Fase 1

Baseline no commit `d350b8a`, branch `jota/mini_crm`, árvore inicialmente limpa:
228 testes aprovados e dois avisos conhecidos. Código efetivo confirmou Lead,
LeadActivity, LeadSubmission, ingest_lead, importação separada e API local;
Alembic 0005 e idempotência/histórico foram verificados antes da 2A. Trechos
anteriores que diziam revisão Fase 1 pendente são registros históricos, não o
estado atual. O pacote crm já não é somente um scaffold desde a Fase 1.

### Implementação e validação 2A

- Novo MetaLeadAdsClient GET-only com HTTPX injetado, timeouts, limite de corpo,
  origem fixa e paginação reconstruída; cliente Analytics permanece intacto.
- GET/POST `/webhooks/meta/lead-ads`: handshake, HMAC-SHA256 raw-body, limite de
  stream, allowlist e validação batch antes de inbox. ACK somente após commit.
  Disabled/incompleto/demo retorna 503; nenhum bypass ou chamada Graph no router.
- Migration aditiva 0006 cria WebhookEvent/ReconciliationState e página nullable
  em Lead. Claims UPDATE atômico, leases/fencing e retry durável; nenhuma
  transação aberta durante HTTP. Worker é CLI explícita e limitada, sem autostart.
- Reconciliação manual de fontes autorizadas, paginação completa, filtro UTC
  local, overlap e checkpoint após sucesso integral. Início explícito que deixe
  lacuna depois do checkpoint é rejeitado. Falhas/replay/crash são recuperáveis.
- Normalizador usa ingest_lead; preserva comercial/notas/campos locais; unknown
  fields apenas contados. Corrigida igualdade UTC versus naive SQLite para
  evitar atividade de correção espúria em replay do mesmo timestamp.
- Segredos separados SecretStr, sem fallback Ads. Redação de URLs Graph/cursor,
  segredos e hub.verify_token em logger uvicorn.access com propagate=false.
  CLI canonicaliza URL SQLite para verificar o banco exato escolhido.
- Validação final programador: `.venv/bin/python -m pytest -q` → **283 passed,
  2 warnings em 61,20s**. `compileall frontend src tests` e `git diff --check`
  aprovados. Migrations upgrade/head/check/downgrade0005/reupgrade em temporário
  preservam Leads/atividades anteriores. Mocks, TCP bloqueado, sem rede real.
- Revisões identificaram replayUTC, query access log, isolamento demo, caminho
  relativo CLI e lacuna de checkpoint; correções têm regressões específicas.
  Uma execução intermediária falhou por harness Alembic in-process desabilitar
  loggers; teste movido para subprocess, sem defeito adicional de produto.

São nove entidades de domínio/técnicas e 25 operações OpenAPI: 18 Analytics/health,
cinco CRM e duas webhook. Resposta CRM acrescenta meta_page_id opcional; nenhum
path, método ou campo anterior foi removido. Fórmulas e módulos Analytics não
foram alterados. Não houve commit, push, merge ou alteração de credenciais.

### Limitações e próximo passo

A documentação developers.facebook.com retornou 429; fontes Meta-owned acessíveis
fundamentam contratos mínimos, mas versão/permissões/ciclo de token/retencão
atuais não foram confirmados. Nenhum lead real foi consultado; UI E2E,
PostgreSQL e implantação continuam não validados. SQLite single-host e logs de
proxy externo exigem controles adicionais antes de produção.

Próxima ação: autorização específica para Gate 2B, seguida do checklist em
META_LEAD_ADS_INTEGRATION e README: versão/app/permissões, Página/formulário de
teste, segredos no ambiente, HTTPS webhook-only e validação de lead fictício,
replay/reconciliação/segurança. Não executar isso implicitamente.

`docs/` foi incluído no controle de versão no commit `a9759b6`; esse commit
registra a conclusão da Fase 2A antes da tentativa real descrita acima.
As seções seguintes registram evolução histórica; seus textos de “próximo
passo” não substituem a prioridade vigente.

## Etapa 0 — raiz e contrato

Estado: concluída.

- Raiz, stack, contratos futuros, regras financeiras e limites de escopo foram
  registrados em `DECISIONS.md`.
- A matriz verificável está em `ACCEPTANCE.md`.

## Etapa 1 — scaffold, configuração e segurança

Estado: concluída e aprovada pelo QA.

- Scaffold `src/`, frontend, testes, fixtures, dados, Alembic e documentação.
- Settings validadas com bancos real/demo separados.
- SQLAlchemy com WAL, foreign keys e busy timeout.
- Logging com redação defensiva.
- FastAPI factory e `GET /health` sem dependência da Meta.

## Etapa 2 — banco e modo demonstração

Estado: concluída e aprovada pelo QA.

- Entidades `Campaign`, `CampaignInsight`, `EnrollmentRecord` e `SyncRun` com
  enums, relações e constraints nomeadas.
- Migration `0002_domain_models` explícita, reversível e alinhada à metadata.
- Seed demo transacional e idempotente com três campanhas, sete datas por
  campanha, matrículas, receitas e casos de denominador zero.
- O seed recusa modo real e não cria schema nem acessa serviços externos.
- Revisão SOLID/KISS aprovada: responsabilidades coesas, sem repository genérico,
  Unit of Work, interfaces especulativas ou antecipação das etapas futuras.

## Etapa 3 — KPIs e agregações

Estado: concluída e aprovada pelo QA e pelo arquiteto.

- Cálculo puro dos 11 KPIs com `Decimal`, seis casas e `ROUND_HALF_UP`.
- Divisões por zero retornam `None`; cliques das fórmulas são
  `inline_link_clicks`.
- Agregações independentes de Insights e matrículas impedem multiplicação
  cartesiana e aceitam período, campanha e marca.
- Métricas não aditivas da Meta são preservadas apenas para uma linha; múltiplas
  linhas produzem aviso explícito.
- Divergências de curso geram avisos contextuais, deduplicados e ordenados sem
  alterar matrículas ou receitas.
- Revisão SOLID/KISS aprovada: cálculo separado de I/O, sessão recebida na
  fronteira e nenhuma abstração ou funcionalidade futura antecipada.

## Etapa 3.1 — evolução comercial e financeira dos KPIs

Estado: concluída e aprovada pelo QA e pelo arquiteto.

- `CampaignInsight.qualified_leads` persiste uma medição opcional: `NULL`
  significa desconhecido e zero é um valor conhecido.
- A migration reversível `0003_qualified_leads` preserva linhas existentes como
  desconhecidas e rejeita somente valores negativos.
- O serviço calcula taxa de qualificação, CPQL, conversão contrato → pagante,
  taxa de cancelamento, matrículas líquidas, CAC líquido e receitas esperada e
  recebida por pagante.
- Matrículas líquidas negativas são preservadas; o CAC líquido só é calculado
  quando o denominador é positivo.
- Totais incompletos de leads qualificados não são somados parcialmente.
  Inconsistências de qualificados, cancelamentos e pagantes geram warnings
  determinísticos com contexto do registro, sem correção silenciosa.
- A margem de contribuição não foi agregada nem usada em KPIs porque sua unidade
  e granularidade ainda não constituem um contrato de produto.
- A etapa 4 foi inicialmente pausada e depois reativada explicitamente pelo
  usuário após a validação desta evolução.

## Etapa 4 — cliente Meta mock-first

Estado: concluída e aprovada pelo QA e pelo arquiteto.

- Cliente HTTPX síncrono, injetável e estritamente `GET`, sem chamadas reais.
- Conta, campanhas e Insights são mapeados para dataclasses imutáveis com
  validação estrita de strings, datas, inteiros e `Decimal`.
- Conta usa ID normalizado; campanhas ativas são filtradas localmente; Insights
  usam nível de campanha, período explícito e incremento diário.
- Paginação repete o endpoint fixo com `after`; `paging.next` é validado, mas
  nunca seguido. Cursor repetido, host inesperado e mais de 100 páginas falham.
- Cada página tem até três tentativas totais somente para transporte, timeout,
  HTTP 429 e 500–599. `Retry-After` inteiro não negativo é respeitado.
- Redirects são desativados por requisição, inclusive quando o cliente injetado
  foi configurado para segui-los.
- Erros, logs, headers de uso e respostas brutas são sanitizados, inclusive
  quando um segredo é ecoado em uma chave JSON.
- A versão padrão segue configurável como `v26.0`; a verificação oficial online
  não foi conclusiva nesta execução por busca vazia e resposta HTTP 429.

## Etapa 5 — sincronização e agendamento

Estado: concluída e aprovada pelo QA e pelo arquiteto.

- `SyncService` valida período inclusivo, timezone, modo, credenciais e filtro
  antes de banco, lock ou Meta; hoje é aceito e sinalizado como parcial.
- Um lock único por processo impede execuções simultâneas e é sempre liberado.
- `SyncRun` inicial, upsert de dados e estado terminal usam três transações
  explícitas; campanhas e Insights são persistidos atomicamente.
- Filtros de atividade e ID são conjuntivos. Respostas duplicadas são reduzidas
  por chave natural com a última ocorrência, mantendo contagens idempotentes.
- Upserts preservam marca, curso e leads qualificados; datetimes Meta exigem
  offset e são normalizados para UTC antes da persistência SQLite.
- Falhas registram estado `FAILED`, contagens zero e mensagem fixa sanitizada.
- O scheduler opcional registra um job intervalar `meta-sync` com janela de
  lookback, `coalesce=True` e `max_instances=1`, sem iniciar automaticamente.
- Toda a etapa foi validada com mocks; nenhuma rede ou chamada Meta real ocorreu.

## Etapa 6 — API REST local

Estado: concluída e aprovada pelo QA e pelo arquiteto.

- O contrato preserva `GET /health` e acrescenta nove operações para conexão,
  sincronização, campanhas, Insights e matrículas.
- Recursos ligados a campanha usam PK interna nas rotas e expõem também
  `meta_campaign_id`; listagens têm paginação, total, filtros conjuntivos e
  ordenação determinística.
- Classificação distingue campo omitido, curso nulo e curso vazio. Matrículas
  usam POST para criação e PUT para substituição, com conflito natural em 409.
- Bodies rejeitam coerção de inteiros e booleanos; dinheiro entra como `Decimal`
  finito e não negativo. Campos raw da Meta não são expostos.
- Erros 404, 409, 422, 502 e 503 usam envelopes e mensagens fixos sanitizados.
- O composition root cria Meta/Sync somente em modo real configurado. O
  lifecycle controla scheduler e fecha apenas o cliente HTTP que ele próprio
  criou; demo/default não cria cliente externo nem thread.
- Connection não faz I/O em demo/configuração incompleta. Testes de real usam
  `MockTransport`; nenhuma chamada Meta real foi feita.

## Etapa 7 — dashboard, exportação e painel local

Estado: concluída e aprovada pelo QA e pelo arquiteto.

- `GET /api/dashboard/summary` reutiliza o cálculo de KPIs existente; não cria
  fórmulas financeiras novas.
- Dashboard e exportação compartilham período inclusivo e filtros conjuntivos
  de marca, campanha, curso e status efetivo. `course` é sempre
  `Campaign.course`, sem ratear investimento pelo curso da matrícula.
- CSV é específico ao dataset solicitado, usa UTF-8-SIG e neutraliza textos que
  começam com `=`, `+`, `-` ou `@`. XLSX é um relatório integrado com as abas
  `Resumo`, `Diário`, `Matrículas` e `Campanhas`, independentemente do dataset
  obrigatório na URL.
- O Streamlit consome somente a API REST por HTTPX, mostra modo demonstração,
  filtros, visão geral, campanhas/classificação, matrículas e sincronização de
  forma tolerante a API indisponível e listas vazias.
- QA-7-01 confirmou que o painel propaga o escopo ativo às listagens; matrículas
  são restringidas pelos IDs das campanhas filtradas para preservar o significado
  de curso da campanha.
- Não houve migration, chamada Meta real, ação BotConversa ou nova integração
  externa.

## Etapa 8 — hardening e operação local

Estado: concluída e aprovada pelo QA e pelo arquiteto.

- A suíte bloqueia `socket.socket.connect`, inclusive para localhost, e falha
  no teardown mesmo quando o código testado captura a tentativa.
- Um cenário integrado com token-sentinela em resposta Meta mockada confirma
  ausência em respostas públicas, logs, persistência e exportação.
- Duas sessões em threads distintas concluem escritas leves no SQLite; o
  conflito entre sync manual e job parado retorna `sync_in_progress` sem novo
  I/O ou segundo `SyncRun`.
- O smoke demo aplicou migration e seed, iniciou API e painel sem credenciais e
  terminou sem listeners residuais. Health, conexão, campanhas, resumo e
  exportação responderam com sucesso.
- `docs/OPERATIONS.md` registra instalação, banco, backup, demo, API, painel,
  scheduler, diagnóstico, limitações e o runbook não executado de conexão real.
- Não houve alteração de produção ou schema, CI, chamada Meta/BotConversa real
  ou inclusão de segredo.

## Etapa 9A — lançamento diário seguro

Estado: concluída e aprovada pelo QA e pelo arquiteto.

- O registro agregado `EnrollmentRecord` permanece como lançamento diário; ele
  não representa ainda uma matrícula individual, contrato ou pagamento.
- A migration `0004_commercial_closures` cria `CommercialClosure`, com um estado
  explícito `PARTIAL` ou `COMPLETE` por campanha e data. Ausência de fechamento
  significa cobertura desconhecida, não zero comercial.
- O resumo expõe cobertura comercial `unknown`, `partial` ou `complete` e as
  unidades esperadas, desconhecidas, parciais e fechadas. A base de candidatos
  é a união de dias de Insight, lançamentos diários e fechamentos, respeitando
  o recorte.
- Filtros de relatórios e exportação usam a data dos eventos; `start_time` e
  `stop_time` da campanha não excluem Insights, lançamentos ou fechamentos.
- A API filtra antes de paginar. O painel percorre as páginas, informa o total e
  localiza duplicidade por campanha/data/curso antes de abrir a edição.
- A tela chama a ação de “Lançamento diário”, seleciona campanha por nome, marca
  e status, carrega o registro completo para edição e preserva observações e
  margem. Zero confirmado e fechamento parcial ficam visíveis.
- Não houve chamada Meta/BotConversa real, nova integração externa, matrícula
  individual, pagamento, rateio ou mudança nas fórmulas aprovadas de KPI.

## Etapa 9B — painel orientado à decisão

Estado: concluída e aprovada pelo QA e pelo arquiteto.

- O dashboard acrescenta última carga de mídia no recorte, comparação por
  campanha e período padrão baseado nos Insights persistidos. As fórmulas de
  KPI e o schema permanecem inalterados.
- A comparação, o resumo e a aba `Campanhas` do XLSX usam exatamente os mesmos
  filtros; campanhas sem Insight continuam visíveis com totais zero, KPI não
  calculável e cobertura não informada.
- O painel oferece períodos rápidos, intervalo personalizado e aplicação
  explícita dos filtros. Em demonstração, ele abre o intervalo disponível do
  seed e o identifica como dado fictício.
- Mídia, comercial e financeiro aparecem separados, com formato de moeda,
  percentual e múltiplo; o catálogo explica fórmula e interpretação sem alegar
  conversão de coorte. Avisos são separados em informação, pendência e
  inconsistência.
- A tela lê somente `GET /health`, endpoints de dashboard, listagens e estado
  local de sync ao renderizar. Diagnóstico Meta e sincronização continuam ações
  explícitas do operador.
- A exportação XLSX é preparada para o recorte ativo e descartada ao trocar os
  filtros. Não houve migration, matrícula individual, integração real ou
  mudança de fórmula.

## Etapa 9C — comparação detalhada de campanhas

Estado: concluída e aprovada pelo QA e pelo arquiteto.

- A aba `Comparar campanhas` permite selecionar duas ou mais campanhas pelo
  identificador interno mantido no estado da tela, preservando nomes e IDs da
  Meta para distinguir campanhas homônimas.
- A listagem percorre todas as páginas disponíveis e aplica o mesmo período,
  marca, curso e status efetivo do recorte global. A seleção da aba substitui
  apenas o filtro singular de campanha nessa consulta.
- `GET /api/dashboard/campaign-comparison/detail` devolve, na ordem escolhida,
  os totais e KPIs vigentes, avisos, cobertura comercial e última atualização
  de mídia de cada campanha. `GET /api/dashboard/campaign-comparison/export`
  exporta a mesma seleção e o mesmo recorte.
- A matriz explica dados ausentes, métricas não aditivas, qualificados
  incompletos, denominadores zero e margem de contribuição não agregada. A
  margem não é somada nem vira KPI.
- A tabela de cobertura mostra dias esperados, sem confirmação, parciais e
  fechados; pendências são detalhadas por campanha. A exportação inclui códigos
  e mensagens dos avisos.
- A exportação em memória é invalidada ao mudar filtros ou seleção, inclusive
  quando a seleção cai para menos de duas campanhas. Abrir, filtrar ou comparar
  continua sem consulta implícita à Meta.
- A etapa não cria migration, fórmula, ranking, recomendação de orçamento,
  matrícula individual ou integração externa.

## Resultado da etapa 9C

- `pytest -q`: 215 testes aprovados; 2 avisos conhecidos de depreciação em
  FastAPI/Starlette, sem falhas do projeto.
- `python -m compileall -q frontend src tests`: concluído com sucesso.
- `git diff --check`: concluído sem divergências de whitespace.

## Comandos de verificação

```bash
python --version
pytest
alembic upgrade head
alembic downgrade base
PYTHONPATH=src python -m meta_kpi_calc.services.demo_seed
```

## Resultado local

- Ambiente: Python 3.14.6 em `.venv`.
- `pytest -q`: 208 testes aprovados sob bloqueio de TCP; 2 avisos de depreciação
  originados em FastAPI/Starlette, sem falhas do projeto.
- `alembic upgrade head`, `alembic check`, downgrade de `0004` para `0003` e
  novo `upgrade head`: concluídos com sucesso em banco temporário.
- Seed executado duas vezes com as mesmas contagens: 3 campanhas, 21 insights e
  3 registros de matrícula.
- `python -m compileall`: concluído com sucesso.

## Gate final

Gate 9B aprovado: QA confirmou summary, comparison, XLSX, status local,
período padrão, filtros e ausência de diagnóstico Meta automático. O arquiteto
confirmou que a etapa preserva o resumo diário e não antecipa matrícula
individual ou integração externa.

Gate 9C aprovado: QA confirmou seleção 2+, paginação completa, matriz
reconciliável, cobertura, motivos de indisponibilidade, exportação vinculada à
seleção e invalidação de cache. O arquiteto confirmou que a comparação reutiliza
os KPIs existentes e não cria agregação de margem, I/O externo ou schema novo.
O próximo passo é preparar o piloto assistido usando 9A+9B como mínimo
funcional; a etapa 10 permanece posterior.

## Riscos pendentes

- A compatibilidade local será comprovada no Python 3.14.6; Python 3.12 deverá
  ser validado futuramente em CI.
- O lifecycle inicia o scheduler quando habilitado; por isso esse modo exige um
  worker Uvicorn e não deve usar `--reload`.
- O lock não protege processos ou máquinas diferentes. Quando o scheduler for
  ativado, o Uvicorn deverá usar um worker e não usar `--reload`.
- Nenhuma chamada Meta real foi testada ou executada.
- Se o SQLite estiver totalmente indisponível durante a transação terminal, o
  serviço não consegue garantir que o `SyncRun` seja finalizado; não há
  recuperador ou retry de banco nesta etapa.
- A versão Meta atual ainda deve ser confirmada em documentação oficial antes
  da primeira conexão real.
- A semântica de `contribution_margin` ainda precisa definir unidade e
  granularidade antes de permitir ROAS ou ROI sobre margem.
- O fechamento comercial ainda é informado manualmente por campanha e data. A
  reconciliação com a fonte comercial deve ocorrer no piloto antes de qualquer
  entrega ao cliente.
