# Meta KPI Calculator

Aplicação local para consolidar métricas de campanhas da Meta e calcular KPIs
de investimento, leads e matrículas da RCTEC, FECAF Florianópolis e Curso com
Bolsa.

Esta entrega contém Analytics até 9C, a Fase 1 do mini-CRM local e a
implementação técnica Lead Ads 2A, validada apenas com mocks. A integração 2B
completa segue pendente; o teste direto 2B.2 persistiu uma lead fictícia e
confirmou o replay idempotente. Modelagem de leads, importação e API CRM são preservadas.
Inclui contrato do MVP, configuração,
infraestrutura SQLite/Alembic, endpoint de saúde, modelos de domínio, dados
fictícios, serviço interno de KPIs, cliente Meta mock-first e serviço interno de
sincronização com agendamento opcional, além da API REST local para conexão,
sincronização, campanhas, Insights, matrículas, dashboard, exportação e painel
Streamlit, hardening operacional, lançamento diário seguro e leitura orientada
à decisão. Não há integração
com BotConversa nesta entrega.

## Prioridade atual — mini-CRM local

A Fase 0 e a fundação local Fase 1 estão preservadas. Fase 2A acrescenta cliente
Graph, webhook assinado, inbox e recuperação manual; a preparação local da
Fase 2B.3 acrescenta um gateway webhook-only, ainda sem túnel nem configuração
Meta. Integração real ponta a ponta segue pendente. Analytics permanece
funcional. Não há login, interface comercial, PostgreSQL ou deploy. Não exponha
a API privada para publicar o webhook.

- [Auditoria e inventário A/B/C/D](docs/TECHNICAL_AUDIT.md)
- [Arquitetura atual e proposta modular](docs/ARCHITECTURE.md)
- [Roadmap CRM fases 0–5](docs/CRM_ROADMAP.md)
- [Modelo e planejamento PostgreSQL](docs/CRM_DATA_MODEL.md)
- [Integração futura Lead Ads](docs/META_LEAD_ADS_INTEGRATION.md)

### Contrato local da Fase 1

`Lead` representa uma submissão individual e usa `meta_lead_id` textual único;
telefone/e-mail não são chaves únicas. Os campos observados da planilha são
persistidos com seus IDs e snapshots. `lead_status` da Meta vira
`source_status`; o status interno começa em `NEW` (`NEW`, `CONTACTED`,
`INTERESTED`, `ENROLLED`, `NO_RESPONSE`, `LOST`). `course` fica vazio se não
informado. Uma campanha local só é relacionada quando seu ID Meta já existe.
Datetime sem offset é interpretado como UTC e telefone não recebe DDD inferido.

`LeadActivity` registra importação automática, mudança de status e atividades
do operador (`NOTE`, `CONTACT_ATTEMPTED`, `CONTACT_MADE`). A origem do ator é
`SYSTEM_IMPORT` ou `LOCAL_OPERATOR`; `actor_id` permanece nulo enquanto não
houver identidade real. Reimportar o mesmo ID preserva status, notas e histórico;
campos de origem presentes podem ser corrigidos e a atividade guarda somente os
nomes dos campos que mudaram.

A migration `0005_crm_leads` é aditiva. Após `alembic upgrade head`, simule a
importação com:

```bash
PYTHONPATH=src python -m meta_kpi_calc.crm.import_cli \
  /caminho/para/exportacao-meta.xls \
  --database-url sqlite:////caminho/absoluto/meta_kpi_demo.db
```

A CLI é dry-run por padrão; passe `--commit` para persistir. Aceita CSV UTF-8,
XLSX sem fórmulas e SpreadsheetML 2003 com extensão `.xls`; XLS binário OLE,
fórmulas, arquivos acima de 20 MiB e cabeçalhos extras são recusados. Imprime
somente totais/códigos de erro. A API oferece `GET /api/crm/leads` (offset,
limit, status, campaign_id e busca), detalhe, PATCH de status e leitura/criação
de atividades. As cinco operações exigem conexão de loopback; isso não é
autenticação e não autoriza publicação via proxy ou host remoto.

As alterações detalhadas estão descritas em `docs/CRM_DATA_MODEL.md`,
`docs/CRM_ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/STATUS.md` e
`docs/OPERATIONS.md`; esses documentos acompanham a implementação no repositório.

### Integração Lead Ads — Gate 2A local

Implementação técnica local validada; Gate 2B **não executado**. Baseline Fase 1:
228 testes aprovados. Após implementação e correções de revisão:
`pytest -q` — **283 aprovados, 2 avisos conhecidos, 61,20s**;
`compileall` e `git diff --check` aprovados. Nenhuma chamada Meta real foi realizada.

Fluxo: POST assinado → commit inbox → ACK; CLI worker → claim/commit → GET
Graph → normalização → fence + ingest_lead + COMPLETED numa transação.
Reconciliação manual percorre todas as páginas da fonte autorizada, filtra UTC
localmente e só avança checkpoint ao concluir o scan. HTTP fica fora de
transações. O `MetaClient` Analytics não foi alterado.

- Migration `0006_lead_ads_inbox`: WebhookEvent, ReconciliationState e coluna
  nullable `Lead.meta_page_id`. Alembic segue autoridade única; nenhuma migration
  histórica ou fórmula foi alterada. Execute migrations antes dos comandos.
- `GET /webhooks/meta/lead-ads` valida hub.mode/verify_token e retorna challenge.
  `POST` limita stream a 256 KiB por padrão, valida HMAC-SHA256 raw-body pelo
  `X-Hub-Signature-256`, valida batch/Páginas e confirma só após commit durável.
  Integração incompleta/desabilitada ou modo demo retorna 503, sem bypass HMAC.
- Cliente HTTPX injetado: somente GET Graph fixo, bearer no header, redirects
  bloqueados, timeouts explícitos, paginação reconstruída por cursor confiável
  com cap local, erro fixo sem raw. Sem retry em memória/sleep. Versão Lead Ads
  é independente e obrigatoriamente explícita; nenhuma versão atual é presumida.
- Inbox deduplica por Página+lead; worker adquire lease com UPDATE atômico,
  tenta no máximo 5 claims por evento por padrão, backoff de 30s até 3600s; recupera
  lease expirada após reinício. Fence impede worker antigo de gravar ou concluir.
  Duplicação não reseta COMPLETED/FAILED. SQLite é single-host com escritas
  serializadas, sem garantia exactly-once distribuída.
- Reconciliação: mapping form→page, primeiro start UTC explícito e end opcional capturado no início,
  overlap de 300s e máximo de 31 dias locais por padrão; sem filtro Graph não confirmado.
  Próxima scan começa novamente na primeira página a partir de checkpoint-overlap;
  timeout/cap/payload inválido/falha de banco não avança checkpoint. Start explícito que
  deixe lacuna depois do checkpoint é rejeitado. Lease por formulário impede
  scans simultâneos e protege avanço final.
- `field_data`: full_name/phone_number/email/city/state conhecidos; sem inferir
  DDD/curso. Perguntas desconhecidas geram contador `unmapped_fields`, sem nomes
  ou respostas retidos; resultado pode ser incompleto. Antes do 2B, perguntas
  essenciais precisam de mapeamento explícito. Replay preserva status/notas/
  campos locais; igualdade de timestamp considera UTC ao ler SQLite naive.

Configuração em `.env.example`: `LEAD_ADS_ENABLED=false` por padrão; segredos
`LEAD_ADS_ACCESS_TOKEN`, `LEAD_ADS_APP_SECRET`, `LEAD_ADS_VERIFY_TOKEN` separados,
sem fallback de Ads; `LEAD_ADS_API_VERSION` sem default;
`LEAD_ADS_ALLOWED_PAGE_IDS` é lista JSON; `LEAD_ADS_AUTHORIZED_SOURCES` é mapping
JSON formulário→Página. Os demais `LEAD_ADS_*` definem limites locais, não regras
oficiais da Meta. Nenhuma credencial existente foi alterada.

Comando local sem rede (banco existente migrado; URLs relativas são resolvidas
uma vez contra cwd e canonicalizadas antes de Settings):

```bash
PYTHONPATH=src python -m meta_kpi_calc.crm.lead_ads_cli status \
  --database-url sqlite:////caminho/absoluto/banco-migrado.db
```

`status` retorna contagens de eventos/tentativas/estados de reconciliação, idade
de pendência e última reconciliação, sem IDs ou PII. Comandos de rede futuros
`process` e `reconcile` exigem `DEMO_MODE=false`, configuração habilitada/token/
versão e flag `--allow-network`, além de banco selecionado. Process aceita
`--max-events`; reconcile requer `--form-id` autorizado e `--start` no primeiro
scan, com `--end` opcional. **Não executados nesta entrega**. Nada é iniciado
por lifespan, scheduler ou abrir painel.

Logging redige os três segredos, URLs Graph/cursors e query hub.verify_token;
filtro dedicado uvicorn.access cobre propagate=false. Logs de proxies externos
exigem redação/desativação própria antes de expor HTTPS. Não guardar raw,
contatos, tokens ou exportações reais em logs/fixtures/Git.

As páginas oficiais developers.facebook.com retornaram 429. Contratos mínimos
foram fundamentados em [solução Meta-owned](https://github.com/facebookincubator/catalogue-of-api-solutions/blob/main/solutions/leads/leads-retrieval-set-up-checker.md),
[sample Lead Ads arquivado](https://github.com/fbsamples/lead-ads-webhook-sample/blob/main/README.md)
e [exemplo oficial HMAC](https://github.com/fbsamples/whatsapp-api-examples/blob/main/signature-validation-with-webhooks-payloads/app.py).
Isso não confirma suporte atual de versão/permissões/token ou retenção.

### Gate 2B — próxima etapa: webhook `leadgen`

O acesso direto funcionou após duas respostas iniciais 401. A primeira resposta
200 criou somente a lead pedida e a segunda confirmou `already_existed`, sem
nova atividade ou aumento de contagem. A evidência detalhada está em
`docs/STATUS.md`. Em etapa própria, preparar HTTPS temporário restrito ao path
`/webhooks/meta/lead-ads`, validar HMAC e processar pela inbox/worker explícito.
Não publicar a API CRM completa. Reconciliação, deploy e dados não fictícios
continuam fora do escopo e exigem validação e autorização próprias.

Os detalhes de arquitetura, status, roadmap e operação estão versionados em
`docs/`. Não houve commit, push ou merge durante a 2A.

### Fase 2B.2 — busca direta de uma lead

A CLI oferece `fetch-lead`, uma chamada Graph de objeto por execução. Ela exige
`--allow-network` e `--lead-id`, consulta somente `GET /{lead-id}`, confere o
`form_id` retornado no mapping `LEAD_ADS_AUTHORIZED_SOURCES`, valida a Página
associada e então usa o normalizador e `ingest_lead()`. O resultado não inclui
campos pessoais; informa criação/reimportação, histórico e diferença agregada
na contagem de leads. Não percorre o formulário nem chama reconciliação.

Use um token Lead Ads recém-rotacionado em `.env`/secret manager, configure a
versão explícita e a relação formulário→Página autorizada. Antes de cada
execução que possa gravar, faça backup consistente do SQLite e confirme o
caminho mostrado pela CLI. Em 29/10/2026, após duas respostas 401, o GET
retornou 200, persistiu uma lead e uma atividade `IMPORTED`; a repetição
retornou `already_existed` sem nova atividade. Nenhum outro lead foi importado.
Os backups estão registrados em `docs/STATUS.md`. Exemplo:

```bash
LEAD_ADS_ENABLED=true \
LEAD_ADS_API_VERSION=v26.0 \
LEAD_ADS_ALLOWED_PAGE_IDS='["100130844916605"]' \
LEAD_ADS_AUTHORIZED_SOURCES='{"3207253009465556":"100130844916605"}' \
DEMO_MODE=false \
.venv/bin/python -m meta_kpi_calc.crm.lead_ads_cli \
  --database-url 'sqlite:///./data/meta_kpi.db' \
  --allow-network --lead-id '1799753681047061' fetch-lead
```

O estado e as evidências da execução real (ou o motivo de ela não ter ocorrido)
estão em `docs/STATUS.md`. Webhook e reconciliação continuam fora deste teste.

### Fase 2B.3 — preparação local do webhook

`meta_kpi_calc.crm.webhook_gateway:app` é um alvo local isolado para eventual
túnel: só encaminha o path exato `/webhooks/meta/lead-ads` com GET/POST para a
API em `127.0.0.1:8000`; bloqueia os demais paths/métodos, limita o corpo e não
repassa cookies, autorização ou cabeçalhos de encaminhamento. Não tem docs,
OpenAPI ou health endpoint. Testes usam upstream mockado. **Túnel público,
painel Meta, geração de lead e worker real ainda não foram iniciados.** O `.env`
atual não está pronto para ingress: faltam App Secret, Verify Token, allowlist,
mapping form→Página, versão Lead Ads explícita e habilitação. Configure-os
localmente; nunca compartilhe segredos no chat. Consulte
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) e [`docs/STATUS.md`](docs/STATUS.md).

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

## Lançamento diário e cobertura comercial

Nesta etapa, um lançamento ainda é um resumo diário por campanha e curso; não é
uma matrícula individual. No painel, use “Lançamento diário” para escolher a
campanha pelo nome, marca e status, informar a data e salvar ou editar o
fechamento. Se houver outro registro com a mesma campanha, data e curso, a tela
abre o registro existente para edição.

Depois de salvar, informe a situação comercial do dia: parcial ou fechada. Sem
essa confirmação, a cobertura do resumo permanece “não informado”; ausência de
registro nunca é interpretada como zero de matrículas ou receita. A cobertura
considera os dias em que houve Insight, lançamento diário ou fechamento
comercial no período.

Para bancos existentes, aplique a migration antes de iniciar a aplicação:

```bash
alembic upgrade head
```

O lançamento diário, a cobertura, o painel e a comparação detalhada foram
validados localmente. As etapas 9A e 9B compõem a base mínima para o piloto
assistido; antes da liberação, ainda é necessário reconciliar uma janela curta
com a fonte comercial do cliente. A etapa 9C acrescenta a comparação detalhada
e permanece antes da evolução de matrícula individual da etapa 10.

## Dashboard, exportação e painel

`GET /api/dashboard/summary` exige `date_start` e `date_stop` e aceita os filtros
conjuntivos opcionais `brand`, `campaign_id`, `course` e `effective_status`.
`course` representa a classificação da campanha, não o curso do registro de
matrícula. O endpoint devolve totais, KPIs e avisos já calculados pelo serviço
interno, inclusive métricas não calculáveis como `null`.

`GET /api/dashboard/campaign-comparison` usa esse mesmo recorte e devolve uma
linha por campanha com investimento, leads, contratadas, pagantes, CAC
financeiro, receita recebida e cobertura comercial. `last_media_sync_at` no
resumo informa a última carga de mídia no recorte. `GET /api/dashboard/default-period`
informa o menor e maior dia de Insight persistido, sem consultar a Meta.

`GET /api/dashboard/campaign-comparison/detail` exige `campaign_ids` repetidos
para selecionar duas ou mais campanhas e devolve, na ordem escolhida, todos os
totais e KPIs existentes, cobertura, avisos e última atualização de mídia. A
aba **Comparar campanhas** percorre a listagem completa, aplica os filtros
globais e exibe uma matriz com unidades e motivos para valores ausentes ou não
calculáveis. A margem de contribuição aparece como não agregada neste recorte.
`GET /api/dashboard/campaign-comparison/export` gera o XLSX da mesma seleção e
inclui cobertura, códigos e mensagens dos avisos.

`GET /api/meta/sync/status` informa apenas o último estado local persistido da
sincronização (`running`, `completed`, `failed` ou `not_confirmed`); também não
consulta a Meta. `GET /api/export` exige os mesmos filtros, além de `format=csv|xlsx` e
`dataset=performance|enrollments`. CSV contém apenas o dataset solicitado em
UTF-8-SIG; XLSX produz sempre as abas `Resumo`, `Diário`, `Matrículas` e
`Campanhas`. Textos iniciados por `=`, `+`, `-` ou `@` são neutralizados antes da
exportação e campos brutos da Meta não aparecem.

Com a API em execução, inicie o painel local:

```bash
streamlit run frontend/app.py
```

O painel usa exclusivamente `API_BASE_URL` (por padrão
`http://127.0.0.1:8000`), abre no período existente do demo quando há Insights
e aplica filtros somente após **Aplicar filtros**. A visão geral organiza mídia,
comercial e financeiro, explica cada KPI e mostra cobertura, pendências e
inconsistências. A exportação XLSX usa o mesmo recorte exibido e invalida o
arquivo preparado se os filtros mudarem. O painel mostra um banner em
demonstração e trata API vazia ou indisponível sem exibir traceback. Ele só
consulta a Meta quando o operador usa **Testar conexão Meta** ou
**Sincronizar período filtrado**; não lê SQLite diretamente.

As decisões congeladas, a matriz de aceite e o andamento ficam em `docs/`.
O procedimento completo de instalação, migrations, backup, inicialização,
diagnóstico, scheduler e preparação de uma conexão real está em
[`docs/OPERATIONS.md`](docs/OPERATIONS.md). A conexão real descrita ali não foi
executada; o token deve ser inserido diretamente no `.env` local, nunca enviado
pelo chat.
