# PostgreSQL local do mini-CRM

O ambiente de desenvolvimento usa PostgreSQL 17 do Homebrew, em `127.0.0.1:55432`,
banco `meta_kpi_dev` e usuário de aplicação `meta_kpi_runtime`. A URL e a senha
ficam em `.env`, que deve permanecer privado e fora do Git. O acesso TCP exige
senha; o socket administrativo fica em um diretório privado e usa autenticação
local do usuário do sistema. O processo não é registrado no `brew services`.

Os comandos abaixo devem ser executados na raiz de `meta-kpi-calc` pelo mesmo
usuário do macOS que criou o ambiente. A configuração de autenticação em `.logs`
é necessária e não deve ser removida enquanto este banco estiver em uso.

## Iniciar o banco

```sh
test -d /private/tmp/mkcrm17_82c930bccc || mkdir -m 700 /private/tmp/mkcrm17_82c930bccc
/opt/homebrew/opt/postgresql@17/bin/pg_ctl \
  -D /opt/homebrew/var/postgresql@17 \
  -l "$PWD/.logs/pg17-crm-server-82c930bccc.log" \
  -o "-c hba_file=$PWD/.logs/pg17-crm-hba-82c930bccc.conf -c listen_addresses=127.0.0.1 -c port=55432 -c unix_socket_directories=/private/tmp/mkcrm17_82c930bccc -c unix_socket_permissions=0700 -c password_encryption=scram-sha-256 -c log_statement=none -c log_min_error_statement=panic" \
  -w start
```

Para verificar o estado:

```sh
/opt/homebrew/opt/postgresql@17/bin/pg_ctl -D /opt/homebrew/var/postgresql@17 status
```

## Parar o banco

Pare primeiro a API e qualquer processo que esteja usando o banco. O comando
abaixo para o **cluster PostgreSQL 17 inteiro**, incluindo outros bancos que
venham a ser criados nele:

```sh
/opt/homebrew/opt/postgresql@17/bin/pg_ctl -D /opt/homebrew/var/postgresql@17 -m fast -w stop
```

O PostgreSQL 18 do Postgres.app usa outra instalação e não é controlado por
esses comandos.

## Migrations futuras

O usuário da aplicação não tem permissão de criar ou alterar tabelas. Para
aplicar migrations autorizadas, use o usuário local do macOS pelo socket
privado, assumindo a função proprietária apenas durante o comando:

```sh
DEMO_MODE=false DATABASE_URL="postgresql+psycopg://$(id -un)@localhost/meta_kpi_dev?host=/private/tmp/mkcrm17_82c930bccc&port=55432&options=-c%20role%3Dmeta_kpi_owner" \
  .venv/bin/alembic upgrade head
```

Esse comando não altera a URL da aplicação em `.env`. Faça backup e valide a
migration antes de usá-lo com dados importantes.

## Retornar à configuração SQLite

O backup consistente anterior à migração está em
`data/meta_kpi.before-postgres-20261030T154113Z.db`; o banco original é
`data/meta_kpi.db`. A configuração anterior está no arquivo privado
`.logs/env-before-postgres-17f22b0cac7d.env`.

Antes de restaurar a configuração, pare processos que escrevem, preserve a
configuração PostgreSQL atual em outro arquivo privado e faça backup dos dois
bancos. Compare e reconcilie quaisquer gravações posteriores feitas no
PostgreSQL: voltar ao SQLite antigo por si só não as preserva. Então restaure
em `.env` o valor anterior de `DATABASE_URL`, `sqlite:///./data/meta_kpi.db`,
mantendo `DEMO_MODE=false` e os demais valores atuais. Como alternativa, o backup
da configuração anterior pode ser restaurado integralmente, levando em conta
que isso também reverterá eventuais alterações posteriores nos outros campos.
Mantenha a permissão `600` e confirme o banco ativo. Não remova nenhum banco ou
backup como parte do retorno.
