# Airflow Plugins

Plugins are synced to the `airflow_airflow-plugins` volume during CI/CD deploy.

## Next Run View

Displays DAG list with **next execution time** (`next_dagrun_create_after`) instead of data interval start.

- **Menu**: Browse → DAG 列表（執行時間）
- **Purpose**: Show when DAGs will actually run, not the logical date
