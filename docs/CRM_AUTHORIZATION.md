# Autorização do mini-CRM

A API exige uma sessão interna válida para as rotas de CRM, administração e
Analytics. Administradores provisionam identidades por emissor e subject,
gerenciam perfis e atribuem leads. Operadores consultam e atendem somente os
próprios leads. O filtro de leads sem responsável é reservado ao administrador.
O histórico comercial registra a conta autenticada. Criação, atualização de
conta e reatribuição geram registros de auditoria na mesma transação.
A desativação revoga as sessões existentes. Contas são desativadas em vez de
excluídas para preservar o histórico. Leads de uma conta desativada continuam
atribuídos até que um administrador os reatribua.

A revisão `0007_crm_authorization` adiciona referências opcionais ao
responsável e ao autor. Atribuições novas começam vazias e a autoria legada é
preservada. O webhook HMAC e o worker continuam com seus acessos de serviço.
A fase 4A não emite sessões nem cria um administrador. Após a migração, uma
instalação sem sessões válidas retorna 401 nas rotas protegidas. O Streamlit
atual depende da integração da fase 4B para acessá-las.

## Integração Google Workspace (fase 4B)

1. O FastAPI inicia Authorization Code com PKCE, `state` e `nonce` de uso único.
   O callback valida assinatura via JWKS, emissor, audiência, expiração, nonce,
   domínio Workspace (`hd`) aprovado e e-mail verificado. A conta interna é
   localizada pelo emissor canônico e subject, com provisionamento explícito.
2. O servidor emite um token aleatório de 32 bytes codificado como base64url,
   guarda apenas seu SHA-256 no PostgreSQL e envia o token em cookie
   `rctec_session`, HttpOnly, Secure em produção e SameSite=Lax, com prazo
   definido. A UI e os caminhos de login/logout ficam na mesma origem.
3. O Streamlit encaminha somente o cookie de sessão à API privada no servidor,
   sem gravá-lo em logs ou caches compartilhados. O FastAPI consulta a sessão
   e o perfil atual a cada requisição.
4. Logout via POST revoga a sessão no banco, expira o cookie e limpa o estado
   e os dados da interface. Valide Origin e token CSRF nos endpoints de
   alteração que aceitam cookies, inclusive logout. Mantenha a proteção XSRF
   do Streamlit e valide o fluxo em abas existentes e reconexões WebSocket.

O domínio Workspace, os redirects de cada ambiente, a primeira conta
administradora e a duração da sessão serão definidos na fase 4B.

## Controles verificados na fase 4A.1

Mudanças de perfil e desativação revogam as sessões existentes na mesma
transação da alteração e da auditoria. Reativar uma conta exige nova sessão.
A consulta de histórico aplica o escopo do responsável na própria instrução SQL.
Uma leitura iniciada antes do commit de uma reatribuição ainda vê seu snapshot;
leituras iniciadas depois do commit respeitam a nova atribuição.

O PostgreSQL da aplicação usa **READ COMMITTED**. A alteração de contas e a
atribuição de leads passam pelo mesmo bloqueio transacional, com revalidação
do administrador após adquirir o bloqueio. Essas operações falham de forma
segura se a conexão usar outro isolamento. Não há endpoint de exclusão de conta.
Ferramentas futuras que alterem contas devem preservar esse mesmo protocolo.

### Papéis PostgreSQL

Valide em uma instância isolada antes de configurar papéis de produção.
Separe credenciais e reserve a propriedade do schema e tabelas ao papel de
migrations. O papel da API lê as sessões, altera sua revogação e gerencia
operações administrativas e insere auditoria. Permita SELECT apenas dos
campos técnicos retornados pelos INSERTs de auditoria e atividades ao papel
que os grava. A futura
emissão de sessões exige uma concessão explícita na 4B. O webhook insere na
inbox e lê somente a chave necessária à deduplicação. O worker lê e atualiza
a inbox, ingere leads e insere atividades; não altera atribuição, estado
comercial de leads existentes, sessões ou contas. O INSERT de leads inclui
a coluna do status inicial (`NEW`), preenchida pelo ORM. Conceda uso apenas das sequências necessárias.
O ensaio automatizado usa quatro papéis descartáveis e cobre o fluxo principal
de cada serviço. Revisar demais operações Analytics e tarefas de manutenção
com os papéis reais antes de publicar; nenhuma permissão foi aplicada ao banco
principal nesta fase.

### Bloqueios de ativação da fase 4B

- Validar assinatura OIDC, emissor, subject, audiência e domínio Workspace,
  além de expiração, nonce, state e PKCE. Autorizar somente identidades
  previamente vinculadas por emissor canônico e subject.
- Provisionar o primeiro administrador explicitamente por rotina local
  auditável, após verificar a identidade. O primeiro login nunca promove a conta.
- Aplicar expiração e revogação de sessão. A emissão deve coordenar-se com
  mudanças de perfil e desativação para evitar emitir uma sessão com base em
  estado antigo. Definir prazo curto e um processo
  de desligamento que desative a conta interna e revogue todas as sessões
  quando o Google Workspace suspender o usuário. A suspensão no Google por si
  só não invalida uma sessão local existente.
- Aplicar CSRF e validação de origem nas operações acessíveis por navegador
  autenticadas por cookie. Manter a API privada e rotear somente o fluxo de
  autenticação necessário na borda pública.
- Excluir cookies, códigos OIDC e demais parâmetros sensíveis dos logs da
  borda, API e Streamlit.
- Validar em navegador login, logout, troca de conta, abas antigas, reconexão
  e downloads após revogação.
