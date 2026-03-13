"""Airflow plugin: DAG list with next execution time (next_dagrun_create_after)."""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint

from airflow.plugins_manager import AirflowPlugin

from next_run_view.view import NextRunView


# Blueprint for template resolution (templates/next_run_view/)
_plugin_dir = Path(__file__).resolve().parent
bp = Blueprint(
    "next_run_view",
    __name__,
    template_folder=str(_plugin_dir / "templates"),
    static_folder="static",
    static_url_path="/static/next_run_view",
)


class NextRunViewPlugin(AirflowPlugin):
    """Register custom DAG list view showing next execution time."""

    name = "Next Run View"
    flask_blueprints = [bp]
    appbuilder_views = [
        {
            "name": "DAG 列表（執行時間）",
            "category": "Browse",
            "view": NextRunView(),
        }
    ]
