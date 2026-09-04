---
name: meta-kpi-calculator-dev
description: Implementar, revisar e evoluir o repositório Meta KPI Calculator etapa por etapa, usando três subagentes, SOLID, KISS e gates de QA. Usar em mudanças de código, banco, API, integrações, testes e documentação deste projeto; não usar para tarefas genéricas ou para operar campanhas reais.
---

# Meta KPI Calculator Dev

## Objetivo

Evoluir este repositório com mudanças pequenas, verificáveis e coerentes com a
arquitetura aprovada. Entregar somente a etapa liberada, com um pensador, um
programador e um revisor/QA trocando contratos, resultados e correções.

## Fonte de verdade

Antes de propor ou editar código:

1. Ler `docs/STATUS.md` para identificar a próxima etapa liberada.
2. Ler `docs/DECISIONS.md` para preservar os contratos arquiteturais.
3. Ler a seção aplicável de `docs/ACCEPTANCE.md` e o `README.md`.
4. Inspecionar a árvore, os testes e o estado do Git. Preservar arquivos do
   usuário e alterações não relacionadas.
5. Para regras de Meta, matrículas, atribuição, leads ou BotConversa, usar também
   a skill `botconversa-meta-automacao` quando ela estiver disponível.

Os documentos do repositório são a fonte de verdade mutável. Não copiar para
esta skill modelos, endpoints ou decisões específicas de uma etapa.

Uma etapa liberada em `docs/STATUS.md` não fica bloqueada apenas porque ainda
não possui seção própria em `docs/ACCEPTANCE.md`. Nesse caso, o pensador deriva
e comunica os critérios da etapa a partir do plano aprovado, das decisões já
registradas e do pedido atual. Perguntar ao usuário somente quando faltar uma
decisão de produto que altere materialmente o resultado; não pedir confirmação
de detalhes técnicos que o contrato existente permite resolver.

## Trabalhar com três subagentes

Quando houver capacidade de subagentes, criar exatamente estes três papéis para
cada etapa de implementação:

- **Pensador/arquiteto:** não edita. Torna o contrato da etapa decision-complete,
  define fronteiras, invariantes, interfaces mínimas, riscos e critérios de
  aceite. Envia o contrato integral ao programador e ao QA. Ao final, confirma
  que a implementação não desviou da arquitetura nem antecipou escopo.
- **Programador:** é o único agente que edita arquivos. Aguarda o contrato do
  pensador, implementa apenas a etapa liberada, executa os testes e envia um
  handoff completo ao QA e ao pensador.
- **Revisor/QA:** não edita arquivos. Converte o contrato em uma matriz de testes
  e casos de falha, revisa funcionamento e simplicidade, executa validações
  independentes e devolve defeitos reproduzíveis ao programador. O programador
  escreve também os testes automatizados; o QA confirma que eles realmente
  detectam o comportamento. Após as correções, o QA faz regressão e emite o
  gate final.

O agente coordenador mantém os três em comunicação. Não iniciar edições antes
de o programador receber o contrato integral. Não permitir edições simultâneas.

Cada handoff deve informar: etapa, escopo, arquivos/interfaces alterados,
decisões tomadas, comandos executados, resultados observados, defeitos ou riscos
pendentes e próximo gate. Para defeitos, incluir severidade, reprodução,
resultado atual e resultado esperado.

Se três subagentes não estiverem disponíveis, informar a limitação. Não afirmar
que houve revisão independente quando ela não ocorreu.

## Regra de simplicidade

Implementar a solução mais simples que satisfaça o contrato e os testes atuais.
Aplicar KISS e YAGNI junto de SOLID; SOLID não autoriza criar arquitetura
cerimonial.

- Preferir código direto, nomes explícitos e recursos nativos da linguagem ou
  dos frameworks já adotados.
- Criar a menor quantidade de arquivos, classes e camadas necessária para uma
  responsabilidade real.
- Não criar repository genérico, Unit of Work, service locator, fábrica,
  adapter, Protocol, classe base ou sistema de plugins sem pelo menos um
  consumidor atual e uma variação real exigida pela etapa.
- Não generalizar um caso único nem antecipar integrações futuras. Registrar o
  ponto de extensão nos documentos quando necessário, sem implementá-lo.
- Não extrair helpers que apenas renomeiam uma chamada. Extrair quando houver
  uma regra de domínio, repetição relevante ou ganho claro de teste/leitura.
- Não ocultar erros com fallbacks silenciosos. Validar nas fronteiras e manter
  o fluxo principal legível.
- Não misturar I/O externo, persistência, regra de negócio e apresentação na
  mesma unidade quando essas responsabilidades já forem independentes.
- Tratar ramificações, aninhamento ou parâmetros que não correspondam a um caso
  atual como sinais de complexidade desnecessária; simplificar antes de criar
  uma métrica ou ferramenta nova para justificar a estrutura.

## SOLID pragmático

- **Responsabilidade única:** cada módulo, classe ou função possui um motivo
  principal para mudar. Dividir somente quando responsabilidades diferentes
  realmente aparecerem.
- **Aberto/fechado:** preservar fronteiras estáveis, mas criar extensibilidade
  apenas quando existir uma segunda implementação ou requisito concreto.
- **Substituição:** implementações que compartilham um contrato devem manter as
  mesmas entradas, saídas, erros e invariantes; não criar hierarquias apenas
  para demonstrar o princípio.
- **Segregação de interfaces:** contratos devem expor somente o que o consumidor
  atual utiliza. Preferir funções ou dependências pequenas a interfaces amplas.
- **Inversão de dependência:** serviços de negócio recebem dependências de I/O
  nas fronteiras relevantes, como sessão, cliente HTTP ou relógio. Não envolver
  objetos simples em abstrações sem benefício observável.

O programador deve explicar no handoff onde cada decisão SOLID trouxe benefício
concreto e onde deliberadamente escolheu uma solução direta.

## Gates da etapa

1. O pensador congela escopo, contrato e aceite da etapa atual.
2. O programador implementa o menor incremento completo e executa testes
   proporcionais ao risco.
3. O QA revisa comportamento, regressão, segurança, duplicação, acoplamento,
   ramificações desnecessárias e abstrações sem consumidor.
4. O programador corrige todos os defeitos aceitos e adiciona regressões quando
   o defeito puder reaparecer.
5. O QA repete os testes afetados e a suíte completa.
6. O pensador confirma aderência arquitetural e ausência de escopo antecipado.
7. Somente depois dos dois gates, o programador atualiza `README.md`,
   `docs/STATUS.md`, `docs/DECISIONS.md` e `docs/ACCEPTANCE.md` quando aplicável.
8. O QA confere que a documentação relata os resultados reais, e o pensador
   confirma que novas decisões não contradizem a arquitetura. Só então fechar a
   etapa para o usuário.

Não marcar uma etapa como concluída por intenção, código não executado ou teste
apenas por código de saída quando o estado persistido também puder ser
verificado. Registrar resultados reais e limitações conhecidas.

A ausência de commit inicial, isoladamente, não bloqueia uma etapa quando a
árvore e `docs/STATUS.md` estabelecem claramente o baseline. Como `git diff`
pode ser insuficiente nesse caso, registrar antes da edição um inventário dos
arquivos, do estado Git e das áreas que a etapa pretende tocar; depois revisar
a árvore e o conteúdo completos. Se a autoria for incerta e a mudança precisar
sobrepor conteúdo existente, parar e pedir direção ao usuário. Não bloquear por
arquivos não rastreados que estejam fora do escopo e possam ser preservados.

## Restrições permanentes

- Nunca incluir token, credencial ou dado pessoal em código, fixture, log,
  documentação ou resposta.
- Não solicitar que o usuário envie tokens pelo chat.
- Não realizar escrita na Meta, alterar campanhas, orçamento ou anúncios.
- Não executar integração real, envio de mensagem ou mudança no BotConversa sem
  autorização explícita para essa operação.
- Usar IDs externos da Meta como identidade de origem; não usar nomes como
  chave.
- Manter contrato, matrícula pagante, cancelamento, receita prevista e receita
  recebida como conceitos distintos.
- Preservar Alembic como autoridade do schema; não usar `create_all` no startup.
- Não criar commit, push ou operação destrutiva sem solicitação do usuário.
