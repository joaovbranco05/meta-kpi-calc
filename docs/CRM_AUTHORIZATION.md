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
   `__Host-rctec_session`, HttpOnly, Secure em produção e SameSite=Lax, com prazo
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


## Fase 4B — execução e ativação

A migration `0008_oidc_flows` cria transações de login de uso único e registra
mudanças de conta que invalidam logins já iniciados. Configure as quatro
variáveis OIDC do `.env.example` somente no serviço FastAPI. Com elas ausentes
ou em modo demo, login e callback ficam indisponíveis. Guarde o segredo no
ambiente privado. Use um cliente Workspace interno e cadastre exatamente
`https://<origem-do-crm>/auth/callback`. Configure uma origem HTTPS sem caminho.

A borda HTTPS encaminha somente `GET /auth/login`, `GET /auth/callback` e
`GET/POST /auth/logout` ao FastAPI. Bloqueie externamente `/api/*`,
`/auth/session`, `/health` e quaisquer outras rotas FastAPI. O restante
segue para o Streamlit, incluindo o upgrade WebSocket. A API fica em rede
privada e `API_BASE_URL` no Streamlit aponta para essa rede. Restrinja o
host da borda ao domínio esperado e preserve o Origin. Não sobrescreva
`Referrer-Policy: same-origin` na página de confirmação de logout, pois a
política `no-referrer` pode fazer o navegador enviar Origin nulo no POST.
O webhook continua em entrada e serviço separados.

O cookie `__Host-rctec_session` usa Path=/, Secure, HttpOnly, SameSite=Lax
e não tem Domain. Ao iniciar uma conexão, o Streamlit encaminha apenas esse
cookie para o FastAPI e acrescenta o token de CSRF às suas chamadas de
escrita. A sessão é reavaliada a cada chamada e a interface verifica abas
ociosas a cada 15 segundos quando o navegador executa o timer. Logout ou
troca bem-sucedida de conta revoga a sessão anterior. Dados já entregues
ao navegador ou baixados não podem ser recolhidos.

Na borda e no Uvicorn, desative logs de acesso que incluam querystrings e
cabeçalhos sensíveis. Inicie o Uvicorn com `--no-access-log` e mantenha
logs HTTP de depuração desativados. Aplique limites de requisição na borda
às rotas de login e callback. Remova transações expiradas por rotina
operacional se necessário e defina retenção para sessões expiradas.
Valide emissão, logout e troca de conta com o HTTPS e o proxy definitivos
antes de liberar usuários.

### Primeiro administrador

1. Autorize explicitamente a pessoa responsável. Em ambiente de
   provisionamento controlado, obtenha o `sub` de uma identidade Google
   verificada para o cliente e domínio aprovados. Valide assinatura, emissor,
   audiência, expiração, nonce e `hd`. Use o emissor canônico
   `https://accounts.google.com`. Guarde apenas o par de identidade, nunca
   o token ou um endereço de e-mail como chave. A tela de login comum
   rejeita identidades ainda não cadastradas.
2. Um operador de banco autorizado abre uma transação READ COMMITTED,
   usa o mesmo bloqueio `pg_advisory_xact_lock(718503120464)` das alterações
   de conta e confirma que a instalação ainda não recebeu o primeiro
   administrador. Insere a conta ativa com o par verificado e perfil
   `admin`, usando parâmetros SQL e os constraints de unicidade.
3. Na mesma transação, registre `bootstrap_admin` em `admin_audit` com o
   ID criado em `actor_user_id` e `target_user_id` e `new_value='admin'`.
   Esse autor é convencional para bootstrap, pois ainda não há sessão
   administrativa. Registre quem autorizou e quem executou em um registro
   operacional separado, sem credenciais. Revise a inserção antes do commit.
4. O administrador se autentica pelo Google para obter a primeira sessão.
   Criar a conta não gera cookie. Use procedimento de recuperação separado
   se já existir um administrador provisionado.

Além dos privilégios da 4A.1, o papel da API precisa de INSERT em
`app_sessions` e SELECT/INSERT/DELETE em `oidc_flows`, sem DDL. Use um papel
operacional separado para CLIs de status, reconciliação e manutenção, com
acesso explícito às tabelas necessárias em cada operação.

Exemplo de roteamento Caddy para revisão antes da ativação. Troque os nomes
dos serviços pelos endereços privados do ambiente. Preserve os controles
de origem e XSRF do Streamlit.

```caddyfile
crm.example.invalid {
    @auth_get {
        method GET
        path /auth/login /auth/callback /auth/logout
    }
    @auth_post {
        method POST
        path /auth/logout
    }
    @private path /api /api/* /auth /auth/* /health /docs /redoc /openapi.json

    route {
        reverse_proxy @auth_get fastapi:8000
        reverse_proxy @auth_post fastapi:8000
        respond @private 404
        reverse_proxy streamlit:8501
    }
}
```
