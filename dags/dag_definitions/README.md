# XML DAG definitions

Add or edit `.xml` files here to create new Airflow DAGs **without writing Python**.  
The loader is in `dags/xml_dag_factory.py`.

## XML format

- **Root:** `<dags>` with one or more `<dag>` children.
- **`<dag>`**
  - `id` (required): unique DAG id (e.g. `my_webhook_dag`).
  - `schedule` (required): cron expression (e.g. `0 8 * * *` for 08:00 daily).
  - `description` (optional): short description.
- **`<trigger>`** (one per `<dag>`)
  - `url` (required): full URL to call.
  - `method` (required): one of  
    `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `connect`, `trace`.
- **Parameters**
  - **Query / URL params:** use `<params>` or `<query_params>` with `<param name="...">value</param>`.
  - **Headers:** `<headers>` with `<header name="...">value</header>`.
  - **Body (POST/PUT/PATCH):** `<body type="json">...</body>` (JSON) or `<body type="text">...</body>`.

## Example (minimal)

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
