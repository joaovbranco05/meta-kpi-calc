# Arquitetura do projeto

Referência: Fase 2A mini-CRM, 29/10/2026. Estado efetivo: Analytics até 9C,
fundação CRM Fase1 e integração técnica Lead Ads local com mocks. `STATUS.md` define o avanço autorizado.

## Arquitetura existente

Monólito modular em camadas com service layer: FastAPI é a fonte dos contratos;
Streamlit consome apenas REST; serviços calculam KPIs, sincronizam e montam
relatórios; SQLAlchemy síncrono persiste no SQLite; Alembic controla o schema.
Não há microserviços, repository genérico, Unit of Work ou DDD formal.

```text
frontend/app.py (Streamlit) ──HTTP──> api/app.py + api/routes/rest.py
                                          │
                         services KPI/reports/sync
                              │                │
                          db/SQLite       MetaClient GET
                              │                │
                           Alembic       Meta Graph API
APScheduler opcional ──> SyncService (um processo)
```

`MetaClient` tem conta, campanhas e Insights; não tem Lead Ads individual.
`CampaignInsight.leads` é contagem. `EnrollmentRecord` é resumo diário, não
aluno/matrícula individual. `CommercialClosure` registra cobertura, não um
status de atendimento. O baseline Analytics de cinco entidades/18 operações
está em TECHNICAL_AUDIT. Com Lead/Activity e inbox/reconciliation, o estado
atual tem nove entidades persistentes e 25 operações OpenAPI: 18 Analytics/health,
cinco CRM local e duas webhook. `MetaLeadAdsClient` é o novo adaptador individual;
o cliente de Analytics continua com as responsabilidades anteriores.

A API tem handlers fixos e validação; não tem autenticação. `rest.py` tem 1000
linhas e o painel 1094 no baseline; essa concentração é um risco de manutenção,
não autorização para reescrever tudo. Serviços recebem Session explicitamente,
uma escolha simples adequada ao tamanho atual. Comparação agrega por campanha;
medir consultas antes de otimizar. Lock/scheduler são locais ao processo.

## Direção modular e dependências

Continuar no mesmo repositório, pacote, aplicação e ciclo Alembic. A separação
é de responsabilidades, sem deslocar o código funcional nesta fase:

| Módulo conceitual | Caminhos atuais / futuros | Responsabilidade e fronteira |
|---|---|---|
| Core compartilhado | `core/`, `db/base.py`, `db/session.py`, `api/app.py` | Settings, logging, sessões, Base, composição; identidade/autorização futuras |
| CRM prioritário | `crm/`, router incluído por `api/app.py` | Lead, histórico, ingestão idempotente, importação de arquivo e consultas comerciais |
| Analytics preservado | `services/`, `db/models.py`, `api/routes/rest.py`, `api/schemas.py`, `frontend/` | Conta/campanhas/Insights, agregados, KPIs, exportação e Streamlit |

As entidades CRM usarão a mesma Base e migrations. CRM pode referenciar Campaign
por FK opcional; ausência de campanha não impede capturar lead com ID externo.
Analytics não depende do CRM e não soma leads individuais aos KPIs atuais.
Core não importa CRM para executar configuração ou logging. Routers validam
HTTP e delegam; serviços recebem sessão/HTTPX nas fronteiras; views não acessam
banco nem tokens. Não introduzir camada genérica sem consumidor real.

## Estrutura preparada e crescimento incremental

```text
src/meta_kpi_calc/
  api/                    # contratos e composition root existentes
  core/                   # config/logging existentes
  db/                     # Base/sessão/modelos existentes
  services/               # Analytics e adaptador Meta existentes
  crm/
    __init__.py
    models.py             # Lead e LeadActivity
    ingestion.py          # ingestão idempotente e histórico
    queries.py            # listagem, detalhe e histórico
    import_files.py       # parsers CSV/XLSX/SpreadsheetML
    import_cli.py         # dry-run local, commit opt-in
    api.py                # endpoints CRM locais
frontend/app.py           # Streamlit Analytics existente
alembic/                  # inclui migration aditiva 0005_crm_leads
```

Futuramente, criar dentro de `crm/` somente arquivos com responsabilidade e
consumidor: modelos Lead/Activity, serviço de ingestão, router, schemas e cliente
Lead Ads específico quando cada fase os exigir. Não criar arquivos vazios de
repository, transport, controllers, views ou autenticação. `api/app.py` inclui
o router CRM; este confere o peer loopback, mas não autentica usuários nem
autoriza exposição por proxy ou rede remota.

SOLID aqui significa motivos claros para mudança e dependências de I/O
injetadas. KISS significa reutilizar Session/Base e HTTPX existentes, sem
Protocol, fábricas ou hierarquias especulativas. Extração de transporte HTTP
compartilhado só será avaliada se houver duplicação real na implementação.

## Interface e identidade futuras

Recomendação: interface comercial própria no mesmo projeto, usando o backend
FastAPI; páginas renderizadas no servidor com templates simples são candidatas
para avaliação na fase3. Não se escolhe biblioteca nem adiciona framework nesta
fase. Streamlit permanece painel Analytics. Adaptá-lo é alternativa de menor
custo inicial, mas o script atual concentra estado/HTTP e uma tela de login não
protege a API; separar a experiência comercial reduz esse acoplamento.

Na fase3 comparar um fluxo de login→lista→detalhe→status→histórico, capacidade
de testar sessões/CSRF, manutenção e UX. Identidade compartilhada deve autorizar
cada operação privada no servidor, inclusive endpoints Analytics existentes
quando o host ficar acessível remotamente. Provedor OIDC é candidato; usuários
locais com senha exigiriam hash adequado, recuperação, revogação e proteção
contra tentativas, sem implementação caseira. Webhook é exceção técnica ao
login humano, com assinatura validada e persistência segura. Login Streamlit
com OIDC fornece autenticação, não autorização de recursos
([documentação oficial](https://docs.streamlit.io/develop/concepts/connections/authentication)).

## Dados e operação

SQLite permanece atual. PostgreSQL/Supabase são opções de fase4, não uma troca
de URL: Settings e engine/Alembic contêm código SQLite específico. O plano de
migração e as entidades propostas estão em [CRM_DATA_MODEL.md](CRM_DATA_MODEL.md).
Antes de exposição remota, exigir autorização, TLS, segredos, backups restaurados,
retenção e observabilidade. `/health` atual faz SELECT1: não certifica migrations,
processamento de inbox, segurança ou readiness da implantação.

## Prioridade e planos históricos

9A/9B/9C continuam preservadas. `PLAN.md`, `PLAN-2.md` e `PRODUCT_REVIEW.md`
registram planos anteriores; a 9D não foi executada. O prompt atual substitui a
prioridade de refatoração 9D/matrícula individual pelo roadmap CRM fases0–5.
Não é necessário executar toda a 9D antes de modelar leads; qualquer extração
futura deve proteger contratos e ter motivo concreto. Matrícula, contrato,
pagamento e cancelamento continuam distintos e não entram no CRM por inferência.

Próximo incremento: [CRM_ROADMAP.md](CRM_ROADMAP.md). Integração futura:
[META_LEAD_ADS_INTEGRATION.md](META_LEAD_ADS_INTEGRATION.md). Não houve deploy,
autenticação, webhook, chamada Meta real ou integração BotConversa na Fase1.


## Integração Lead Ads 2A local (29/10/2026)

`crm/lead_ads_client.py` concentra GET HTTPX; `normalizer.py` mapeia field_data
para LeadSubmission; `webhook.py` valida raw HMAC e grava inbox antes do ACK;
`inbox_models.py`/`inbox.py` mantêm modelo técnico e claims/fences;
`processing.py` executa worker one-shot; `reconciliation.py` varre formulários
configurados com lease/checkpoint; `lead_ads_cli.py` dá comandos explícitos.
A factory inclui somente router webhook; não constrói HTTP cliente/worker nem
inicia chamadas Lead Ads no lifespan. MetaClient Analytics permanece intacto.

Fronteiras concretas: HTTP separado de persistência; Session curta recebida nos
serviços; ingest_lead é a única persistência de Lead; nenhuma interface genérica,
SDK ou fila externa. Migration0006 é aditiva e inclui página opcional em Lead.
Settings tem segredos/enable/versão independentes. Config incompleta falha
fechada. A integração só foi validada com mocks; versão/permissões reais e
publicação HTTPS são gate2B futuro, explicitamente não executado.

As descrições de ausência de webhook nas seções Fase1 acima são históricas;
este incremento adiciona apenas as duas operações webhook. API privada segue
local sem login: expor host/proxy não está autorizado pelo gate2A.
