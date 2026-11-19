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
