# Worker contínuo Lead Ads

O worker não inicia com a API nem com o Streamlit. Para iniciá-lo manualmente,
com as configurações Lead Ads já prontas e somente quando houver autorização
para processar a inbox e consultar a Meta:

```bash
cd meta-kpi-calc
.venv/bin/python -m meta_kpi_calc.crm.lead_ads_cli worker --allow-network
```

O comando usa o banco ativo configurado no `.env` ou ambiente e pode fazer
consultas à Meta e gravar nesse banco. Confirme o destino antes de executá-lo.
Interrompa com Ctrl+C ou SIGTERM. Um evento em andamento termina antes da saída;
nenhum novo evento é assumido depois da sinalização. Uma falha abrupta deixa a
lease recuperável após expirar, sujeita ao limite de tentativas existente.

Variáveis: `LEAD_ADS_WORKER_BATCH_SIZE` (100), `LEAD_ADS_WORKER_POLL_SECONDS`
(5), `LEAD_ADS_WORKER_BACKOFF_BASE_SECONDS` (5) e
`LEAD_ADS_WORKER_BACKOFF_MAX_SECONDS` (300). São segundos, exceto o lote.
Falhas de ciclo usam backoff exponencial limitado; falhas de eventos usam o
retry persistente já existente. Logs estruturados informam ciclos, contagens,
backlog e última falha sem detalhes de exceções. Essas métricas são locais ao
processo e reiniciam quando ele reinicia; backlog inclui eventos em processamento.
Uma consulta Graph pode ultrapassar a duração da lease: o fencing impede a
gravacão tardia, mas consultas externas repetidas continuam possíveis.
