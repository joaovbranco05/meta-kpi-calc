---
name: customer-pilot-readiness
description: Preparar um piloto assistido do Meta KPI Calculator com onboarding, reconciliação, backup e critérios de liberação; usar antes de entregar o sistema ao cliente.
---

# Customer Pilot Readiness

## Objetivo

Preparar uma entrega verificável ao cliente sem alterar dados comerciais nem
executar integrações externas.

## Roteiro

1. Ler `docs/STATUS.md`, `docs/DECISIONS.md`, `docs/ACCEPTANCE.md`,
   `docs/OPERATIONS.md`, `docs/PLAN-2.md` e `docs/PRODUCT_REVIEW.md`.
2. Definir o recorte curto de reconciliação, a fonte comercial de comparação e
   os operadores do piloto.
3. Preparar um roteiro de onboarding que cubra filtros, lançamentos, edição,
   interpretação de cobertura, consulta dos KPIs e exportação.
4. Ensaiar backup, restauração, abertura e encerramento conforme a operação
   documentada, registrando resultado, pendência e responsável.
5. Liberar o piloto apenas quando a jornada assistida e a reconciliação do
   recorte escolhido estiverem concluídas e as pendências forem entendidas.

## Limites

- Não executar Meta, BotConversa, sincronização real, envio de mensagem ou
  alteração de campanhas durante a preparação.
- Não substituir `meta-kpi-calculator-dev` ou `botconversa-meta-automacao`:
  esta skill coordena a prontidão da entrega, não a implementação nem a
  automação comercial.
- Manter dados pessoais e credenciais fora de roteiros, relatórios e registros
  de validação.
