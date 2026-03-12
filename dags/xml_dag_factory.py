"""
XML-driven DAG factory: create Airflow DAGs from XML files without writing Python.
Edit XML in dags/dag_definitions/ to add new DAGs (schedule, trigger URL or Celery task).

Celery triggers support an optional ``wait="true"`` mode that generates a
send_task → CeleryResultSensor pipeline with idempotent task IDs, circuit
breaker, trace context injection, and Jinja template rendering for kwargs.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from airflow import DAG
from airflow.exceptions import AirflowException
from airflow.operators.python import PythonOperator
from airflow.sensors.base import BaseSensorOperator
from airflow.utils.dates import days_ago

_log = logging.getLogger(__name__)

# Default args for all generated DAGs
DEFAULT_ARGS = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": __import__("datetime").timedelta(minutes=5),
}

# Directory for XML definitions (next to this file)
DEFINITIONS_DIR = Path(__file__).resolve().parent / "dag_definitions"

ALLOWED_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "connect", "trace"}
)


def _http_trigger(
    url: str,
    method: str,
    query_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    body_type: str = "json",
    **kwargs: Any,
) -> None:
    """Execute HTTP request. Used as PythonOperator callable."""
    import urllib.request
    import urllib.error
    import json

    method = method.upper()
    query_params = query_params or {}
    headers = headers or {}

    if query_params:
        from urllib.parse import urlencode
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urlencode(query_params)}"

    if body and body_type.lower() == "json" and method in ("POST", "PUT", "PATCH"):
        try:
            data = json.loads(body)
            body_bytes = json.dumps(data).encode("utf-8")
        except json.JSONDecodeError:
            body_bytes = body.encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif body and method in ("POST", "PUT", "PATCH"):
        body_bytes = body.encode("utf-8")
    else:
        body_bytes = None

    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        code = resp.getcode()
        resp.read()
    if code >= 400:
        raise RuntimeError(f"HTTP {code} for {method} {url}")


def _get_vascular_celery_app():
    """Lazy Celery app for sending tasks to Vascular (same broker, no tasks registered)."""
    from celery import Celery
    broker = os.getenv("VASCULAR_CELERY_BROKER_URL") or os.getenv("AIRFLOW__CELERY__BROKER_URL") or "redis://localhost:6379/0"
    return Celery(broker=broker, backend=broker, include=[])


def _celery_trigger(
    task_name: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    **_: Any,
) -> None:
    """Send a task to Vascular Celery workers (fire-and-forget). Used for wait=false."""
    app = _get_vascular_celery_app()
    app.send_task(task_name, args=args or [], kwargs=kwargs or {})


def _celery_trigger_with_xcom(
    task_name: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    **context: Any,
) -> None:
    """Send a Celery task with idempotent ID, circuit breaker, trace context,
    Jinja rendering, and XCom push.  Used as PythonOperator callable for wait=true."""
    from jinja2 import Template

    app = _get_vascular_celery_app()

    # --- circuit breaker: verify at least one worker is alive ---
    try:
        ping = app.control.inspect(timeout=5).ping()
    except Exception:
        ping = None
    if not ping:
        raise AirflowException(
            "No Vascular Celery workers responding — aborting to prevent queue buildup"
        )

    # --- resolve Jinja templates in kwargs ---
    resolved_kwargs: dict[str, Any] = {}
    for k, v in (kwargs or {}).items():
        if isinstance(v, str) and "{{" in v:
            resolved_kwargs[k] = Template(v).render(**context)
        else:
            resolved_kwargs[k] = v

    # --- inject trace context ---
    dag_run = context.get("dag_run")
    ti = context.get("ti")
    dag_obj = context.get("dag")
    resolved_kwargs["_trace"] = {
        "dag_id": getattr(dag_obj, "dag_id", None) or getattr(dag_run, "dag_id", "unknown"),
        "dag_run_id": getattr(dag_run, "run_id", "unknown"),
        "execution_date": str(context.get("execution_date", "")),
        "task_instance": getattr(ti, "task_id", "unknown"),
    }

    # --- deterministic task ID for idempotency ---
    run_id = getattr(dag_run, "run_id", "manual")
    seed = f"{task_name}:{run_id}"
    celery_task_id = hashlib.sha256(seed.encode()).hexdigest()[:32]

    existing = app.AsyncResult(celery_task_id)
    if existing.state not in ("PENDING", None):
        _log.info("Task %s already dispatched (state=%s), reusing", celery_task_id, existing.state)
    else:
        app.send_task(
            task_name,
            args=args or [],
            kwargs=resolved_kwargs,
            task_id=celery_task_id,
        )
        _log.info("Dispatched Celery task %s as %s", task_name, celery_task_id)

    if ti is not None:
        ti.xcom_push(key="celery_task_id", value=celery_task_id)


class CeleryResultSensor(BaseSensorOperator):
    """Polls the Celery result backend until the task reaches a terminal state.

    Uses ``mode="reschedule"`` so it does not occupy an Airflow worker slot
    while waiting.  Includes a *startup_timeout* to detect tasks stuck in
    PENDING (worker down / task lost).
    """

    def __init__(
        self,
        send_task_id: str,
        startup_timeout: int = 300,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.send_task_id = send_task_id
        self.startup_timeout = startup_timeout
        self._first_poke_ts: float | None = None

    def poke(self, context: dict[str, Any]) -> bool:
        if self._first_poke_ts is None:
            self._first_poke_ts = time.time()

        ti = context["ti"]
        celery_task_id: str | None = ti.xcom_pull(
            task_ids=self.send_task_id, key="celery_task_id"
        )
        if not celery_task_id:
            raise AirflowException(
                f"No celery_task_id found in XCom from task '{self.send_task_id}'"
            )

        app = _get_vascular_celery_app()
        result = app.AsyncResult(celery_task_id)
        state = result.state

        if state == "SUCCESS":
            _log.info("Celery task %s succeeded", celery_task_id)
            ti.xcom_push(key="celery_result", value=result.result)
            return True
        if state == "FAILURE":
            raise AirflowException(f"Celery task {celery_task_id} failed: {result.result}")
        if state == "REVOKED":
            raise AirflowException(f"Celery task {celery_task_id} was revoked")

        if state == "PENDING":
            elapsed = time.time() - self._first_poke_ts
            if elapsed > self.startup_timeout:
                raise AirflowException(
                    f"Celery task {celery_task_id} stuck in PENDING for "
                    f"{elapsed:.0f}s — worker may be down or task was lost"
                )

        _log.info("Celery task %s state=%s, waiting...", celery_task_id, state)
        return False


def _pipeline_celery_trigger(
    task_name: str,
    kwargs: dict[str, Any] | None = None,
    prev_wait_task_id: str | None = None,
    step_index: int = 0,
    **context: Any,
) -> None:
    """Send a Celery task as part of a multi-step pipeline.

    - Step 0 generates a new ``pipeline_key`` from ``dag_run.run_id``.
    - Steps 1+ read ``pipeline_key`` from the previous sensor's XCom.
    - Includes circuit breaker, Jinja rendering, trace injection, and
      idempotent task IDs (same as ``_celery_trigger_with_xcom``).
    """
    from jinja2 import Template

    app = _get_vascular_celery_app()

    try:
        ping = app.control.inspect(timeout=5).ping()
    except Exception:
        ping = None
    if not ping:
        raise AirflowException(
            "No Vascular Celery workers responding — aborting to prevent queue buildup"
        )

    dag_run = context.get("dag_run")
    ti = context.get("ti")
    run_id = getattr(dag_run, "run_id", "manual")

    if step_index == 0:
        pipeline_key = f"pipeline:{run_id}"
    else:
        prev_result = ti.xcom_pull(task_ids=prev_wait_task_id, key="celery_result") or {}
        pipeline_key = prev_result.get("pipeline_key")
        if not pipeline_key:
            raise AirflowException(
                f"No pipeline_key found in XCom from '{prev_wait_task_id}'"
            )

    resolved_kwargs: dict[str, Any] = {"pipeline_key": pipeline_key}
    for k, v in (kwargs or {}).items():
        if isinstance(v, str) and "{{" in v:
            resolved_kwargs[k] = Template(v).render(**context)
        else:
            resolved_kwargs[k] = v

    dag_obj = context.get("dag")
    resolved_kwargs["_trace"] = {
        "dag_id": getattr(dag_obj, "dag_id", None) or getattr(dag_run, "dag_id", "unknown"),
        "dag_run_id": run_id,
        "execution_date": str(context.get("execution_date", "")),
        "task_instance": getattr(ti, "task_id", "unknown"),
    }

    seed = f"{task_name}:{run_id}"
    celery_task_id = hashlib.sha256(seed.encode()).hexdigest()[:32]

    existing = app.AsyncResult(celery_task_id)
    if existing.state not in ("PENDING", None):
        _log.info("Pipeline task %s already dispatched (state=%s)", celery_task_id, existing.state)
    else:
        app.send_task(task_name, args=[], kwargs=resolved_kwargs, task_id=celery_task_id)
        _log.info("Dispatched pipeline task %s as %s", task_name, celery_task_id)

    if ti is not None:
        ti.xcom_push(key="celery_task_id", value=celery_task_id)


def _parse_pipeline(pipeline_el: ET.Element) -> dict[str, Any]:
    """Parse a ``<pipeline>`` element containing multiple ``<step>`` children."""
    defaults = {
        "poke_interval": int((pipeline_el.get("poke_interval") or "30").strip()),
        "timeout": int((pipeline_el.get("timeout") or "3600").strip()),
        "startup_timeout": int((pipeline_el.get("startup_timeout") or "300").strip()),
    }

    steps: list[dict[str, Any]] = []
    for step_el in pipeline_el.findall("step"):
        task = (step_el.get("task") or "").strip()
        if not task:
            raise ValueError("pipeline <step> must have a task attribute")
        kwargs_el = step_el.find("kwargs")
        kwargs = _parse_params(kwargs_el, "param", "name") if kwargs_el is not None else {}

        step: dict[str, Any] = {
            "task": task,
            "kwargs": kwargs,
            "poke_interval": int((step_el.get("poke_interval") or str(defaults["poke_interval"])).strip()),
            "timeout": int((step_el.get("timeout") or str(defaults["timeout"])).strip()),
            "startup_timeout": int((step_el.get("startup_timeout") or str(defaults["startup_timeout"])).strip()),
        }
        steps.append(step)

    if not steps:
        raise ValueError("<pipeline> must contain at least one <step>")

    return {"trigger_type": "pipeline", "steps": steps, **defaults}


def _parse_params(parent: ET.Element | None, tag: str, key_attr: str = "name") -> dict[str, str]:
    if parent is None:
        return {}
    out = {}
    for node in parent.findall(tag):
        name = node.get(key_attr)
        if name is not None:
            out[name] = (node.text or "").strip()
    return out


def _parse_trigger(trigger: ET.Element) -> dict[str, Any]:
    url = (trigger.get("url") or "").strip()
    trigger_type_attr = (trigger.get("type") or "").strip().lower()
    task_attr = (trigger.get("task") or "").strip()

    is_celery = trigger_type_attr == "celery" or (task_attr and not url)
    if is_celery:
        if not task_attr:
            raise ValueError("trigger type='celery' must have task=...")
        args_el = trigger.find("args")
        args = []
        if args_el is not None:
            for arg in args_el.findall("arg"):
                args.append((arg.text or "").strip())
        kwargs_el = trigger.find("kwargs")
        kwargs = _parse_params(kwargs_el, "param", "name") if kwargs_el is not None else {}

        wait = (trigger.get("wait") or "false").strip().lower() == "true"
        poke_interval = int((trigger.get("poke_interval") or "30").strip())
        timeout = int((trigger.get("timeout") or "3600").strip())
        startup_timeout = int((trigger.get("startup_timeout") or "300").strip())

        return {
            "trigger_type": "celery",
            "task": task_attr,
            "args": args,
            "kwargs": kwargs,
            "wait": wait,
            "poke_interval": poke_interval,
            "timeout": timeout,
            "startup_timeout": startup_timeout,
        }

    if not url:
        raise ValueError("trigger must have url or type='celery' with task")
    method = (trigger.get("method") or "get").strip().lower()
    if method not in ALLOWED_METHODS:
        raise ValueError(f"method must be one of {sorted(ALLOWED_METHODS)}, got {method!r}")

    query_params = _parse_params(trigger, "query_params/param", "name")
    if not query_params:
        qp = trigger.find("params")
        if qp is not None:
            query_params = _parse_params(qp, "param", "name")

    headers_el = trigger.find("headers")
    headers = _parse_params(headers_el, "header", "name") if headers_el is not None else {}

    body_el = trigger.find("body")
    body = None
    body_type = "json"
    if body_el is not None and body_el.text:
        body = body_el.text.strip()
        body_type = (body_el.get("type") or "json").strip().lower()

    return {
        "trigger_type": "http",
        "url": url,
        "method": method,
        "query_params": query_params,
        "headers": headers,
        "body": body,
        "body_type": body_type,
    }


def create_dag_from_xml_element(dag_el: ET.Element, source_file: str) -> DAG | None:
    """
    Create a single DAG from a <dag> XML element.
    Call this from your code or let load_dags_from_xml() discover XML files.
    """
    dag_id = (dag_el.get("id") or "").strip()
    if not dag_id:
        return None
    schedule = (dag_el.get("schedule") or "").strip() or None
    description = (dag_el.get("description") or dag_el.find("description"))
    if isinstance(description, ET.Element) and description.text:
        description = description.text.strip()
    elif not isinstance(description, str):
        description = f"Generated from XML ({source_file})"

    pipeline_el = dag_el.find("pipeline")
    trigger_el = dag_el.find("trigger")

    if pipeline_el is not None:
        trigger = _parse_pipeline(pipeline_el)
    elif trigger_el is not None:
        trigger = _parse_trigger(trigger_el)
    else:
        return None

    dag = DAG(
        dag_id=dag_id,
        default_args=DEFAULT_ARGS,
        schedule=schedule,
        start_date=days_ago(1),
        tags=["xml-generated"],
        doc_md=description,
    )

    if trigger.get("trigger_type") == "pipeline":
        steps = trigger["steps"]
        prev_op = None
        for idx, step in enumerate(steps):
            send_id = f"send_{step['task']}"
            wait_id = f"wait_{step['task']}"
            prev_wait_id = f"wait_{steps[idx - 1]['task']}" if idx > 0 else None

            send_op = PythonOperator(
                task_id=send_id,
                python_callable=_pipeline_celery_trigger,
                op_kwargs={
                    "task_name": step["task"],
                    "kwargs": step.get("kwargs") or {},
                    "prev_wait_task_id": prev_wait_id,
                    "step_index": idx,
                },
                provide_context=True,
                dag=dag,
            )
            sensor_op = CeleryResultSensor(
                task_id=wait_id,
                send_task_id=send_id,
                startup_timeout=step.get("startup_timeout", 300),
                mode="reschedule",
                poke_interval=step.get("poke_interval", 30),
                timeout=step.get("timeout", 3600),
                dag=dag,
            )
            if prev_op is not None:
                prev_op >> send_op
            send_op >> sensor_op
            prev_op = sensor_op

    elif trigger.get("trigger_type") == "celery":
        if trigger.get("wait"):
            send_op = PythonOperator(
                task_id="send_task",
                python_callable=_celery_trigger_with_xcom,
                op_kwargs={
                    "task_name": trigger["task"],
                    "args": trigger.get("args") or [],
                    "kwargs": trigger.get("kwargs") or {},
                },
                provide_context=True,
                dag=dag,
            )
            sensor_op = CeleryResultSensor(
                task_id="wait_for_result",
                send_task_id="send_task",
                startup_timeout=trigger.get("startup_timeout", 300),
                mode="reschedule",
                poke_interval=trigger.get("poke_interval", 30),
                timeout=trigger.get("timeout", 3600),
                dag=dag,
            )
            send_op >> sensor_op
        else:
            PythonOperator(
                task_id="celery_trigger",
                python_callable=_celery_trigger,
                op_kwargs={
                    "task_name": trigger["task"],
                    "args": trigger.get("args") or [],
                    "kwargs": trigger.get("kwargs") or {},
                },
                dag=dag,
            )
    else:
        task_id = "http_trigger"
        PythonOperator(
            task_id=task_id,
            python_callable=_http_trigger,
            op_kwargs={
                "url": trigger["url"],
                "method": trigger["method"],
                "query_params": trigger["query_params"] or None,
                "headers": trigger["headers"] or None,
                "body": trigger["body"],
                "body_type": trigger["body_type"],
            },
            dag=dag,
        )
    return dag


def load_dags_from_xml(definitions_dir: Path | None = None) -> list[DAG]:
    """
    Scan a directory for *.xml files, parse each and create DAGs.
    Returns list of created DAGs. Also registers them in globals() so Airflow discovers them.
    """
    dir_path = definitions_dir or DEFINITIONS_DIR
    if not dir_path.is_dir():
        return []

    dags: list[DAG] = []
    for xml_path in sorted(dir_path.glob("*.xml")):
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except ET.ParseError:
            continue
        source = xml_path.name
        for dag_el in root.findall("dag"):
            try:
                dag = create_dag_from_xml_element(dag_el, source)
                if dag is not None:
                    dags.append(dag)
                    globals()[dag.dag_id] = dag
            except (ValueError, KeyError) as e:
                # Log and skip invalid DAG so one bad XML doesn't break others
                import logging
                logging.getLogger(__name__).warning(
                    "Skipping DAG from %s: %s", source, e
                )
                continue
    return dags


# Load all DAGs from XML at import time so Airflow discovers them
load_dags_from_xml()
