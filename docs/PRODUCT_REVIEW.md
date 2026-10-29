# Scan de produto — do MVP à operação do cliente

Data de referência: 10/09/2026. Estado: diagnóstico e proposta; não altera os
contratos aprovados em DECISIONS, STATUS ou ACCEPTANCE.

## Parecer

A base técnica oferece cálculo, persistência, API e isolamento de demonstração.
A experiência atual exige que o operador conheça IDs, estrutura do banco e
semântica dos agregados. O principal investimento deve ser tornar o lançamento
comercial confiável e os resultados interpretáveis. Aumentar a quantidade de
indicadores antes disso amplia a chance de decisões baseadas em dados incompletos.

O cadastro atual **não representa a matrícula de um aluno**: representa um
resumo diário por campanha e curso. Essa escolha foi deliberada no MVP. Uma
tela mais bonita não resolve o acompanhamento individual de pagamentos,
cancelamentos e atribuição que esse modelo não registra.

## Escopo e evidências

Foram lidos os cinco documentos existentes em docs, README, as duas skills
indicadas, referências de dados/KPIs e arquitetura da skill BotConversa,
frontend, modelos, schemas, rotas, serviços e testes relevantes. Três agentes
analisaram matrículas, KPIs e operação e trocaram os achados de domínio.

Validação da suíte existente: `.venv/bin/pytest -q` — **191 aprovados**, dois
avisos de depreciação FastAPI/Starlette. Isso comprova o contrato técnico
testado; não comprova usabilidade com o cliente. A cobertura de frontend
existente concentra-se em helpers e propagação de filtros.

Os problemas foram identificados por leitura do código. Não houve reprodução
completa das jornadas na interface nem teste de usabilidade com o cliente.

Não houve conexão Meta/BotConversa, leitura de dados pessoais, alteração de
banco real ou implementação de funcionalidades. As referências abaixo usam
linhas do código existente no momento do scan.

## Problemas prioritários

P0: corrigir antes de uso operacional. P1: incluir na primeira entrega de
produto. P2: evolução após validar a rotina.

| Prioridade | Evidência no repositório | Consequência prática | Encaminhamento |
|---|---|---|---|
| P0 | `frontend/app.py:145–157`; `api/routes/rest.py:399–403` | Corrigir exige ID e redigitação; PUT substitui tudo e a tela envia `notes` e `contribution_margin` nulos. Pode apagar conteúdo existente. | Selecionar linha, carregar valores atuais, preservar campos não editados, mostrar alterações e atualizar a tela ao salvar. |
| P0 | `services/report_filters.py:33–46`; `services/kpi_service.py:206–219` | O período de vigência da campanha também restringe receitas. Recebimento posterior ao encerramento pode desaparecer do resumo. | Definir filtro por data do evento comercial, independentemente da vigência da campanha; manter dashboard e exportação consistentes. |
| P0 | `frontend/app.py:74–86,131–143` | Apenas os primeiros 100 registros/campanhas são carregados; a interseção é feita depois da paginação. Pode haver lista vazia ou incompleta apesar de existirem resultados. | Aplicar todo o escopo na API antes de paginar, exibir total e navegação. |
| P0 | `services/kpi_service.py:225–238,123–127` | Ausência de lançamento comercial vira zero. Com investimento, o ROI publicitário recebido pode aparecer como −100% sem fechamento informado. | Separar “zero confirmado” de “ainda não informado”; informar cobertura e pendências. Não inferir completude da simples existência de uma linha. |
| P1 | `db/models.py:185–245`; `frontend/app.py:144–159` | “Salvar matrícula” promete cadastro individual, mas salva contagens e receitas agregadas. | Renomear para “Lançamento diário” enquanto esse for o modelo; decidir fonte da matrícula individual antes de evoluir schema. |
| P1 | `frontend/app.py:53–71` | Consulta depende de ID interno, nome exato do curso e status técnicos. | Seletores por nome, opções dependentes, atalhos de período e botão “Aplicar filtros”. |
| P1 | `frontend/app.py:14–19,89–103`; `api/schemas.py:178–197` | KPIs são chaves técnicas e valores sem unidade consistente; Decimal serializado em JSON chega como string. | Catálogo de apresentação com título, unidade, definição e motivo de indisponibilidade. |
| P1 | `frontend/app.py:106–125`; `api/routes/rest.py:277–312` | “Campanhas e comparação” mostra cadastro de campanhas, sem métricas de comparação. | Tabela por campanha com investimento, leads, contratos, pagantes, CAC e receita, agregados no backend. |
| P1 | `frontend/app.py:42–50,164–176`; `api/routes/rest.py:249–274` | 409, 422, indisponibilidade e timeout viram falha genérica. Sync síncrono pode terminar depois do timeout de 10 s da tela. | Mensagens por código; acompanhamento da execução para distinguir processamento, falha e conclusão. |
| P1 | `frontend/app.py:166,186`; `api/routes/rest.py:225–245` | Abrir/reexecutar o painel consulta duas vezes o diagnóstico que acessa a Meta quando configurada. | Usar saúde local para estado do painel e botão explícito para testar conexão externa. |
| P1 | `frontend/app.py:171–172`; `api/schemas.py:34` | Sync envia só datas e usa campanhas ativas por padrão; os demais filtros visíveis não definem esse escopo. | Separar seleção de relatório do escopo de sincronização; esclarecer inclusão de campanhas pausadas e encerradas no histórico. |
| P1 | `services/demo_seed.py:17`; `frontend/app.py:54–58` | Demo cobre 25–31/08/2026 e a tela abre últimos sete dias; apresentação posterior abre sem desempenho. | Demo deve abrir no intervalo fictício disponível e identificá-lo claramente. |
| P1 | `api/routes/rest.py:521`; `frontend/app.py` | Exportação existe na API, mas não há botão no painel. | Baixar relatório com o mesmo recorte e nomes/unidades legíveis. |

Os caminhos abreviados `api/`, `db/` e `services/` pertencem a
`src/meta_kpi_calc/`.

## Jornada de lançamento recomendada

### Primeiro incremento: tornar seguro o resumo diário

1. Abrir **Lançamentos diários** e escolher **Novo lançamento** ou **Editar**.
2. Selecionar marca e campanha pelo nome, com identificação adicional quando
   nomes coincidirem. IDs continuam preservados internamente.
3. Escolher data e curso. Sugerir curso classificado na campanha, permitindo
   divergência explícita. Não excluir campanhas antigas necessárias ao lançamento.
4. Informar contagens do dia e receitas com formato brasileiro. Explicar que
   valores são totais do recorte, não valores por aluno ou acumulados do mês.
5. Se campanha/data/curso já existir, oferecer abrir o lançamento existente.
   Não somar nem substituir silenciosamente.
6. Revisar um resumo legível e salvar. Exibir o registro persistido e renovar
   lista e indicadores; se ficar fora do filtro atual, oferecer vê-lo.

Na edição, todos os campos atuais devem estar carregados. Erro conserva o que
foi digitado. Valores como `1.234,56` precisam de conversão explícita para
decimal; entradas ambíguas devem ser recusadas com orientação.

Este incremento reduz erro de operação, mas continua sem identificar quem
pagou, se a mesma pessoa já foi contada ou a qual contrato pertence o cancelamento.

### Evolução: registrar matrícula e eventos, se o operador trabalhar por aluno

Fluxo de produto proposto:

**Localizar aluno/lead ou referência de contrato → confirmar curso e origem →
registrar contrato → registrar recebimentos/cancelamento na mesma matrícula.**

- Buscar por referência já usada na operação; nome/telefone apenas quando
  houver necessidade e fonte definida. Não pedir novamente dados já existentes.
- Herdar campanha e IDs de origem quando houver vínculo verificável. Atribuição
  manual registra operador, data e evidência. Permitir origem desconhecida ou
  não Meta em vez de forçar uma campanha falsa.
- Contrato tem identificador estável e data própria; recebimento tem data e
  valor próprios. Uma segunda parcela aumenta receita, mas não aumenta novamente
  matrículas pagantes. Cancelamento e eventual estorno são eventos distintos.
- Definir com o cliente o que torna uma matrícula “pagante”: primeiro pagamento
  positivo, pagamento mínimo ou outro critério comercial explícito.
- Contagens passam a ser derivadas dos eventos; o operador não redigita totais.
- Permitir correção rastreável e prevenir duplicação/reenvio. Telefone sozinho
  não identifica unicamente uma matrícula: uma pessoa pode fazer mais de um curso.

Se já existe sistema ou planilha confiável de matrículas, priorizar sua entrada
e conciliação, evitando cadastro duplicado. BotConversa permanece responsável
pelo atendimento; não há motivo para construir outro Kanban neste painel.
Gatilhos e campos disponíveis no Integrador ainda precisam ser verificados.

Migração: registros agregados antigos não permitem reconstruir alunos. Devem
permanecer identificados como histórico consolidado. Fixar recorte de transição
e regra de reconciliação para que importação individual não some novamente as
mesmas matrículas ou receitas.
Recebimentos futuros de contratos legados precisam permanecer no consolidado
ou ser conciliados com uma referência individual, sem recriar contratos já
contabilizados no histórico.

## Consulta e apresentação dos resultados

### Tela inicial orientada a perguntas

Exibir período, marca, campanha selecionada, última atualização e cobertura
comercial antes dos indicadores. Disponibilizar “Este mês”, “Mês anterior”,
“Últimos 7 dias” e intervalo personalizado. “Todos” deve ter texto explícito.
Status deve indicar que é a situação atual conhecida da campanha, não seu
status histórico durante todo o período consultado.

| Pergunta do cliente | Exibição principal | Detalhamento |
|---|---|---|
| Quanto investimos? | Investimento | Diário e por campanha |
| Quantos resultados comerciais tivemos? | Contratadas e pagantes | Cancelamentos e origem dos lançamentos |
| Quanto custou conseguir um pagante? | CAC financeiro | Fórmula e completude do lançamento comercial |
| Quanto entrou? | Receita recebida | Receita prevista separada e datas consideradas |
| Onde precisamos agir? | Pendências de dados e comparação entre campanhas | Registro/campanha que exige revisão |

Organizar detalhes em mídia (CTR, CPC, CPM, CPL), comercial (qualificação e
conversões) e financeiro (CAC, receitas, ROAS). Usar `%`, `R$` e `x` conforme
o indicador. Receita sobre investimento não é lucro; o ROI atual desconta
somente mídia e deve manter esse significado explícito.

Avisos devem explicar o que falta e oferecer ação. Exemplo: “Há dias sem
medição de qualificados; CPQL indisponível”. O aviso de que alcance/frequência
não podem ser somados deve ser informativo, sem parecer erro de cadastro.

Comparação de campanhas deve usar o mesmo período, mostrar volume e qualidade
dos dados e permitir ordenação. Comparação com período anterior exige intervalo
equivalente e explicitação de dias parciais. Não adicionar selo de campanha
“boa/ruim” ou recomendação automática de orçamento sem critério do negócio.

### Comparação resumida e comparação detalhada

A tabela resumida da 9B permite uma leitura rápida por campanha com os
principais totais comerciais e financeiros. A 9C acrescenta uma aba própria em
que o usuário seleciona duas ou mais campanhas e compara todos os totais e KPIs
do catálogo vigente, no mesmo período e com os mesmos filtros globais. A matriz
deve reconciliar cada campanha com seu resumo e com uma exportação específica
da seleção, além de expor cobertura, avisos, última atualização, dias parciais e
o motivo de qualquer valor não calculável. Essa ampliação não muda fórmulas,
não cria ranking ou recomendação e não consulta a Meta implicitamente.

### Definições que precisam acompanhar o produto

- **Qualificação:** o código e DECISIONS usam qualificados ÷ leads; a referência
  da skill BotConversa usa qualificados ÷ respondidos. Preservar o contrato atual
  e nomear “Qualificação dos leads”. Só introduzir “Qualificação entre respondidos”
  quando esse denominador for medido. Não trocar fórmula silenciosamente.
- **Fonte dos qualificados:** há persistência/leitura, mas não há fluxo operacional
  de entrada na tela/API atual. Até existir fonte, manter indisponibilidade visível.
- **Data versus coorte:** gasto, lead, contrato e pagamento no mesmo intervalo
  não provam que são as mesmas pessoas. Os índices atuais são razões entre
  totais do período. Não apresentá-los como conversão de uma coorte rastreada.
- **Curso:** o filtro atual usa curso da campanha; o registro comercial pode
  conter outro curso. Oferecer visão comercial por curso vendido separadamente;
  não atribuir gasto/CAC por curso sem regra de atribuição ou rateio definida.
- **Receita prevista:** formalizar se representa valor total do contrato ou
  previsão de recebimento no período. Não usar o mesmo rótulo para ambas.
- **Cancelamentos e pagantes:** no consolidado podem pertencer a contratos de
  outro período. Preservar avisos e valores; não impor percentuais máximos de 100%.
- **Moeda e fuso:** o painel formata BRL; antes da operação real, confirmar que
  moeda da conta e calendário comercial correspondem à apresentação.

## Sequência de entrega

| Incremento proposto | Resultado observável | Dependências |
|---|---|---|
| 9A — Cadastro seguro e consulta acessível | Operador cria/edita lançamento sem IDs, perda de campos ou registros ocultos pela paginação; filtros por nome; demo utilizável. | Preserva resumo diário; revisão dos filtros comerciais e mensagens. |
| 9B — Resultados compreensíveis | Unidades, definições, cobertura comercial, comparação por campanha e download no painel. | Contrato de fechamento/completude; sem inventar zero para dado desconhecido. |
| 9C — Comparação detalhada de campanhas | Usuário seleciona duas ou mais campanhas e compara todos os totais e KPIs existentes em uma matriz reconciliável e exportável. | 9B concluída; mesmo recorte, catálogo e semântica do resumo; cobertura e indisponibilidade explícitas. |
| 10 — Fonte comercial e matrícula individual | Contrato, pagamento e cancelamento ligados; origem rastreável; sem dupla contagem. | Confirmar rotina do cliente, fonte oficial, definição de pagante e transição do histórico. |
| 11 — Piloto assistido | Cliente executa rotina completa e confere números com a fonte original. | Conexão real validada separadamente, atualização e recuperação operacionais. |

Estes números identificam propostas e não liberam automaticamente etapas no
STATUS. Não é necessário trocar Streamlit ou SQLite para executar os primeiros
incrementos. Acesso remoto ou uso simultâneo por equipe exigem contrato de
implantação, identidade, permissões e concorrência próprios; o MVP foi desenhado
para operação local.

9A e 9B compõem o mínimo funcional aprovado para o piloto: 9A isoladamente não
libera operação com indicadores que tratem dados comerciais ausentes como zero.
A 9C é a próxima evolução planejada, antes da 10, e não bloqueia a preparação do
piloto já liberada pelas etapas 9A e 9B.

## Aceite prático da entrega

1. Operador encontra campanha pelo nome e registra um lançamento sem consultar
   documentação técnica. Medir no piloto; meta sugerida: até um minuto após
   familiarização, sem tratar essa meta como resultado já observado.
2. Editar um valor preserva os demais, inclusive observações; sucesso mostra
   valores persistidos. Duplicidade e valor inválido têm instrução de correção.
3. Conjunto com mais de 100 campanhas/registros continua navegável; tabela,
   resumo e exportação reconciliam o mesmo escopo.
4. Recebimento posterior ao encerramento da campanha aparece no período do
   recebimento, conforme a regra comercial escolhida.
5. Sem fechamento comercial, o usuário vê pendência, não conclusão de ausência
   de vendas. Zero confirmado, dado ausente e divisão por zero são distinguíveis.
6. No modelo individual, duas parcelas não duplicam pagantes; cancelamento não
   vira estorno automaticamente; reenvio/importação não duplica receita.
7. Sincronização lenta informa estado real; falha não pede repetição às cegas.
   Última carga e dia parcial ficam visíveis. Modo demo não oferece sync real.
8. Relatório baixado usa nomes/unidades compreensíveis e reproduz os números da
   tela. Usuário consegue explicar investimento, CAC e receita recebida.
9. Na comparação detalhada, o usuário seleciona duas ou mais campanhas, cada
   coluna reconcilia com o resumo da respectiva campanha e a exportação reproduz
   exatamente a mesma seleção e o mesmo recorte.
10. Instalação, abertura, encerramento e restauração de backup são ensaiados;
   primeira conexão real usa janela curta e conciliação com a fonte.

Pendente de descoberta: quem lança matrículas, onde o registro nasce e se já
existe planilha/sistema oficial. Essa resposta define se a próxima evolução
central será formulário individual, consolidação diária ou importação.
