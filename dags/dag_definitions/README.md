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

## Option A: HTTP trigger (call a URL)

Use this to call any HTTP endpoint (e.g. Vascular API that then triggers Celery).

- **`<trigger>`** with `url` and `method`:
  - `url` (required): full URL to call.
  - `method` (required): one of  
    `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `connect`, `trace`.
- **Parameters**
  - **Query / URL params:** use `<params>` or `<query_params>` with `<param name="...">value</param>`.
  - **Headers:** `<headers>` with `<header name="...">value</header>`.
  - **Body (POST/PUT/PATCH):** `<body type="json">...</body>` (JSON) or `<body type="text">...</body>`.

Example — call Vascular API to trigger processing (API runs Celery task):

```xml
<dag id="vascular_via_api" schedule="0 8 * * *" description="Trigger Vascular via API">
  <trigger url="http://vascular-host/api/v1/communicators/process" method="post">
    <headers>
      <header name="Authorization">Bearer YOUR_TOKEN</header>
    </headers>
  </trigger>
</dag>
```

---

## Option B: Celery trigger (call Vascular task directly)

Use this to send a task to Vascular Celery workers **without HTTP**. Airflow and Vascular must use the **same broker** (e.g. Redis).

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
