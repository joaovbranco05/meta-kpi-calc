# Plano de implementação — evolução para operação real

## Resumo

Evoluir o MVP em cinco incrementos, mantendo FastAPI como fonte de verdade e Streamlit como interface:

1. Corrigir segurança e clareza do lançamento atual.
2. Tornar os KPIs interpretáveis e reconciliáveis.
3. Permitir comparação detalhada entre duas ou mais campanhas no mesmo recorte.
4. Organizar as fronteiras do código antes de ampliar o domínio comercial.
5. Substituir gradualmente o resumo agregado por matrícula individual com eventos financeiros.

A rotina escolhida para o piloto será **matrícula individual**. O fechamento diário existente será preservado como histórico legado e como possível mecanismo de conferência/importação.

## Incremento 9A — base operacional segura

Alterar backend e Streamlit para:

- Trocar “Salvar matrícula” por “Novo lançamento” ou “Editar lançamento” até a entrada individual estar disponível.
- Selecionar campanha por nome, marca e status, mantendo o ID interno oculto.
- Carregar todos os valores antes de editar e preservar `notes` e `contribution_margin`.
- Detectar duplicidade campanha/data/curso e oferecer abertura do registro existente.
- Validar moeda brasileira, curso, datas e campos obrigatórios antes da requisição.
- Aplicar filtros no backend antes da paginação; exibir total e navegação.
- Corrigir o filtro de relatórios para que a data do evento comercial não dependa da vigência da campanha.
- Diferenciar dado ausente, zero confirmado e fechamento parcial.
- Mapear erros 404, 409, 422, 502 e timeout para mensagens acionáveis.
- Mostrar o resultado persistido após salvar e atualizar a lista e os KPIs.

Interfaces principais:

- Manter POST/PUT compatíveis durante a transição.
- Acrescentar metadado de cobertura comercial ao resumo, distinguindo `unknown`, `partial` e `complete`.
- Preservar o contrato atual de KPIs; não trocar silenciosamente a fórmula de qualificação.

## Incremento 9B — painel orientado a decisão

Reorganizar a primeira tela em torno das perguntas do cliente:

- Quanto investimos?
- Quantos contratos e pagantes tivemos?
- Quanto custou cada pagante?
- Quanto entrou?
- O que precisa ser revisado?

Implementar:

- Períodos rápidos: este mês, mês anterior, últimos sete dias e personalizado.
- Resumo textual do recorte ativo, última atualização e dias parciais.
- KPIs agrupados em mídia, comercial e financeiro.
- Catálogo de apresentação com nome, unidade, fórmula e interpretação.
- Formatação consistente de `R$`, `%`, `x` e valores não calculáveis.
- Tabela de comparação por campanha com investimento, leads, contratos, pagantes, CAC e receita.
- Separação visual entre informação, pendência e inconsistência.
- Botão de exportação usando exatamente o mesmo recorte da tela.
- Demo abrindo automaticamente no intervalo existente do seed.
- Estado de sincronização visível: executando, concluída, falhou ou não confirmada.
- Diagnóstico Meta somente mediante ação explícita do usuário; abrir ou filtrar o painel não deve consultar a Meta novamente.

O painel não deve apresentar razões de período como conversão comprovada de uma mesma coorte.

## Incremento 9C — comparação detalhada entre campanhas

Criar uma aba própria para selecionar duas ou mais campanhas e comparar todos
os totais e KPIs já disponíveis no produto. A aba deve herdar os filtros globais
compatíveis e aplicar o mesmo período a todas as campanhas selecionadas. Nessa
aba, a multisseleção substitui o filtro global singular de campanha; período,
marca, curso, status e os demais filtros compatíveis permanecem comuns a todas
as campanhas comparadas.

Apresentar uma matriz com indicadores nas linhas e campanhas nas colunas,
agrupada em mídia, comercial e financeiro. Cada coluna deve mostrar os mesmos
valores que o resumo da respectiva campanha no mesmo recorte. A identificação
visível usa o nome da campanha e informação adicional quando houver homônimos;
IDs internos e IDs externos estáveis preservam a identidade sem exigir que o
usuário os conheça.

A comparação deve incluir:

- Todos os totais e KPIs do catálogo vigente, sem criar fórmula ou indicador novo.
- Formatação consistente de `R$`, `%`, `x`, contagens e valores não calculáveis,
  com o motivo da indisponibilidade.
- Cobertura comercial, avisos, última atualização de mídia e indicação de dias
  parciais para cada campanha.
- Razões entre totais do período identificadas como tal, sem afirmar conversão
  de coorte.
- Status descrito como situação atual conhecida da campanha, não como histórico
  de todo o intervalo.
- Curso tratado como classificação da campanha. Não ratear investimento, CAC ou
  outros indicadores por curso sem regra de atribuição aprovada.
- Receita recebida, receita prevista e margem de contribuição separadas. ROAS
  não representa lucro; o ROI vigente desconta somente o investimento em mídia.
- Exportação específica das campanhas selecionadas e do mesmo recorte. Alterar
  qualquer filtro global ou a seleção de campanhas invalida o download anterior.

Limites do incremento:

- Não criar migration, matrícula individual, dado pessoal ou integração nova.
- Não consultar Meta ou BotConversa ao abrir, filtrar ou comparar; qualquer
  diagnóstico externo continua dependendo de ação explícita.
- Não adicionar KPI, scoring, ranking, recomendação automática, selo de
  campanha boa/ruim ou gráfico avançado.
- Não executar I/O externo para montar a comparação; usar os dados já
  persistidos e os contratos existentes de resumo e exportação.

## Incremento 9D — organização estrutural antes da matrícula individual

Executar esta etapa após a conclusão e estabilização da 9C e antes de iniciar a
etapa 10. O objetivo é reduzir a concentração de responsabilidades em
`api/routes/rest.py` e `frontend/app.py`, preservando integralmente o
comportamento atual.

O padrão adotado será **MVC com service layer**, de forma pragmática:

- rotas FastAPI são controllers: recebem HTTP, validam o contrato e delegam;
- Streamlit contém as views: apresenta dados, coleta a interação e consome REST;
- entidades SQLAlchemy e schemas Pydantic continuam representando os modelos de
  persistência e contrato;
- serviços concentram os casos de uso e regras de negócio, sem lógica comercial
  relevante nas rotas ou nas telas.

Não transformar este projeto em Clean Architecture, microserviços, DDD formal
ou uma hierarquia de abstrações. O propósito é deixar as responsabilidades
explícitas e preparar a entrada de contratos, pagamentos e eventos da etapa 10.

### Backend

- Substituir o arquivo único `api/routes/rest.py` por módulos por contexto:
  `meta.py`, `campaigns.py`, `enrollments.py`, `dashboard.py`, `comparison.py`
  e `exports.py`. Cada rota deverá permanecer no mesmo caminho, usar os mesmos
  métodos HTTP, schemas, status e envelopes públicos de erro.
- Manter `api/app.py` como composition root: cria dependências, registra routers
  e controla lifecycle; não deslocar essa responsabilidade para os routers.
- Extrair das rotas somente operações transacionais de negócio já existentes —
  classificação de campanha, lançamentos diários e fechamento comercial — para
  serviços nomeados pelo contexto. Consultas de KPI e relatório devem continuar
  nos serviços atuais enquanto já forem coesas.
- Manter SQLAlchemy `Session` explícita nos serviços nesta etapa. Não criar
  repository genérico, Unit of Work, interfaces/Protocols ou camada CRUD.
- Preservar `MetaClient` como adaptador exclusivo da Meta e `SyncService` como
  dono da sincronização; 9D não cria integração com BotConversa.

### Frontend

- Reduzir `frontend/app.py` ao bootstrap do Streamlit, composição das abas e
  aplicação do recorte global.
- Mover o cliente HTTP e o tratamento comum de respostas para um módulo próprio;
  mover formatação e conversão de valores para helpers; separar cada área da UI
  em módulos de view: visão geral, campanhas, comparação, lançamentos,
  sincronização e exportação.
- Preservar `API_BASE_URL` como única fronteira de dados do painel. Views não
  podem importar SQLite, sessões SQLAlchemy, serviços internos ou `MetaClient`.
- Manter os nomes de estado do Streamlit e a jornada do operador quando eles
  já forem cobertos por testes; a etapa não redesenha telas nem altera textos de
  produto sem necessidade funcional.

### Sequência de execução

1. Criar testes de contrato adicionais apenas onde a cobertura atual não fixar
   path, método, status ou envelope de erro de uma rota que será movida.
2. Mover routers por contexto sem alteração de comportamento, validando a suíte
   após cada grupo coeso.
3. Extrair os casos de uso transacionais das rotas, mantendo as transações e
   regras de conflito atuais.
4. Mover helpers e views do Streamlit sem alterar os endpoints consumidos, os
   filtros aplicados ou o estado observável da jornada.
5. Consolidar a comparação detalhada da 9C no módulo próprio e confirmar que
   tela, resumo e exportação continuam reconciliados.

### Limites e decisões adiadas

- Não criar migration nem alterar entidades, constraints, fórmulas de KPI,
  cálculos, filtros ou contratos REST públicos.
- Não migrar SQLite para PostgreSQL nesta etapa. A decisão será reavaliada após
  a estabilização do modelo individual e de eventos da etapa 10, antes de uma
  operação multiusuário, em servidor ou com integrações comerciais reais.
- Não adicionar autenticação, filas, scheduler externo, integração Meta real,
  BotConversa, upload, gráficos ou novos indicadores.
- Não combinar refatoração estrutural com a modelagem de contratos, pagamentos,
  cancelamentos ou estornos da etapa 10.

### Critérios de aceite

- Toda a suíte existente permanece aprovada; novos testes cobrem somente as
  lacunas necessárias para proteger contratos movidos.
- OpenAPI, paths, métodos, bodies, respostas, status e códigos de erro das
  rotas existentes permanecem compatíveis.
- O painel mantém o mesmo recorte, comportamento de filtros, jornada de edição,
  invalidação de exportação e ausência de consulta Meta implícita.
- `frontend/` continua consumindo exclusivamente HTTP/REST; nenhum módulo de
  view importa banco, serviços internos ou cliente Meta.
- Não há alteração de schema/Alembic nem acesso externo adicional. O modo demo
  continua iniciando sem credenciais.
- A revisão final identifica controllers finos, views separadas e serviços com
  responsabilidades de negócio coesas, sem introduzir camadas genéricas.

## Incremento 10 — matrícula individual e eventos

Criar um modelo individual com:

- Identificador estável da matrícula/contrato.
- Referência opcional ao lead e aos IDs externos da Meta.
- Curso, data do contrato e origem da atribuição.
- Valor previsto do contrato.
- Estado da matrícula.
- Registro de quem atribuiu manualmente a origem e qual evidência foi usada.

Criar eventos separados para:

- Primeiro pagamento.
- Pagamentos posteriores.
- Cancelamento.
- Estorno ou reembolso, caso o negócio precise desse controle.

Regras:

- Matrículas pagantes serão derivadas conforme definição aprovada pelo cliente.
- Segunda parcela aumenta receita, mas não aumenta novamente a contagem de matrículas pagantes.
- Cancelamento não será convertido automaticamente em estorno.
- Reenvio ou importação idempotente não poderá duplicar contrato ou evento.
- Campanha desconhecida será permitida como pendência; o sistema não inventará atribuição.
- Totais agregados antigos permanecerão identificados como histórico consolidado.
- Recebimentos futuros de contratos legados serão conciliados sem recriar contratos e duplicar valores.

Os KPIs comerciais passarão a indicar se usam eventos do período ou uma coorte. Nenhuma regra de rateio de investimento por curso será criada sem decisão explícita.

## Testes e gates

Adicionar testes de backend e jornada para:

- Criar, editar e duplicar lançamento.
- Preservar campos não editados.
- Aceitar `1.234,56` como `Decimal("1234.56")`.
- Manter o formulário preenchido após erro.
- Encontrar o registro na posição 101 ou posterior.
- Exibir recebimento posterior ao encerramento da campanha.
- Diferenciar zero confirmado de dado ausente.
- Reconciliar tela, resumo e exportação.
- Exigir a seleção de pelo menos duas campanhas na comparação detalhada e
  orientar o usuário quando houver menos de duas.
- Exibir todos os indicadores do catálogo na matriz, com filtros globais e o
  mesmo período aplicados a todas as campanhas selecionadas.
- Reconciliar cada coluna da comparação detalhada com o resumo da campanha e a
  exportação específica da seleção.
- Cobrir, por campanha, dado ausente, fechamento parcial, zero confirmado,
  valor não calculável e respectivo motivo.
- Invalidar a exportação da comparação quando mudar o recorte ou a seleção de
  campanhas.
- Confirmar que abrir, filtrar e comparar não consulta a Meta implicitamente.
- Preservar todos os contratos REST e jornadas cobertos antes da refatoração 9D.
- Confirmar que o painel pós-9D não importa persistência, serviços internos ou
  clientes de integração.
- Exibir mensagens específicas para erros conhecidos.
- Demonstrar estado correto de sincronização lenta.
- Registrar contrato, primeira parcela, segunda parcela, cancelamento e estorno sem dupla contagem.
- Repetir importação sem duplicar eventos.
- Manter dados legados fora da contagem individual duplicada.

Gate do piloto:

- 9A e 9B precisam estar concluídos; 9A isoladamente não libera operação.
- Um operador deve completar a jornada sem conhecer IDs internos.
- O cliente deve conseguir explicar investimento, CAC financeiro, receita recebida e pendências.
- Os números devem ser conferidos contra a fonte comercial original em uma janela curta.
- A suíte existente deve continuar passando; a última execução registrada foi de 208 testes aprovados.

## Atualização das skills do projeto

Na execução, revisar:

- `meta-kpi-calc/.agents/skills/meta-kpi-calculator-dev/SKILL.md`: incluir etapas 9A, 9B, 9C, 9D e 10, exigir testes de jornada Streamlit, cobertura comercial e reconciliação com fonte de matrícula.
- `botconversa-meta-automacao/SKILL.md`: acrescentar contrato de matrícula individual, eventos de pagamento/cancelamento, conciliação de legados e regra de não duplicação.

Proponho uma nova skill opcional:

`customer-pilot-readiness`

Responsabilidade: preparar e validar a entrega com o cliente, cobrindo roteiro de onboarding, teste assistido, reconciliação de números, critérios de confiança, registro de pendências, backup/restauração e decisão de liberação para uso real. Ela não deverá executar Meta ou BotConversa automaticamente e não substituirá as skills de implementação ou automação.
