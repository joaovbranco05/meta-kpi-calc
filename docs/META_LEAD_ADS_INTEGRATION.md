# Meta Lead Ads — implementação local 2A e validação futura 2B

Referência: 29/10/2026. Gate 2A em validação local, com HTTPX mockado e SQLite
temporário. Gate 2B não executado nem autorizado. Nenhum túnel, deploy, inscrição
de app/Página, token real ou mensagem foi criado nesta execução.

## Contratos externos e evidência

A documentação de [recuperação de leads](https://developers.facebook.com/docs/marketing-api/guides/lead-ads/retrieving/)
e [Webhooks Graph](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/)
retornou HTTP 429 na consulta desta fase. Não foi possível confirmar versão
atual suportada, grants/permissões, ciclo de tokens, retenção, filtros ou limites
oficiais. A integração usa versão explícita independente `LEAD_ADS_API_VERSION`,
sem default; o `v26.0` do Analytics não é assumido como validado para Lead Ads.

Fontes Meta-owned acessíveis fundamentam os contratos mínimos:

- [Catalogue de soluções — lead retrieval checker](https://github.com/facebookincubator/catalogue-of-api-solutions/blob/main/solutions/leads/leads-retrieval-set-up-checker.md): evento de Página `leadgen`, inscrição de Página, GET individual, edge de leads do formulário e campos mínimos.
- [Lead Ads webhook sample](https://github.com/fbsamples/lead-ads-webhook-sample/blob/main/README.md) e [collection de exemplo](https://github.com/fbsamples/lead-ads-webhook-sample/blob/main/postman/FB%20Lead%20Ads%20%28Part%201%20-%20The%20Webhook%29.postman_collection.json): handshake `hub.*`, object page/entry/changes/leadgen. Repositório arquivado em 2025: comprova exemplo histórico, não suporte atual de versão/permissão.
- [Exemplo oficial de assinatura de webhook](https://github.com/fbsamples/whatsapp-api-examples/blob/main/signature-validation-with-webhooks-payloads/app.py): HMAC-SHA256 em bytes originais e header `X-Hub-Signature-256`. É fonte do mecanismo criptográfico, não prova de permissões Lead Ads.

Nenhum endpoint de catálogo de páginas/formulários foi inventado. Fontes para
reconciliação são configuradas explicitamente por IDs de formulário e Página.
Os limites de corpo/páginas/tentativas abaixo são políticas locais, não limites
atribuídos à Meta. Compatibilidade atual comprovada somente por mocks.

## Fluxo implementado

```text
GET handshake ──> verify token + challenge
POST webhook ──> limite de bytes ──> HMAC ──> validação batch
                                             │
                                  inbox transação/commit ──> ACK
                                             │
CLI process ──> claim/commit ──> GET lead ──> normalizador
                                             │
                       fence + ingest_lead + COMPLETED (mesmo commit)

CLI reconcile ──> lease da fonte ──> GET form/leads paginado
                         │               │
                         └── fence + ingest_lead por página
                                         │
                    checkpoint só após traversal completo bem-sucedido
```

`MetaClient` de Analytics permanece intacto. Novo `MetaLeadAdsClient` recebe
HTTPX injetado, token próprio e versão explícita. Faz somente GET individual
`/{lead_id}` e `/{form_id}/leads` em HTTPS Graph fixo, fields
`id,created_time,ad_id,form_id,field_data`. IDs ASCII numéricos até 64 posições;
redirects desabilitados por requisição; bearer somente no header; timeouts
connect/pool 5s e read/write 10s, resposta até 2 MiB. Paginação valida origem e
path de next, extrai apenas `paging.cursors.after` e reconstrói o endpoint.
Cursor repetido, path/host suspeito ou cap alcançado falham, sem truncar como
sucesso. Cursor e URL não são persistidos.

Uma tentativa HTTP por chamada, sem sleeps nem retries em memória. Timeout,
transporte, 429 e 5xx são transitórios; 401/403, 404, outras rejeições, erro
Graph e payload inválido recebem códigos permanentes fixos. Não se presume
semântica dos códigos internos Graph não confirmados. `Retry-After` inteiro é
limitado e usado apenas no agendamento durável do worker. Reconciliação falha
para rerun explícito, sem repetição longa invisível.

## Webhook e limites

`GET /webhooks/meta/lead-ads`: modo subscribe, token comparado em tempo
constante, challenge não vazio até 1024 caracteres. Erros 400/403 fixos.
`POST` no mesmo path: stream limitado (default 256 KiB), HMAC SHA256 sobre os
bytes originais antes do JSON; assinatura ausente/adulterada é 403, oversize
413, payload inválido 400, Página não autorizada 403. Não existe bypass demo.
No máximo 100 entries e 1000 changes por batch. Eventos não-leadgen com
estrutura válida são ignorados; qualquer evento leadgen inválido/Página
proibida rejeita o batch inteiro antes de persistir. IDs extraídos: lead,
Página, formulário/anúncio opcionais; entry.id e value.page_id devem coincidir.

Em modo demo ou sem config habilitada + app secret + verify token + allowlist,
rotas retornam
503 sem persistência. Verify token só serve ao handshake; não substitui HMAC.
Inbox é gravada em uma transação e ACK ocorre após commit; falha de banco
retorna 503. Perda de ACK depois do commit é segura para reenvio idempotente.
Nenhum payload bruto é armazenado. Rotas não consultam Graph nem criam worker.

## Inbox e worker retomável

`0006_lead_ads_inbox` cria WebhookEvent e ReconciliationState e acrescenta
`Lead.meta_page_id` opcional. Dedup inbox: `meta:leadgen:{page}:{lead}` UNIQUE.
Estados: PENDING, PROCESSING, COMPLETED, RETRY, FAILED; tentativas >= 0; lease
obrigatória apenas durante PROCESSING; índices por status/due e expiry.
Metadados: IDs mínimos, origem WEBHOOK, timestamps UTC, contador de campos não
mapeados e código de erro fixo. Sem PII de resposta ou segredos.

Claim é UPDATE condicional atômico no banco com token novo e incremento de
attempts; commit encerra sessão antes do HTTP. Finalização usa token + estado
+ lease ainda válida; conclusão e `ingest_lead()` são atômicos. Worker antigo
não pode gravar lead/atividade ou finalizar depois de perder lease. Falha de
banco na finalização deixa lease recuperável; não finge sucesso. PROCESSING
expirado é reclamado; orçamento exaurido fica FAILED sem HTTP adicional.

Default: 5 claims por evento, lease 120s, backoff exponencial base 30s até 3600s;
Retry-After limitado participa do delay. Permanentes vão para FAILED; transitórios
para RETRY enquanto há orçamento. Duplicado webhook não reseta tentativas,
COMPLETED ou FAILED. Falhas técnicas não viram notas comerciais.

CLI process é one-shot com máximo de eventos e termina. Não usa BackgroundTasks,
threads automáticas, APScheduler, Celery ou fila externa. A garantia é retomada
com persistência idempotente, não exactly-once distribuído. SQLite single-host
serializa escritas; não há garantia multi-host nem escalabilidade distribuída.

## Normalização e ingestão

Graph timestamps exigem offset e são convertidos para UTC; entrada inválida
impede conclusão/checkpoint. `field_data` aceita full_name, phone_number, email,
city, state; zero respostas é ausência, uma string dentro do limite é mapeada;
múltiplos valores conhecidos ou duplicatas conflitantes são rejeitados.
Telefone continua texto, sem inferir DDD; curso não é inferido. IDs de origem
são preservados, Campaign local opcional. Página/contexto form/ad inconsistentes
são rejeitados. Campos ausentes não sobrescrevem valores existentes.

Campos desconhecidos são ignorados com contador `unmapped_fields` persistido
na metadata técnica/retornado na CLI, sem guardar nomes ou respostas. Um
contador positivo indica mapeamento incompleto, não dados completos. Perguntas
personalizadas essenciais exigem mapeamento explícito e validado antes do 2B;
esta fase não cria armazenamento arbitrário de PII. Nomes de campaign/adset/ad
não são inferidos nem solicitados por fields não confirmados.

Toda gravação usa `ingest_lead()` existente. Status, notas, curso e histórico
comercial são preservados. A comparação de meta_created_time trata retorno
naive SQLite como UTC para igualdade, evitando SOURCE_CORRECTED espúria em
replay do mesmo instante; importação manual e fórmulas Analytics permanecem.

## Reconciliação

Fonte autorizada é mapping form→page em config. Primeira execução exige start
UTC/offset explícito; end padrão captura o começo da execução. Janela local
máxima default 31 dias, overlap default 300s. Próxima execução sem start usa
checkpoint anterior como início e aplica overlap. Start explícito posterior ao
checkpoint+overlap é rejeitado antes de HTTP para não criar lacuna; início mais
antigo permite replay e checkpoint nunca regride. Todas as páginas disponíveis
são percorridas, mesmo com leads antigos; não se presume ordenação nem envia
filtro temporal Graph sem confirmação oficial. Filtro é local, inclusivo.

Lease por fonte impede scan concorrente. Cada página normalizada é persistida
em transação curta com fence e renovação de lease. Falhas podem deixar páginas
já gravadas, mas não avançam `completed_until`. Somente traversal completo,
sem cap/timeout/payload inválido/falha DB, permite checkpoint final com token
vigente. Checkpoint nunca regride. Reinício começa na primeira página da janela
sobreposta; cursor só vive em memória. Webhook e reconciliação convergem no
mesmo UNIQUE Lead. Não se promete recuperação além da retenção disponível da
Meta, nem cobertura histórica total.

## Configuração e comandos

Todas variáveis `LEAD_ADS_*` estão em `.env.example`, sem segredos. enabled=false
por padrão; token Lead Ads, app secret e verify token são SecretStr separados,
sem fallback Ads. Status local não faz rede. Worker/reconcile exigem enabled,
versão/token explícitos, DEMO_MODE=false e `--allow-network`; executar com esse
opt-in é ação posterior autorizada, não parte desta entrega.

```bash
PYTHONPATH=src python -m meta_kpi_calc.crm.lead_ads_cli status \
  --database-url sqlite:////caminho/absoluto/banco-migrado.db
```

Comandos de uso futuro, **não executados nesta fase**:

```bash
PYTHONPATH=src python -m meta_kpi_calc.crm.lead_ads_cli process \
  --database-url sqlite:////caminho/absoluto/banco-migrado.db \
  --max-events 100 --allow-network
PYTHONPATH=src python -m meta_kpi_calc.crm.lead_ads_cli reconcile \
  --database-url sqlite:////caminho/absoluto/banco-migrado.db \
  --form-id ID_AUTORIZADO --start 2026-10-29T00:00:00Z --allow-network
```

URLs SQLite relativas são canonicalizadas contra cwd antes de criar Database,
e o arquivo exato precisa existir. CLI status imprime contagens por estado,
tentativas acumuladas, contagem de formulários por last_result, idade de
pendência/última reconciliação e códigos fixos,
sem IDs, nomes, telefone, e-mail, tokens ou raw. Logging existente redige novos segredos, URLs Graph que HTTPX registra e
hub.verify_token da query; filtro no logger uvicorn.access cobre handlers com
propagation desativada. **Logs de proxy externo ainda exigem redação/desativação
antes de exposição.** Não expor Analytics/CRM privado por proxy apenas para publicar o
webhook. Login/auth continuam fora desta fase.

## Fase 2B.3 — gateway local preparado; gate externo pendente

`meta_kpi_calc.crm.webhook_gateway:app` é um app ASGI independente para ser o
alvo local de um futuro túnel. A allowlist é literal: `GET` e `POST` apenas em
`/webhooks/meta/lead-ads`, comparando também o path bruto. Qualquer outro path
retorna 404; outros métodos no callback retornam 405 com `Allow: GET, POST`.
Não há docs, OpenAPI, health, redirecionamento de barra, static files ou
roteamento para CRM/Analytics. Upstream HTTP só pode ser IP loopback e é
default `127.0.0.1:8000`; redirecionamentos ficam desabilitados. Body usa o
limite configurado, headers encaminhados são mínimos e erros de upstream são
sanitizados. O app é independente para o operador poder apontar o túnel à porta
8765 sem expor diretamente Uvicorn principal na porta 8000.

Testes com HTTPX MockTransport cobrem callback GET/POST, paths privados e
alternativos, métodos, path com barra final, body acima do limite, filtragem de
headers, transporte indisponível e rejeição de upstream não-loopback. A inbox e
worker também passaram a conferir mapping formulário→Página; evento sem essa
associação é rejeitado no webhook e, para evento legado/enfileirado, o worker
marca origem não autorizada antes de qualquer GET Graph.

Isto prova somente o comportamento local do gateway e os controles em testes.
**Não foi iniciado túnel HTTPS, teste em fronteira pública, handshake com Meta,
inscrição de app/Página, lead novo ou worker real.** Não há provedor de túnel
selecionado; certificado TLS, logs da borda, URL pública e isolamento HTTPS ainda
não foram verificados. Cada passo operacional espera configuração local e
autorização explícita do operador.

Na auditoria de 29/10/2026: `.env` tinha somente o token Lead Ads presente entre
as credenciais Lead Ads. `LEAD_ADS_ENABLED=false`, App Secret, Verify Token,
versão da API, allowlist e mapping formulário→Página ainda não estavam
configurados. Portanto handshake/ingress e cliente Graph estão fail-closed.
O banco confirmado tinha revisão 0006, integridade `ok`, 1 lead e 1 atividade,
com inbox vazia; esta preparação local não gravou nesse banco.

## Gate 2B — checklist para ação posterior

1. No Meta for Developers, confirmar app e versão Graph suportada; verificar
   produto Webhooks/Páginas, acesso de negócio e permissões Lead Ads vigentes.
2. Com o responsável RCTEC, escolher Página e formulário de teste e verificar
   quem pode acessar seus leads. Conferir acesso ao evento leadgen e inscrição
   da Página; não assumir que o token de Insights serve.
3. Configurar os três segredos separadamente no ambiente/secret manager, nunca
   no código ou chat; confirmar expiração/revogação/renovação documentadas.
4. Aprovar acesso externo apenas ao webhook HTTPS, com log seguro, limites e
   proteção da API privada; túnel/deploy dependem de autorização separada.
5. Informar callback e verify token no painel Meta, completar challenge e
   inscrever Página no evento correto conforme documentação atual.
6. Gerar um lead fictício com ferramenta oficial de teste; conferir inbox
   persistida, executar worker explicitamente e verificar Lead/histórico.
7. Reenviar evento para provar ausência de duplicação; simular falha/reinício
   e conferir retry; executar reconciliação autorizada e comparar IDs/contagens.
8. Confirmar campos personalizados essenciais, política de acesso/retenção e
   logs sem PII. Registrar evidências e só então considerar 2B concluído.

Não solicita tokens/segredos pelo chat. Nenhuma ação dessa lista foi realizada.
