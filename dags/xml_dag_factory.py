"""
XML-driven DAG factory: create Airflow DAGs from XML files without writing Python.
Edit XML in dags/dag_definitions/ to add new DAGs (schedule, trigger URL, method, parameters).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago

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
    if not url:
        raise ValueError("trigger must have url")
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

    trigger_el = dag_el.find("trigger")
    if trigger_el is None:
        return None
    trigger = _parse_trigger(trigger_el)

    dag = DAG(
        dag_id=dag_id,
        default_args=DEFAULT_ARGS,
        schedule=schedule,
        start_date=days_ago(1),
        tags=["xml-generated"],
        doc_md=description,
    )

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
