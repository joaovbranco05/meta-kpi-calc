# Decisões de arquitetura

## Estado congelado nas etapas 0 a 6

- A raiz canônica é este repositório `meta-kpi-calc/`; o repositório externo não
  receberá arquivos do produto.
- O projeto suporta Python `>=3.12,<3.15`; o primeiro teste local usa Python
  3.14.6.
- FastAPI será a fonte de verdade e o Streamlit consumirá somente REST.
- SQLAlchemy 2 síncrono e SQLite serão usados com Alembic como única autoridade
  de schema. A API não executará `create_all` nem migrations no startup.
- O modo demonstração é padrão e usa arquivo diferente do banco real.
- A API local usa `127.0.0.1` e não terá autenticação própria no MVP.
- A versão Meta padrão é `v26.0`, sempre configurável. Integrações serão apenas
  de leitura.

## Contratos inicialmente definidos

- Rotas de campanha usarão PK interna inteira e sempre exporão
  `meta_campaign_id`.
- Sincronização será síncrona, inclusiva e limitada a 31 dias; o scheduler
  revisará sete datas e ficará desligado por padrão.
- Dinheiro usará `Decimal`/`Numeric`; divisões por zero retornarão `null`.
- `reach` e `frequency` não serão somados em agregações.
- Matrícula será resumo diário único por campanha e curso; o curso da matrícula
  prevalecerá nos KPIs comerciais quando divergir, acompanhado de alerta.
- IDs externos da Meta serão preservados para permitir futura relação com leads.

## Modelo persistente da etapa 2

- `Campaign`, `CampaignInsight`, `EnrollmentRecord` e `SyncRun` são entidades
  coesas; não há repository genérico, Unit of Work ou interfaces especulativas.
- As marcas e estados de sincronização usam enums não nativos com valores
  estáveis e constraints nomeadas no SQLite.
- Chaves naturais impedem duplicação de campanha, insight diário e resumo de
  matrícula. FKs de insights e matrículas usam `RESTRICT`, sem delete cascade.
- Valores financeiros usam `Numeric`/`Decimal`. Contagens, métricas e receitas
  possuem validações de não negatividade; cancelamentos podem exceder contratos.
- O curso da matrícula é obrigatório e recebe apenas `trim`; o curso da campanha
  permanece opcional.
- `CampaignInsight.synced_at` e `SyncRun.started_at` recebem
  `CURRENT_TIMESTAMP` no banco. Um término de sincronização não pode preceder
  seu início, sem antecipar uma máquina de estados.
- A migration explícita `0002_domain_models` é a autoridade do schema e está
  alinhada à metadata segundo `alembic check`.
- O seed demo é fixo, transacional e idempotente por chaves naturais. Ele não
  cria tabelas, não acessa rede e recusa execução quando `DEMO_MODE=false`.

## KPIs e agregações da etapa 3

- O cálculo puro recebe totais tipados e não acessa banco; a agregação recebe a
  `Session` diretamente, sem repository, Unit of Work ou interface genérica.
- Métricas derivadas usam apenas `Decimal`, são quantizadas em seis casas com
  `ROUND_HALF_UP` e retornam `None` quando o denominador é zero.
- CTR, CPC e CPM calculados usam `inline_link_clicks`. Os valores informados
  pela Meta permanecem separados e não são somados nem recalculados.
- Insights e matrículas são agregados em consultas independentes. Períodos são
  inclusivos, e filtros opcionais de campanha e marca são conjuntivos.
- `reach`, `frequency` e métricas Meta são expostos somente para uma linha de
  Insight; múltiplas linhas geram `NON_ADDITIVE_METRICS_OMITTED`.
- O curso não é dimensão de agregação nesta etapa, pois não há regra de rateio
  de investimento. Divergências exatas geram `COURSE_MISMATCH` contextual,
  deduplicado e ordenado, preservando os valores da matrícula.

## Evolução de KPIs da etapa 3.1

- `CampaignInsight.qualified_leads` é inteiro nullable, sem default. `NULL`
  representa ausência de medição e zero representa uma medição conhecida.
- Valores conhecidos são aditivos somente quando todas as linhas selecionadas
  possuem medição. Qualquer lacuna torna o total desconhecido e gera
  `QUALIFIED_LEADS_INCOMPLETE`; nenhuma soma parcial é apresentada.
- Taxa de qualificação usa qualificados / leads × 100 e CPQL usa investimento /
  qualificados. Denominador zero ou total desconhecido retorna `None`.
- Conversão contrato → pagante e taxa de cancelamento usam matrículas
  contratadas como denominador. Resultados acima de 100% são preservados.
- Matrículas líquidas são contratos menos cancelamentos, inclusive quando zero
  ou negativas. CAC líquido só existe quando esse total é positivo.
- Receitas esperada e recebida por pagante são calculadas separadamente e não
  recebem o nome de LTV.
- `QUALIFIED_LEADS_EXCEED_LEADS`, `CANCELLATIONS_EXCEED_CONTRACTED` e
  `PAYING_EXCEEDS_CONTRACTED` registram inconsistências por linha com IDs e
  datas. Os dados não são limitados, corrigidos ou rejeitados pelo serviço.
- CAC contratual, financeiro e líquido permanecem distintos. Receita esperada,
  recebida e margem de contribuição também permanecem conceitos separados.
- `contribution_margin` continua persistido sem nova interpretação. Como sua
  unidade e granularidade não foram formalizadas, margem agregada, ROAS sobre
  margem e ROI sobre margem não pertencem ao contrato atual.
- A etapa 4 foi pausada e posteriormente reativada por decisão explícita do
  usuário. LTV, LTV/CAC, payback, coortes, CRM, BotConversa, vendedor,
  automações e alterações na Meta não foram antecipados.

## Cliente Meta mock-first da etapa 4

- `MetaClient` recebe um `httpx.Client` concreto e uma função de espera; o
  chamador controla o ciclo de vida. Não há SDK, Protocol, adapter ou factory.
- A origem é fixa em `https://graph.facebook.com/{versão}` e toda chamada usa
  `GET`, `Authorization: Bearer` no header e `follow_redirects=False` explícito.
- Conta, campanhas e Insights possuem contratos imutáveis mínimos. A consulta
  de Insights é no nível da conta, com `level=campaign`, `time_increment=1` e
  período explícito; leads vêm apenas dos action types configurados.
- A paginação ignora `paging.next` como destino, valida seu scheme/host e repete
  o endpoint conhecido apenas com `after`. Cursores repetidos e continuação na
  página 100 são rejeitados antes de outra requisição.
- Há três tentativas totais por página apenas para transporte, timeout, 429 e
  500–599. Demais status são permanentes; `Retry-After` aceita somente inteiro
  decimal não negativo, com fallback de 1 e 2 segundos.
- JSON, shapes e tipos são validados antes do mapeamento. Valores financeiros
  usam `Decimal` sem quantização ou `float`; `qualified_leads` não é inferido.
- Uma única `MetaClientError` expõe mensagens e status sanitizados. Logs contêm
  somente operação, status, tentativa e headers de uso processados; raw e logs
  redigem segredos também quando aparecem como chaves de mappings.
- A versão padrão continua `v26.0` e configurável. A tentativa de confirmação
  oficial não foi conclusiva por busca vazia/HTTP 429, logo nenhuma alegação de
  suporte atual foi congelada.

## Sincronização e agendamento da etapa 5

- `SyncService` recebe Settings, session factory, `MetaClient` e clock concretos.
  Não foram criados repository, Unit of Work, Protocol, adapter ou factory.
- Períodos são inclusivos e possuem no máximo 31 datas, sem truncamento. O dia
  corrente é permitido e sinaliza resultado parcial; datas futuras são negadas
  segundo `APP_TIMEZONE`.
- Modo demo e credenciais ausentes falham antes de lock, banco e Meta. O modo
  demo continua abastecido exclusivamente pelo seed.
- Um lock de módulo, compartilhado entre instâncias no mesmo processo, cobre o
  histórico inicial, I/O, persistência e finalização. Ele não é distribuído.
- O histórico `RUNNING`, o lote de dados e o estado terminal usam três
  transações explícitas. O lote de campanhas e Insights faz rollback integral;
  falhas terminais usam texto fixo sanitizado e contagens zero.
- Campanhas são consultadas antes dos Insights; ausência de campanhas evita a
  segunda consulta. O filtro por ID é exato e conjuntivo com `active_only`.
- Campanhas e Insights usam suas chaves naturais em upsert. Duplicatas da mesma
  resposta mantêm a última ocorrência; marca, curso e leads qualificados nunca
  são substituídos por dados Meta.
- Datas ISO de campanha exigem offset e são convertidas a UTC antes do ORM. No
  SQLite, o relógio UTC naive preserva o instante para comparação entre offsets.
- O scheduler, quando habilitado, configura exatamente um job intervalar
  `meta-sync`, com janela inclusiva de lookback, `coalesce=True` e
  `max_instances=1`. Na etapa 5, ele ainda não era iniciado nem ligado ao
  lifespan.
- Scheduler ativo exige um único processo Uvicorn e ausência de `--reload`.
  Start/shutdown e ciclo de vida do `httpx.Client` pertencem à etapa 6.
- Todos os testes usam mocks. Não houve rede, chamada Meta real ou mudança de
  schema nesta etapa.

## API REST local da etapa 6

- O FastAPI é o composition root. `Database`, `MetaClient`, `SyncService` e
  scheduler ficam em `app.state`; uma dependência pequena abre e fecha uma
  `Session` concreta por request. Não há repository, Unit of Work, Protocol,
  factory genérica ou camada CRUD.
- Além de health, existem nove operações REST para diagnóstico/sync, campanhas,
  Insights e matrículas. Dashboard/summary e exportação foram deliberadamente
  excluídos desta etapa.
- Rotas usam PK inteira local; respostas ligadas a campanha incluem também
  `meta_campaign_id`. Listas retornam `items`, `total`, `offset` e `limit`, com
  limite máximo 100 e ordem estável.
- Schemas não expõem `raw_response`, `raw_actions` nem
  `raw_cost_per_action_type`. Datas/datetimes usam ISO e dinheiro permanece
  `Decimal` na fronteira Pydantic.
- Inteiros de matrícula e `active_only` são estritos nos bodies, sem coerção de
  bool, float ou string. Dinheiro aceita número ou string decimal, mas é
  convertido imediatamente para `Decimal` finito e não negativo.
- PATCH de classificação exige ao menos brand ou course. Brand não aceita null;
  course omitido preserva, null limpa e string recebe trim sem aceitar vazio.
- Matrícula duplicada por campanha/data/curso retorna 409. POST orienta usar
  PUT; PUT substitui todos os campos editáveis e mantém rollback no conflito.
- Erros públicos possuem envelope, código e mensagem fixos. Falha de conexão é
  502; indisponibilidade/configuração de sync é 503; erros de pedido são 422;
  IDs ausentes são 404. Nenhuma entrada ou exceção externa é ecoada.
- Em demo ou configuração incompleta, connection responde sem I/O. Somente uma
  requisição explícita em modo real configurado consulta a Meta.
- O lifecycle compõe cliente/serviço apenas em real configurado, inicia e
  encerra o scheduler habilitado uma vez e fecha somente o `httpx.Client` criado
  pela aplicação, inclusive se o shutdown falhar. Cliente injetado pertence ao
  chamador.
- Na etapa 6, nenhuma migration, chamada Meta real, autenticação, dashboard,
  exportação, Streamlit ou BotConversa foi adicionada.

## Dashboard, exportação e Streamlit da etapa 7

- `GET /api/dashboard/summary` delega a matemática ao `summarize_kpis`. Os
  únicos filtros novos do serviço são `course` e `effective_status`; eles se
  aplicam a Insights, matrículas e warnings, junto com período, marca e campanha.
- O filtro `course` significa `Campaign.course`. O curso informado no registro
  de matrícula continua um dado comercial próprio e não recebe rateio de gasto.
- CSV exige `format=csv` e escolhe `performance` ou `enrollments`; ele usa
  UTF-8-SIG, MIME e nome de download explícitos. XLSX ainda exige `dataset`, mas
  produz o relatório integrado nas abas `Resumo`, `Diário`, `Matrículas` e
  `Campanhas`, nessa ordem.
- Valores textuais em exportação que começam com `=`, `+`, `-` ou `@` recebem
  apóstrofo antes de chegar a CSV/XLSX. Campos raw da Meta nunca são exportados.
- O painel Streamlit usa apenas HTTPX e `API_BASE_URL`; não importa SQLite,
  serviços de domínio ou clientes Meta. A correção QA-7-01 limita matrículas ao
  conjunto de campanhas do escopo, sem reinterpretar `EnrollmentRecord.course`.
- Não foram incluídos migrations, rede real, BotConversa, histórico de sync,
  autenticação, gráficos, uploads ou abstrações genéricas.

## Hardening e operação da etapa 8

- O hardening não altera produção ou schema. A suíte possui uma única guarda
  autouse que bloqueia conexão TCP e registra tentativas, sem exceção para
  localhost; HTTP externo permanece coberto somente por mocks.
- Concorrência leve do SQLite é provada com sessões reais e campanhas distintas.
  Sync manual e scheduler compartilham o mesmo lock no processo, portanto o
  segundo fluxo falha antes de I/O e antes de criar outro histórico.
- A documentação operacional fica centralizada em `docs/OPERATIONS.md`. O
  runbook real mantém scheduler desligado até conexão explícita e repetição
  idempotente de uma janela curta.
- `v26.0` continua apenas configurável e não confirmada como versão oficial
  atual. Nenhuma conexão real foi feita; Python 3.12 em CI continua futuro.
- Leads, atribuição e BotConversa permanecem evoluções futuras ligadas pelos IDs
  externos existentes, sem implementação antecipada.

## Lançamento diário seguro da etapa 9A

- `EnrollmentRecord` continua sendo o fechamento agregado de um dia, por
  campanha e curso. A etapa não o reinterpreta como aluno, contrato, matrícula
  individual ou evento financeiro.
- `CommercialClosure` é a autoridade mínima para declarar a situação comercial
  de uma campanha em uma data: apenas `PARTIAL` ou `COMPLETE`. A inexistência
  de linha representa `unknown`; não há default que converta ausência em zero.
- A cobertura do resumo usa a união dos pares campanha/data existentes em
  Insights, lançamentos diários e fechamentos. Para cada par, ausência prevalece
  como `unknown`, depois `PARTIAL`, e somente todos os pares completos resultam
  em `complete`.
  O recorte mantém período e filtros conjuntivos já aprovados.
- `Campaign.start_time` e `stop_time` são metadados de vigência. Eles não
  filtram eventos comerciais, Insights ou fechamentos em resumo, exportação ou
  cobertura.
- A API aplica todos os filtros antes de `offset` e `limit`. O Streamlit faz a
  consulta paginada necessária para a jornada atual, sem ler SQLite nem usar ID
  interno como entrada do operador.
- A edição de lançamento é substitutiva pelo contrato PUT existente e carrega o
  registro persistido completo; `notes` e `contribution_margin` não podem ser
  apagados por campos omitidos na interface.
- A etapa não altera fórmulas de KPI, cria coortes, rateia investimento, importa
  dados comerciais, integra Meta/BotConversa ou executa qualquer operação real.

## Painel orientado à decisão da etapa 9B

- `GET /api/dashboard/campaign-comparison` reutiliza `summarize_kpis` para cada
  campanha do mesmo `ReportFilters` usado por summary e exportação. Campanhas
  sem Insight no período não são omitidas nem interpretadas como zero comercial.
- `last_media_sync_at` é o maior `CampaignInsight.synced_at` do recorte exato.
  `GET /api/dashboard/default-period` lê o menor e maior dia de Insight local.
  Ambos são leituras locais e não acionam Meta.
- `GET /api/meta/sync/status` lê o `SyncRun` local mais recente por
  `started_at` e expõe somente estado, datas e timestamps. Não expõe erro,
  contagens ou ID do run e não consulta a Meta.
- A aba `Campanhas` do XLSX contém a mesma comparação da tela. Cobertura é
  achatada em colunas para permitir abertura no Excel; CSV preserva seu contrato
  de dataset existente.
- O Streamlit aplica o recorte explicitamente e apresenta indicadores com
  unidade, fórmula e interpretação. Razões entre totais do período não são
  apresentadas como coortes. Arquivo XLSX preparado fica vinculado aos filtros
  usados e não pode ser baixado após mudança de recorte.
- O render automático usa apenas health, dashboard, listagens e estado local de
  sincronização. O diagnóstico Meta e a sincronização são operações explícitas.

## Limites do MVP atual

BotConversa, Kanban, contatos, mensagens, ingestão de leads, autenticação,
gráficos, uploads, matrícula individual e pagamentos não pertencem às etapas
0 a 9C. Nenhuma operação real externa foi executada.
Cliente, sincronização, scheduler, API, exportação e painel foram validados
localmente, com mocks quando aplicável.

## Comparação detalhada da etapa 9C

- A comparação detalhada é uma aba própria do Streamlit. Ela exige pelo menos
  duas campanhas e usa os IDs internos somente no estado e nas requisições;
  nomes e `meta_campaign_id` permanecem visíveis para desambiguar a seleção.
- A seleção usa os filtros globais de período, marca, curso e status efetivo,
  mas substitui o `campaign_id` singular apenas na aba de comparação. A API
  recebe `campaign_ids` repetidos e preserva a ordem solicitada.
- `GET /api/dashboard/campaign-comparison/detail` chama `summarize_kpis` uma
  vez por campanha e devolve os totais, KPIs, avisos, cobertura comercial e
  última atualização de mídia. `GET /api/dashboard/campaign-comparison/export`
  serializa a mesma seleção em uma planilha específica.
- A listagem do painel percorre todas as páginas antes de oferecer o seletor;
  não há limite funcional de 100 campanhas. Seleção e filtros fazem parte da
  chave do cache da exportação, que é descartado inclusive quando ficam menos
  de duas campanhas selecionadas.
- Valores de mídia sem Insight são apresentados como dado ausente. Zero
  comercial continua sendo um valor registrado e é interpretado junto da
  cobertura `unknown`, `partial` ou `complete`. Margem de contribuição aparece
  como não agregada neste recorte, sem soma ou novo KPI.
- A comparação não cria ranking, recomendação de orçamento, coorte ou chamada
  implícita à Meta. Fórmulas e catálogo de KPIs existentes permanecem a fonte
  de verdade.

## Contrato de saúde

`GET /health` não usa rede nem credenciais Meta. Em sucesso retorna HTTP 200 com
`status`, `service`, `mode`, `database` e `scheduler`. Falha de conexão SQLite
retorna HTTP 503 e apenas `database_unavailable`, sem caminho, URL ou segredo.


## Fase0 mini-CRM — prioridade vigente (28/10/2026)

- O pedido atual prioriza mini-CRM RCTEC em um único repositório. Planos 9D e
  etapa10 permanecem históricos; não são pré-requisitos automáticos do CRM.
- Core/config/logging/Base/sessões serão compartilhados. Analytics permanece
  nos caminhos atuais; CRM futuro entra em `crm/`, mesma aplicação e Alembic.
  Nesta fase só docstring: nenhum runtime, modelo ou contrato público alterado.
- Lead é submissão individual com identidade Meta única, contato sem unicidade
  e Campaign FK opcional; não representa pessoa única ou matrícula.
  Idempotência exige UNIQUE+transação e preserva status/notas do operador.
- Integração futura terá cliente Lead Ads específico e inbox durável retomável;
  MetaClient Analytics é preservado. Compartilhar transporte só por duplicação
  real. Permissões/versão e payload exigem documentação oficial atual.
- Recomenda-se interface comercial própria no mesmo projeto, templates
  servidor como candidato a avaliar na fase3. Não se adiciona framework agora.
  Identidade/autorização servidor protegerá toda superfície privada inclusive
  legado antes de exposição remota; login UI isolado é insuficiente.
- SQLite permanece; PostgreSQL/cloud só em fase futura com adaptação por dialeto,
  migrations aditivas, backup/restore e reconciliação. Sem migração nesta entrega.
- LGPD/minimização/retenção e controle de acesso são requisitos futuros, sem
  alegar conformidade certificada. Nenhum raw de lead/PII em logs futuros.
- Detalhes e fases em CRM_ROADMAP, CRM_DATA_MODEL e META_LEAD_ADS_INTEGRATION.
  Gates base QA e arquiteto aprovaram o pacote; Analytics e 18 operações
  OpenAPI preservados. Não houve serviço real, deploy ou alteração de KPI.


## Gate 2A local Lead Ads (29/10/2026)

- MetaLeadAdsClient específico mantém MetaClient Analytics intacto. Credenciais
  e versão separados; enabled=false por padrão e ingress proibido em demo.
- Router webhook valida raw HMAC e batch antes de commit/ACK, sem HTTP Graph.
  Metadata durável sem raw/PII, migration0006 aditiva e meta_page_id opcional.
- Uma tentativa HTTP por claim; retries limitados só no estado durável. Sessões
  curtas sem rede; lease token e fence protegem conclusão/ingestão atômicas.
- Reconciliação explicitamente autorizada por form/page: todas as páginas,
  janela UTC local/overlap, checkpoint final e lease por fonte. Start que crie
  lacuna de continuidade é rejeitado; replay antigo não regride checkpoint.
- Campos desconhecidos apenas contados; essenciais customizados exigem mapping
  validado no 2B. Nenhuma deduplicação por contato ou inferência de curso/DDD.
- CLI é one-shot, rede com opt-in/real/config completa; status só agregados.
  Nenhum lifespan/scheduler dá início a Lead Ads. URLSQLite canonicalizada.
- Logging protege segredos, Graph URLs/cursors e verify token no access logger.
  Proxies externos continuam exigindo regra própria antes da exposição.
- Gate 2A tem evidência local de 283 testes / 2 avisos; Gate 2B não executado. Versão,
  permissões e token reais permanecem pendentes por documentação retornou 429; fontes
  Meta-owned dão fundamento mínimo, não prova de integração real atual.
