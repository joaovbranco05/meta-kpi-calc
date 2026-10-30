# PostgreSQL e migração de snapshot SQLite

O SQLite permanece disponível para desenvolvimento. PostgreSQL usa SQLAlchemy e
`psycopg` (`postgresql+psycopg://...`). `postgresql://...` é normalizada para
esse driver. Forneça URLs e senhas por variáveis de ambiente seguras; não as
adicione ao Git nem a argumentos de comandos visíveis em listas de processos.
`DATABASE_URL` e `DEMO_DATABASE_URL` devem identificar bancos distintos. A
comparação de URLs não detecta todos os aliases de rede para o mesmo servidor:
confirme a separação real dos ambientes.

## Migrations e testes

Instale as dependências do projeto no ambiente virtual. Em um banco PostgreSQL
vazio e explicitamente selecionado, configure `DEMO_MODE` e a URL ativa e execute
`alembic upgrade head`. Uma trava consultiva PostgreSQL serializa execuções do
Alembic pelo projeto. Não inicie migrations em todos os processos da aplicação;
use um único job de implantação. Reexecutar `alembic upgrade head` mantém a revisão.

O ensaio isolado abaixo cria um cluster temporário, aceita somente socket Unix
em `/tmp`, cria bancos fictícios, executa os testes PostgreSQL e para o servidor:

```sh
.venv/bin/python scripts/test_postgresql.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin
```

Na máquina de execução são necessários os binários PostgreSQL 17, `psycopg` e
permissão para memória compartilhada local. O script copia código e testes sem
`.env` ou `data`, e não se conecta a um cluster existente. Sem o ambiente de
teste explícito, os testes PostgreSQL são ignorados; isso não é aprovação.

## Procedimento de cópia

Execute contra dados reais apenas com autorização específica e com a origem sem
escritores. Crie primeiro um snapshot consistente do SQLite pela API de backup
do SQLite, incluindo dados em WAL; confira integridade e guarde o original e um
backup separado. Faça o ensaio usando dados fictícios e banco descartável antes
de qualquer corte. Datas sem fuso no SQLite são interpretadas como UTC: valide
esse pressuposto para os dados históricos antes de migrar.

Crie um PostgreSQL exclusivo e vazio, aplique `alembic upgrade head` e configure
`MIGRATION_TARGET_URL` de forma segura. A ferramenta aceita apenas origens e
destinos na revisão `0006_lead_ads_inbox` e rejeita tabelas de destino que já
contenham dados. Ela abre o snapshot em modo somente leitura. O nome do banco
de destino deve ser repetido em `--confirm-target` para evitar enganos.

```sh
PYTHONPATH=src python -m meta_kpi_calc.db.migrate_sqlite --source /caminho/snapshot.db --confirm-target nome_do_banco
```

O comando acima é um dry-run: retorna contagens, sem inserir dados. Após revisar
destino, backups e contagens, adicione `--execute` para copiar e validar. A cópia
preserva IDs, relacionamentos, atividades e estados; compara os registros e ajusta
sequências. O relatório apresenta apenas contagens. Falhas não exibem registros
ou credenciais. O destino deve ser descartado ou reavaliado antes de uma nova
tentativa: operações de sequência PostgreSQL podem não ser revertidas junto com
uma transação que falhou.

Antes do corte, valide contagens, histórico, referências e restauração do backup.
Não escreva simultaneamente nos dois bancos. Após novas gravações no PostgreSQL,
retornar a uma cópia antiga do SQLite requer preservar e reconciliar essas
gravações; simplesmente trocar a URL não é um rollback sem perda.
