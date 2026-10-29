# Operação local do Meta KPI Calculator

Este runbook cobre o MVP local aprovado até a etapa 9C. O modo demonstração
é o padrão e não precisa de credenciais ou rede. Nenhuma conexão real com a
Meta ou com o BotConversa foi executada durante a implementação.

## Instalação

Use Python 3.12, 3.13 ou 3.14 e mantenha a aplicação restrita a `127.0.0.1`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
```

O `.env` é local e ignorado pelo Git. Nunca envie tokens pelo chat, registre-os
em logs ou adicione-os ao repositório. Para o modo demonstração, deixe
`DEMO_MODE=true`, `SCHEDULER_ENABLED=false` e `META_ACCESS_TOKEN` vazio.

Se o banco já existia antes da etapa 9A, `alembic upgrade head` é obrigatório:
ele aplica a migration `0004_commercial_closures` que registra o fechamento
comercial manual por campanha e data.

## Banco, migrations e backup

Alembic é a única autoridade do schema. A aplicação não cria tabelas nem aplica
migrations no startup.

```bash
alembic upgrade head
alembic check
```

Antes de downgrade ou outra manutenção, pare API e painel. Com os processos
parados, copie o arquivo SQLite ativo para um local seguro. Em demonstração, o
arquivo padrão é `data/meta_kpi_demo.db`; em modo real, é `data/meta_kpi.db`.
Não copie apenas o arquivo principal enquanto houver processo escrevendo, pois
o SQLite usa WAL.

Downgrade é uma operação deliberada e pode remover dados de colunas ou tabelas.
Confira o backup e a revisão de destino antes de executar, por exemplo:

```bash
alembic downgrade -1
```

## Dados de demonstração

Depois de `alembic upgrade head`, carregue o conjunto fictício:

```bash
PYTHONPATH=src python -m meta_kpi_calc.services.demo_seed
```

O seed recusa modo real e é idempotente. Repeti-lo mantém as mesmas três
campanhas, 21 Insights e três matrículas.

## Iniciar e parar

Para iniciar API e Streamlit juntos:

```bash
./iniciar.sh
```

O script usa `127.0.0.1`, grava logs e PIDs em `.logs/` e informa os endereços.
Para uma execução em primeiro plano ou diagnóstico isolado:

```bash
uvicorn meta_kpi_calc.api.app:app --app-dir src --host 127.0.0.1 --port 8000
streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501
```

Ao usar `iniciar.sh`, pare os PIDs exibidos pelo próprio script e confirme que
as portas 8000 e 8501 foram liberadas. Não reutilize um PID antigo sem conferir
qual processo ele identifica.

## Verificação operacional

- API: `http://127.0.0.1:8000/health`
- documentação OpenAPI: `http://127.0.0.1:8000/docs`
- painel: `http://127.0.0.1:8501`

No modo demonstração, `/health` deve indicar `mode=demo`. Campanhas, resumo,
comparação e exportação ficam disponíveis em `/api/campaigns`,
`/api/dashboard/summary`, `/api/dashboard/campaign-comparison`,
`/api/dashboard/campaign-comparison/detail`,
`/api/dashboard/campaign-comparison/export` e `/api/export`.
Resumo, comparação e exportação exigem o mesmo período; o formato e o dataset
também são obrigatórios na exportação. `/api/meta/sync/status` e
`/api/dashboard/default-period` são leituras locais e não acessam a Meta.

Uma sincronização manual real usa `POST /api/meta/sync`, é síncrona, aceita uma
janela inclusiva de no máximo 31 datas e permanece idempotente pelas chaves
naturais. Datas futuras são recusadas.

## Lançamento diário e fechamento comercial

O painel registra um **Lançamento diário**, que continua sendo um total agregado
por campanha, data e curso. Não use essa tela para representar aluno, contrato,
pagamento, parcela ou cancelamento individual.

1. Escolha a campanha pelo nome, marca e status; o ID interno não é uma entrada
   do operador.
2. Informe data, curso, totais comerciais e valores monetários do fechamento.
3. Se a combinação campanha/data/curso já existir, abra e edite o lançamento
   existente. A edição carrega observações e margem já registradas.
4. Declare o fechamento comercial do dia como **parcial** quando ainda houver
   pendências, ou **fechado** quando os totais estiverem confirmados.

No resumo, “não informado” significa que há Insight, lançamento diário ou
fechamento no recorte sem confirmação comercial. Não equivale a zero. “Parcial”
significa que há confirmação incompleta; “fechado” exige todos os pares
campanha/data do recorte fechados. A vigência `start_time`/`stop_time` da
campanha não exclui eventos comerciais de relatórios ou exportação.

## Leads locais

A Fase1 adiciona uma tabela por submissão da Meta e histórico comercial. A API
`/api/crm/...` só aceita conexão de loopback; isso não oferece login e não deve
ser colocado atrás de proxy acessível remotamente. Mantenha o Uvicorn em
`127.0.0.1` até autenticação/autorização serem implementadas.

O importador aceita CSV UTF-8, XLSX sem fórmulas e XML Spreadsheet 2003 (mesmo
quando o arquivo tem extensão `.xls`). XLS binário OLE e colunas desconhecidas
são recusados. O limite é 20 MiB e 50 mil linhas; a atividade de import guarda
apenas o tipo/origem, sem cópia do payload. `created_time` sem timezone é
interpretado como UTC; o telefone não recebe DDD nem correções inferidas.

Depois de `alembic upgrade head`, faça primeiro uma simulação:

```bash
PYTHONPATH=src python -m meta_kpi_calc.crm.import_cli \
  /caminho/para/exportacao-meta.xls \
  --database-url sqlite:////caminho/absoluto/meta_kpi_demo.db
```

Para persistir, acrescente `--commit`. O comando exige seleção explícita do
banco SQLite e imprime somente contagens e códigos de rejeição. Uma transação
engloba as linhas válidas; qualquer falha de persistência cancela o lote. IDs
duplicados são idempotentes, atualizações de origem não alteram status/notas/
histórico/responsável. `lead_status` da Meta permanece `source_status`; o
status interno começa em `NEW`.

Endpoints locais disponíveis: `GET /api/crm/leads` (offset, limit, status,
campaign_id, query), `GET /api/crm/leads/{id}`, `PATCH
/api/crm/leads/{id}/status`, `GET /api/crm/leads/{id}/activities` e `POST
/api/crm/leads/{id}/activities`. O `query` pesquisa nome, e-mail, telefone ou
ID da Meta e deve ser usado somente em contexto local controlado.

## Fase 2B.2 — buscar uma lead por ID

`fetch-lead` faz uma única leitura `GET /{lead-id}` pela Graph API. O comando
exige `--allow-network` e um único `--lead-id`; não consulta a coleção do
formulário, não inicia reconciliação ou worker e não muda status comercial.
Antes de persistir, confere o `form_id` retornado contra
`LEAD_ADS_AUTHORIZED_SOURCES` e usa a Página mapeada, que também deve estar em
`LEAD_ADS_ALLOWED_PAGE_IDS`. Um `page_id` incluído na resposta precisa coincidir.

Configure um token Lead Ads novo fora do Git. Não reutilize `META_ACCESS_TOKEN`
nem cole credenciais em comandos/histórico de shell. `LEAD_ADS_API_VERSION` deve
ser explícita. Faça backup consistente com SQLite Backup API e confirme o banco
antes de executar; o comando se recusa a criar um arquivo de banco inexistente.
O resumo stdout não contém nome, telefone, email ou respostas; mostra apenas
outcome, atividade de importação e contagens agregadas.

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

Uma reexecução da mesma lead é idempotente: não duplica a linha nem a atividade
de importação; `ingest_lead()` também preserva estado comercial e campos locais.
Consulte `STATUS.md` para o resultado real e o backup desta execução controlada.

## Painel, filtros e relatório

O painel abre dados fictícios com o banner de demonstração e usa o intervalo
existente do seed. Escolha **Este mês**, **Mês anterior**, **Últimos 7 dias** ou
**Personalizado**, ajuste marca/status/campanha e use **Aplicar filtros** antes
de interpretar os números. A visão geral mostra mídia, comercial e financeiro;
ela separa informações, pendências e inconsistências. Cobertura comercial não
informada ou parcial pede revisão antes de uma decisão.

Na aba **Exportar**, selecione **Preparar relatório XLSX** e então baixe o
arquivo. O download reflete o recorte ativo e desaparece ao aplicar filtros
diferentes. A aba `Campanhas` do XLSX reproduz a comparação apresentada no
painel.

Na aba **Comparar campanhas**, selecione duas ou mais campanhas. A lista
percorre todas as páginas disponíveis e usa o mesmo período, marca, curso e
status efetivo do recorte global. A matriz apresenta totais e KPIs na mesma
ordem da seleção. “Dado ausente” indica que não há Insight no recorte;
“Não calculável” informa a causa aplicável, como métrica não aditiva,
qualificados incompletos ou denominador zero. Margem de contribuição é exibida
como não agregada neste recorte.

A tabela seguinte mostra cobertura comercial em dias esperados, sem confirmação,
parciais e fechados, além de última atualização e quantidade de pendências. As
pendências detalhadas aparecem por campanha. Use **Preparar exportação da
comparação** para baixar o XLSX da seleção atual; o arquivo em memória é
descartado se filtros ou seleção mudarem, inclusive com menos de duas campanhas.

Abrir o painel, aplicar filtros ou consultar o estado de sincronização não
testa a Meta. Para verificar a configuração real, use **Testar conexão Meta**;
para buscar dados, use **Sincronizar período filtrado**. A sincronização é
síncrona: aguarde o resultado e confira o estado local exibido antes de repetir.

## Scheduler

O scheduler é desligado por padrão. Quando habilitado, revisa a janela móvel
configurada e usa o mesmo `SyncService` da sincronização manual. Execute Uvicorn
com exatamente um worker e sem `--reload`.

O lock evita sobreposição apenas dentro do mesmo processo. Ele não coordena
múltiplos workers, processos ou máquinas. Não habilite o scheduler em mais de
uma instância do MVP.

## Preparar uma primeira conexão real

Este procedimento é somente um runbook; não foi executado nesta entrega.

1. Confirme na documentação oficial da Meta qual versão da Graph API está
   suportada. `META_API_VERSION=v26.0` é apenas o padrão configurável atual e
   ainda não foi confirmado online.
2. Insira `META_ACCESS_TOKEN` diretamente no `.env` local e configure
   `META_AD_ACCOUNT_ID`. Não forneça o token pelo chat.
3. Defina `DEMO_MODE=false`, preserve bancos real e demo em arquivos diferentes
   e mantenha `SCHEDULER_ENABLED=false`.
4. Aplique `alembic upgrade head` ao banco real e inicie somente uma instância
   da API.
5. Consulte explicitamente `/api/meta/connection`. Essa é a primeira operação
   que pode fazer I/O com a Meta no modo real configurado.
6. Execute manualmente uma janela curta e passada. Repita a mesma janela e
   confira idempotência, contagens, classificação e KPIs.
7. Habilite o scheduler somente depois dessa validação, mantendo um worker e
   sem reload.

O cliente é somente leitura. Não há operação para alterar campanha, orçamento
ou anúncio.

## Logs e diagnóstico

`iniciar.sh` grava `.logs/uvicorn.log` e `.logs/streamlit.log`. Os logs são
ignorados pelo Git e o backend redige o token configurado. Ainda assim, não
publique arquivos de log sem revisá-los.

Em falha:

1. confira `/health` e se a migration está em `head`;
2. confirme que o banco ativo corresponde ao valor de `DEMO_MODE`;
3. em demo, execute novamente o seed;
4. confira se portas ou PIDs antigos ainda estão ativos;
5. em modo real, valide configuração, versão oficial da Graph API e o histórico
   sanitizado de sincronização, sem copiar token ou resposta externa.

## Limitações e evoluções futuras

- O ambiente local validado usa Python 3.14.6; Python 3.12 permanece para CI
  futuro.
- O SQLite e o lock atual são locais; não há coordenação distribuída ou retry de
  banco.
- A versão atual da Graph API ainda precisa ser confirmada antes da conexão.
- Não há autenticação própria, deploy, Docker, uploads ou observabilidade
  externa neste MVP local.
- Leads, atribuição, contatos, Kanban, mensagens e BotConversa continuam fora do
  MVP. Uma evolução futura deve conectá-los pelos IDs externos já preservados e
  manter ingestão idempotente.
- As etapas 9A e 9B continuam sendo o mínimo funcional para a preparação do
  piloto assistido; a 9C acrescenta comparação detalhada, não operação
  autônoma. Antes da entrega ao cliente, reconcilie uma janela curta com a
  fonte comercial definida e siga o roteiro `customer-pilot-readiness`.

## Fase 2B.3 — preparação local do callback

`meta_kpi_calc.crm.webhook_gateway:app` é um gateway separado que encaminha
somente `GET` e `POST /webhooks/meta/lead-ads` para a API em `127.0.0.1:8000`.
Os demais caminhos retornam 404, os demais métodos retornam 405, e o gateway
não oferece docs, OpenAPI, health, arquivos estáticos ou acesso ao CRM/Analytics.
O corpo é limitado por `LEAD_ADS_BODY_MAX_BYTES` e somente os cabeçalhos de
conteúdo, assinatura Meta e accept são encaminhados. O upstream é fixo em
loopback. A API privada e o gateway devem continuar vinculados a `127.0.0.1`.

Configuração sem segredos deve incluir `LEAD_ADS_ENABLED=true`,
`LEAD_ADS_API_VERSION` explícita, `LEAD_ADS_ALLOWED_PAGE_IDS` e
`LEAD_ADS_AUTHORIZED_SOURCES` (formulário→Página). App Secret, Verify Token e
Access Token Lead Ads ficam apenas no `.env`/secret manager local, em entradas
separadas; não os envie no chat nem na linha de comando. Modo demo deve estar
desativado e a aplicação deve usar o banco real intencionalmente selecionado.
Handshake só fica pronto quando App Secret, Verify Token, allowlist e ao menos
um mapping autorizado estiverem presentes.

Para preparação local, após revisar a configuração e o caminho do banco:

```bash
uvicorn meta_kpi_calc.api.app:app --app-dir src --host 127.0.0.1 --port 8000
uvicorn meta_kpi_calc.crm.webhook_gateway:app --app-dir src --host 127.0.0.1 --port 8765
```

O segundo comando expõe localmente somente a fronteira webhook-only. Ainda
assim, **não encaminhe a porta 8765 à internet até receber autorização explícita**.
Quando a etapa externa for autorizada, o túnel deverá apontar exclusivamente
para `127.0.0.1:8765`, nunca para a porta 8000 ou para o Streamlit. Não há um
provedor de túnel escolhido/configurado nesta entrega; opções que exijam conta,
instalação ou autenticação devem ser avaliadas com o operador primeiro.

Para encerrar cada processo, use Ctrl-C no terminal correspondente e confirme
que as portas 8000/8765 foram liberadas. Antes da futura publicação, será
necessário provar por HTTPS que somente o callback GET/POST responde e que
`/api/crm/*`, `/api/meta/*`, `/api/dashboard/*`, `/docs`, `/openapi.json`,
`/health`, `/redoc`, paths alternativos e métodos não permitidos são bloqueados
na fronteira pública. Esta entrega comprova o comportamento do gateway por
testes locais com upstream mockado; não comprova TLS, túnel nem isolamento em
uma fronteira pública.

O estado da inbox pode ser consultado sem rede:

```bash
PYTHONPATH=src python -m meta_kpi_calc.crm.lead_ads_cli status \
  --database-url sqlite:////caminho/absoluto/data/meta_kpi.db
```

Só depois de autorizar e receber exatamente um evento fictício esperado na
inbox, conferir ausência de eventos pendentes inesperados e fazer backup
consistente do SQLite, execute manualmente:

```bash
PYTHONPATH=src python -m meta_kpi_calc.crm.lead_ads_cli process \
  --database-url sqlite:////caminho/absoluto/data/meta_kpi.db \
  --max-events 1 --allow-network
```

O worker consulta a Graph API e grava lead/histórico; não o execute antes desses
controles. Não usar reconciliação nesta etapa.
