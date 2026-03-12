# XML DAG definitions

Add or edit `.xml` files here to create new Airflow DAGs **without writing Python**.  
The loader is in `dags/xml_dag_factory.py`.

You can trigger DAGs in two ways: **HTTP (URL)** or **Celery** (e.g. Vascular router tasks).

---

## XML format

- **Root:** `<dags>` with one or more `<dag>` children.
- **`<dag>`**
  - `id` (required): unique DAG id (e.g. `my_webhook_dag`).
  - `schedule` (required): cron expression (e.g. `0 8 * * *` for 08:00 daily).
  - `description` (optional): short description.
- **`<trigger>`** (one per `<dag>`) — choose one of the two types below.

---

## Option A: HTTP trigger (call a URL) — **recommended for production**

Use this to call any HTTP endpoint (e.g. Vascular API that then triggers Celery).  
**Production:** Prefer Option A so Vascular uses its own Redis; Airflow only needs to call the API. Option B (shared Redis / direct Celery) is for development or special cases.

- **`<trigger>`** with `url` and `method`:
  - `url` (required): full URL to call.
  - `method` (required): one of  
    `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `connect`, `trace`.
- **Parameters**
  - **Query / URL params:** use `<params>` or `<query_params>` with `<param name="...">value</param>`.
  - **Headers:** `<headers>` with `<header name="...">value</header>`.
  - **Body (POST/PUT/PATCH):** `<body type="json">...</body>` (JSON) or `<body type="text">...</body>`.

Example — call Vascular API to trigger processing (API runs Celery task). Use `http://vascular-api:8000` when Airflow and Vascular share a Docker network:

```xml
<dag id="vascular_via_api" schedule="0 8 * * *" description="Trigger Vascular via API">
  <trigger url="http://vascular-api:8000/api/v1/communicators/process" method="post">
    <headers>
      <header name="Authorization">Bearer YOUR_TOKEN</header>
    </headers>
  </trigger>
</dag>
```

See `vascular_http_example.xml` for a ready-to-use Option A DAG. With Option A you do **not** need to set `VASCULAR_CELERY_BROKER_URL` on Airflow.

---

## Option B: Celery trigger (call Vascular task directly)

Use this to send a task to Vascular Celery workers **without HTTP**. Airflow and Vascular must use the **same broker** (e.g. Redis). Best for development or when sharing Redis is acceptable; for production, prefer Option A (HTTP).

- **`<trigger>`** with `type="celery"` and `task="<task_name>"`:
  - `type="celery"` (required for this mode).
  - `task` (required): Celery task name registered in Vascular (e.g. `process_communicator_files`).
  - Optional: `<args>` with `<arg>...</arg>` for positional arguments.
  - Optional: `<kwargs>` with `<param name="...">value</param>` for keyword arguments.

**Configuration:** set `VASCULAR_CELERY_BROKER_URL` to the same broker Vascular uses (e.g. `redis://redis:6379/0`). If unset, the factory falls back to `AIRFLOW__CELERY__BROKER_URL` or `redis://localhost:6379/0`. Vascular workers must be running and consuming from that broker.

Example — trigger Vascular communicator processing directly via Celery:

```xml
<dag id="vascular_process_communicators" schedule="0 8 * * *" description="Daily Vascular communicator processing via Celery">
  <trigger type="celery" task="process_communicator_files"/>
</dag>
```

With optional kwargs:

```xml
<trigger type="celery" task="process_communicator_files">
  <kwargs>
    <param name="option">value</param>
  </kwargs>
</trigger>
```

See `vascular_celery_example.xml` for a full example.

---

### Option B with `wait="true"` (send + sensor pipeline)

Add `wait="true"` to a Celery trigger to enable **result tracking**. Instead of
fire-and-forget, the factory generates two Airflow tasks:

1. **`send_task`** — dispatches the Celery task with idempotent ID, circuit
   breaker (verifies workers are alive), Jinja template rendering for kwargs,
   and automatic trace context injection.
2. **`wait_for_result`** — a `CeleryResultSensor` in `mode="reschedule"` that
   polls the result backend without occupying a worker slot.

Additional `<trigger>` attributes for `wait="true"`:

| Attribute | Default | Description |
|---|---|---|
| `poke_interval` | `30` | Seconds between sensor polls |
| `timeout` | `3600` | Maximum seconds the sensor will wait before failing |
| `startup_timeout` | `300` | If the task stays in PENDING beyond this many seconds, the sensor fails early (detects lost tasks / dead workers) |

**Jinja templates:** kwargs values may use Airflow template variables such as
`{{ ds_nodash }}`, `{{ execution_date }}`, etc. They are rendered at runtime
using the Airflow task context.

**Idempotency:** the Celery task ID is derived from `task_name + dag_run.run_id`,
so retries of the same DAG run will not create duplicate tasks.

**Trace context:** a `_trace` dict containing `dag_id`, `dag_run_id`,
`execution_date`, and `task_instance` is automatically injected into kwargs.
Vascular tasks can log this for cross-system traceability.

Example — file confirmation with result tracking and dynamic trade date:

```xml
<dag id="vascular_file_confirmation" schedule="0 8 * * *"
     description="File Confirmation via Celery (send + sensor)">
  <trigger type="celery" task="file_confirmation"
           wait="true" poke_interval="30" timeout="3600" startup_timeout="300">
    <kwargs>
      <param name="trade_date">{{ ds_nodash }}</param>
      <param name="cpty">all</param>
      <param name="by">email</param>
      <param name="env">prod</param>
    </kwargs>
  </trigger>
</dag>
```

See `vascular_file_confirmation.xml` for a complete example.

---

### Pipeline mode: multi-step Celery workflows

Use `<pipeline>` (instead of `<trigger>`) when you need **multiple Celery tasks
executed in sequence**, each independently visible in the Airflow UI. The factory
generates pairs of `send_<task>` + `wait_<task>` operators chained together:

```
send_step1 >> wait_step1 >> send_step2 >> wait_step2 >> ... >> send_stepN >> wait_stepN
```

**Data passing:** intermediate data between steps is stored in Redis via
`PipelineContext` (keyed by `pipeline:<dag_run_id>`). Only the first step
receives kwargs from the XML; subsequent steps read their inputs from Redis
automatically. All pipeline keys expire after 24 hours.

**`<pipeline>` attributes** (defaults for all steps):

| Attribute | Default | Description |
|---|---|---|
| `poke_interval` | `30` | Seconds between sensor polls |
| `timeout` | `3600` | Maximum seconds each sensor will wait |
| `startup_timeout` | `300` | Fail if task stuck in PENDING beyond this |

**`<step>` attributes:**

| Attribute | Required | Description |
|---|---|---|
| `task` | Yes | Celery task name registered in Vascular |
| `poke_interval` | No | Override pipeline default for this step |
| `timeout` | No | Override pipeline default for this step |
| `startup_timeout` | No | Override pipeline default for this step |

Each `<step>` may optionally contain `<kwargs>` (same syntax as `<trigger>`).
Jinja templates (`{{ ds_nodash }}`, etc.) are supported in kwargs values.

**Idempotency, circuit breaker, and trace context** work the same way as the
single-step `wait="true"` mode.

Example — file confirmation broken into 6 observable steps:

```xml
<dag id="vascular_fc_pipeline" schedule="0 8 * * *"
     description="File Confirmation 6-step pipeline via Celery">
  <pipeline poke_interval="15" timeout="3600" startup_timeout="120">
    <step task="fc_prepare_config">
      <kwargs>
        <param name="trade_date">{{ ds_nodash }}</param>
        <param name="cpty">all</param>
        <param name="by">email</param>
        <param name="env">prod</param>
      </kwargs>
    </step>
    <step task="fc_prepare_sql"/>
    <step task="fc_run_query" timeout="1800"/>
    <step task="fc_parse_data"/>
    <step task="fc_generate_report" timeout="1800"/>
    <step task="fc_send_email"/>
  </pipeline>
</dag>
```

See `vascular_fc_pipeline.xml` for a complete example.

---

## Example (minimal HTTP)

```xml
<dags>
  <dag id="my_dag" schedule="0 9 * * *">
    <trigger url="https://api.example.com/webhook" method="post">
      <params>
        <param name="key">value</param>
      </params>
      <body type="json">
        {"event": "daily"}
      </body>
    </trigger>
  </dag>
</dags>
```

After saving, run `deploy_dags` (or let CI sync) so Airflow picks up the new DAG.
