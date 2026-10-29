# Modelo de dados CRM e evolução para PostgreSQL

Proposta iniciada na Fase0 e atualizada após a implementação da Fase1.
Mantêm-se Base SQLAlchemy, Alembic e as cinco entidades Analytics existentes.

## Implementado na Fase1

- `Lead.meta_lead_id` é texto obrigatório e UNIQUE. E-mail e telefone não são
  únicos. `campaign_id` é uma FK opcional com `RESTRICT`; os IDs e snapshots
  Meta ficam preservados quando não existe Campaign sincronizada.
- O registro mantém os campos fixos observados na exportação: nome, telefone,
  e-mail, cidade, estado, data Meta, IDs e nomes de campanha/conjunto/anúncio/
  formulário, orgânico, plataforma e `source_status` (exportado como
  `lead_status`). `course` é opcional e não é inferido.
- Timestamps sem fuso no arquivo são interpretados como UTC. Telefones
  numéricos viram texto lexical, sem acrescentar DDD ou alterar dígitos.
- `commercial_status` inicia em `NEW`; o catálogo é `NEW`, `CONTACTED`,
  `INTERESTED`, `ENROLLED`, `NO_RESPONSE`, `LOST`. O `lead_status` da Meta fica
  em `source_status` e não muda o estado interno.
- `LeadActivity` registra importação, mudança de status, nota, tentativa/
  realização de contato e correção de campos de origem. Ator é
  `SYSTEM_IMPORT` ou `LOCAL_OPERATOR`; `actor_id` fica nulo até haver identidade
  real. Mudança de status e atividade são persistidas na mesma transação.
- Replays usam `INSERT ... ON CONFLICT(meta_lead_id) DO NOTHING` em SQLite. A
  primeira ingestão cria uma atividade; replay atualiza somente valores de
  origem presentes e diferentes, preservando status, notas, atribuição,
  histórico e campos locais. Correções registram apenas nomes de campos.
- Migration aditiva `0005_crm_leads` cria as duas tabelas, FKs `RESTRICT`,
  constraints nomeadas e índices. Alembic segue como autoridade do schema.
- O importador detecta CSV, XLSX e SpreadsheetML 2003 por conteúdo; não aceita
  XLS binário OLE nem executa fórmulas. Limites atuais: 20 MiB, 50 mil linhas,
  100 colunas, 10 mil caracteres por célula, 200 entradas e 100 MiB expandidos
  para XLSX. Colunas desconhecidas são rejeitadas para evitar persistir
  perguntas dinâmicas não avaliadas.
- A CLI `python -m meta_kpi_calc.crm.import_cli` é dry-run por padrão; exige
  `--database-url` e só grava com `--commit`. O schema precisa estar migrado.
- A API CRM oferece listagem, detalhe, status e atividades. O router rejeita
  pares remotos, com exceção do `testclient` de testes. Isso não autentica
  usuários nem substitui controles antes de qualquer proxy/exposição remota.

## Referência do modelo e identidade futura

| Entidade | Campos e invariantes propostos | Relações / fase |
|---|---|---|
| Lead | PK interna inteira; `meta_lead_id` textual obrigatório e UNIQUE para origem Meta; page/form IDs; ad/adset/meta_campaign IDs opcionais; contato mínimo; curso; status; responsável; created/updated/received timestamps UTC | `campaign_id` FK interna opcional com RESTRICT; identidade externa preservada mesmo sem campanha local; fase1 |
| LeadActivity | PK, lead FK, tipo, ator estável, data UTC, nota ou status anterior/novo; append-only; tamanho limitado e texto tratado como entrada não confiável | Histórico ligado a Lead; sem delete cascade automático; fase1 |
| User / identidade mapeada | ID interno ou subject estável do provedor + issuer, ativo e papel; dados mínimos | Responsável/ator; desenho identidade fase1, autenticação fase3; não criar sistema de senhas agora |
| WebhookEvent / inbox | Chave única determinística da notificação/submissão, origem, IDs, recebido/em processamento/concluído/falha, tentativas, próximo retry, erro sanitizado e timestamps | Estado técnico separado de LeadActivity; fase2; payload mínimo sem cópia irrestrita de PII |

Lead representa uma submissão de formulário, não uma pessoa única nem uma
matrícula. A mesma pessoa pode submeter dois formulários e originar dois leads.
Telefone/e-mail não são UNIQUE e não autorizam merge destrutivo. Normalize com
regra explícita, sem adivinhar DDD; dados inválidos/ausentes ficam pendentes.
Se futuramente houver entrada manual/não Meta, definir sua chave de origem no
contrato dessa expansão, sem fabricar `meta_lead_id` agora.

Página/formulário são IDs de origem; nomes são snapshots opcionais, nunca
chaves. Não criar catálogos de todos os objetos Meta sem consumidor. A relação
Lead→Campaign pode ser reconciliada depois por `meta_campaign_id` verificável;
não bloquear captura por sincronização de mídia nem inventar atribuição.

Status inicial implementado `NEW`; catálogo vigente da Fase1 está descrito
acima. Mudanças futuras de transições precisam de contrato próprio. Alteração de status/nota cria atividade com
ator e data na mesma transação. Ingestão/replay não apaga notas, responsável ou
status comercial. Edição concorrente deve detectar conflito, por versão ou
condição sobre estado anterior, sem atualização perdida silenciosa.

## Idempotência e transações

UNIQUE no banco é obrigatório; consulta seguida de insert não basta em
concorrência. O serviço recebe Session e trata conflito de unicidade com
rollback/releitura ou mecanismo por dialeto testado. Repetir a mesma submissão
não cria Lead ou atividade inicial adicionais. Testar duas sessões disputando
a mesma chave, falha entre persistência e resposta, rollback e reenvio.

Inbox: confirmar recebimento somente após transação durável. Retomar após crash,
controlar tentativas e evitar duas execuções simultâneas por evento. Duplicação
não equivale a falha comercial. A recuperação paginada deve chamar o mesmo
serviço idempotente do webhook. Não prometer exactly-once distribuído.

## Preservação do Analytics

`Campaign` já tem UNIQUE(meta_campaign_id). Insights são únicos por
campanha/date_start/date_stop; EnrollmentRecord por campanha/data/curso;
CommercialClosure por campanha/data. SyncRun é execução técnica de mídia.
Essas chaves e entidades ficam inalteradas. Não reconstruir pessoas a partir
de contagens, não somar novos leads aos Insights nem derivar pagantes do status
comercial. Futuras matrículas individuais precisam de fonte oficial, identidade
de contrato e corte de reconciliação para impedir dupla contagem com legado.

## Compatibilidade PostgreSQL: parcial, não operacional

Tipos Integer/String/Text/Date/DateTime/Numeric/JSON, FKs e constraints nomeadas
são uma base reaproveitável. QA compilou DDL PostgreSQL das cinco tabelas e três
índices ORM com sucesso; isso valida sintaxe gerada, não banco, dados ou cadeia
de migrations. SQLAlchemy documenta suporte por dialeto
([PostgreSQL](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html)).

Bloqueios concretos atuais:

- `core/config.py` rejeita qualquer driver diferente de `sqlite` e reconstrói
  URLs SQLite; paths demo/real dependem de arquivo.
- `db/session.py` usa `check_same_thread=False`, cria diretório e executa
  foreign_keys/busy_timeout/journal_mode WAL: exclusivos do SQLite.
- `alembic/env.py` executa PRAGMA incondicionalmente. Alembic usa a mesma
  configuração; sobrescrever apenas alembic.ini não resolve.
- Não há driver PostgreSQL nas dependências nem CI nesse banco. `0003` usa
  batch_alter_table; validar sua execução no dialeto alvo, sem presumir
  incompatibilidade automática ([Alembic batch](https://alembic.sqlalchemy.org/en/latest/batch.html)).

Riscos de dados: SQLite aceita coerções e não garante precision/collation/length
como PostgreSQL. Verificar Numeric/Decimal sem float, JSON serializável e
semântica de NULL, enums não nativos/CHECK, trim/case/acento, datas e UTC.
DateTime(timezone=True) pode voltar naive no SQLite; interpretar timestamps só
com origem/fuso comprovados. Preservar PK/FK e avançar sequences após importar
IDs explícitos. Comparar contagens, chaves naturais, órfãos, somas monetárias e
amostras fictícias; validar unique, índices e RESTRICT no alvo.

## Estratégia futura de migração

1. Fase1: schema CRM aditivo em SQLite temporário; upgrade/downgrade/check e
   regressão completa. Sem editar revisões históricas ou converter agregados.
2. Fase4: selecionar provedor, driver e versão suportados; adaptar fronteiras
   de Settings/engine/Alembic por dialeto, sem mudar fórmulas. Ensaiar toda
   cadeia desde banco vazio e a partir de cópia controlada.
3. Fazer backup consistente e provar restore; ensaiar export/import com
   preservação de IDs, UTC e Numeric; reconciliar domínios e sequences.
4. Definir janela de escrita suspensa, critérios de abortar, cópia final,
   verificação e rollback para backup anterior sem divergência silenciosa.
5. Autorizar cutover/deploy separadamente. Supabase gerenciado não torna a API
   segura automaticamente; definir rede, privilégios, TLS, pool e backups.

Nenhum banco real, arquivo SQLite operacional ou credencial foi modificado.

## Privacidade e controle de acesso

Antes de dados reais, definir finalidade/base aplicável com responsável RCTEC,
campos mínimos, acesso por papel, responsável por atendimento e procedimento
para consulta/correção/eliminação. Não supor que envio de formulário autoriza
qualquer uso posterior. Definir prazo de retenção por finalidade, descarte e
tratamento de backups, sem prazo arbitrário. Histórico append-only não significa
retenção eterna: correções ficam rastreáveis e exclusão/anonimização segue
política aprovada, incluindo notas de texto livre.

Criptografia em trânsito e proteção de backups, privilégios mínimos, auditoria
de acesso e proibição de PII/raw em logs são requisitos de operação futura.
Redação atual de token não protege telefone/e-mail/nome. Usar somente fixtures
fictícias. A orientação se apoia nos materiais oficiais da
[ANPD para agentes de pequeno porte](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/processo-guia-orientativo-sobre-seguranca-da-informacao-para-agentes-de-tratamento-de-pequeno-porte.pdf)
e nos [direitos do titular](https://www.gov.br/anpd/pt-br/assuntos/titular-de-dados);
não constitui certificação de conformidade ou parecer jurídico.


## Implementação técnica local 2A (29/10/2026)

Migration aditiva `0006_lead_ads_inbox` acrescenta `Lead.meta_page_id` nullable
com resposta CRM aditiva, preserva linhas0005 e cria metadata sem payload/PII:

- `webhook_events`: chave única meta:leadgen:page:lead, IDs origem, source WEBHOOK,
  status CHECK, attempts/unmapped_fields >=0, due/received/updated/completed UTC,
  lease_token/expiry e error_code fixo. CHECK exige lease apenas PROCESSING.
  Índices due(status,next_attempt_at) e lease_expires_at.
- `lead_reconciliation_states`: unique page/form, completed_until, last_run_at,
  last_success_at, resultado CHECK, processed_count/unmapped_fields>=0,
  lease_token/expiry e erro fixo; lease só PROCESSING.

Claim/finish usam UPDATE condicional com fence, sessão explícita curta e sem
HTTP em transação. Checkpoint só após todas as páginas. Detalhes, limites
SQLite e regras de recuperação em META_LEAD_ADS_INTEGRATION. Sem alteração de
enums/atores, modelos financeiros, schema Analytics ou migration histórica.
