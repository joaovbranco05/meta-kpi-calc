# Roadmap incremental mini-CRM RCTEC

Prioridade definida pelo prompt de 28/10/2026: captação e gestão comercial antes
de novas análises. Um repositório, FastAPI/SQLAlchemy/Alembic preservados. O plano
não autoriza executar todas as fases; cada fase exige contrato e gates próprios.
`PLAN.md`, `PLAN-2.md` e `PRODUCT_REVIEW.md` permanecem históricos: 9D e matrícula
individual não são pré-requisitos automáticos deste roadmap.

| Fase | Dependências | Entregáveis | Critérios objetivos de aceite |
|---|---|---|---|
| 0 — auditoria e preparação | Baseline e branch de trabalho | Inventário A/B/C/D, arquitetura, modelo proposto, plano Lead Ads, scaffold docstring | Concluída; suíte original e 18 operações preservadas antes da Fase1 |
| 1 — modelagem e persistência de leads (concluída localmente) | Fase 0 aprovada; catálogo mínimo de status/campos e identidade do ator definidos | Modelos Lead/LeadActivity, migration aditiva, ingestão idempotente, importador local e API REST mínima | Fundação verificada no baseline228 antes de2A: replay/concorrência, status/histórico, campanha opcional, import e migration; sem auth/UI/deploy/PostgreSQL |
| 2A — integração técnica local (concluída) | Fase1 verificada e contratos mínimos fundamentados em fontes Meta-owned | Cliente GET, webhook assinado, inbox/worker retomável, normalizador, reconciliação/checkpoint e CLI | 283 testes aprovados com mocks e TCP bloqueado; nenhum Graph real/deploy/auth/PostgreSQL |
| 2B — integração real controlada (não executada) | Gate 2B: autorização específica e confirmação da documentação atual, versão, permissões, tokens e fontes antes de qualquer chamada real | App/Página de teste, HTTPS webhook-only, lead fictício e validação operacional | Lead persistido, replay/reconciliação conferidos, segurança e acesso aprovados; não autorizado automaticamente por 2A |
| 3 — interface mini-CRM e identidade | Fases1/2 estabilizadas para ingestão automática; contrato identidade e papéis | Login/sessões, autorização servidor, lista/detalhe/filtros, status/notas/histórico e novos/não atendidos | Operadora executa jornada sem IDs técnicos; acesso negado/expirado/revogado e CSRF testados; endpoints legados e CRM protegidos antes de exposição remota; filtros curso/campanha/data/status e atualização concorrente sem perda; Analytics preservado |
| 4 — deploy e validação operacional | Fases1–3 aprovadas; autorização para migração/deploy/dados reais, política de acesso/retenção | PostgreSQL cloud (Supabase candidato), adaptação por dialeto, TLS/segredos, backup/restore, monitoramento e runbook | Cadeia Alembic e import ensaiados, PK/FK/somas/UTC reconciliados, rollback demonstrável, restore realizado, webhook HTTPS e recuperação monitorados, piloto autorizado com dado controlado e acesso mínimo; sem multiworker com lock local como garantia |
| 5 — Data Analytics | Dados operacionais confiáveis, reconciliação e definições de atribuição/coorte | Consultas SQL, modelo analítico, BI (Tableau/Power BI candidatos), evolução KPI | Fonte/dicionário explícitos; números reconciliam com CRM e agregados legados sem dupla contagem; unknown distinto de zero; nenhum KPI alterado silenciosamente |

A fase 1 usa SQLite local; testes usam dados fictícios. A exportação real foi
usada somente no smoke de importação em banco temporário e os resultados serão
reportados por contagens agregadas, sem valores pessoais. PostgreSQL é fase
futura de produção.
O schema poderá ser ensaiado no dialeto alvo antes de cutover, em tarefa própria.
Uma etapa não é concluída só por documento ou código de saída: persistência,
reprocessamento e comportamento observável precisam ser verificados.

## Próxima ação recomendada — Gate 2B futuro

Gate 2A local foi implementado e sua suíte final passou 283 testes, dois avisos conhecidos.
Não iniciar Fase 3 ou conexão real automaticamente. Antes do 2B obter autorização
para app/Página/formulário de teste, confirmar versão/permissões e token,
publicação HTTPS webhook-only, logs seguros e acesso privado. Executar checklist
com lead fictício, replay, falha/reinício e reconciliação, conforme README e
documento de integração. Não enviar tokens pelo chat.

## Decisões a fechar na fase apropriada

- Fase1: schema e catálogo locais já implementados e verificados; identidade de
  operador continua futura, sem reconstruir alunos ou fabricar usuários.
- Fase2: versão Graph, permissões e app/página/formulário autorizados; janela
  recuperável, payload, orçamento de retries e política de reprocessamento.
- Fase 3: provedor de identidade e papéis; comparar templates servidor no mesmo
  FastAPI com adaptação Streamlit, usando jornada real. Login não é autorização.
- Fase4: provedor PostgreSQL, disponibilidade, retenção/backup, rede e operador
  responsável; nenhuma implantação pública antes dos controles de acesso.
- Fase5: fonte de matrícula/contrato/pagamento e reconciliação com legado, se
  desejados; Lead não constitui matrícula e status não prova receita recebida.

BotConversa, envio de mensagens, Kanban externo e mudanças de campanhas não são
entregas implícitas deste roadmap. Dependem de pedido e autorização próprios.


## Execução 29/10/2026 — separação dos gates 2A/2B

Fase1 foi verificada no código e baseline (228 testes) antes deste incremento;
textos antigos de revisão pendente não representam evidência atual. Gate 2A
implementa infraestrutura técnica local: cliente GET, HMAC, inbox durável,
worker com lease/retry, normalizador e reconciliação/checkpoint usando ingest_lead.
Validação final e revisões constam em STATUS/README após gates.

Gate 2B permanece NÃO EXECUTADO: confirmar versão/permissões/token, configurar
app/Página/formulário, publicar HTTPS webhook-only com proteção privada, gerar
lead fictício e validar replay/reconciliação. Sem autorização automática para
rede, túnel, deploy ou dados reais. O checklist prático está no documento de
integração. Fase 3 auth/UI e fase 4 PostgreSQL continuam futuras.
