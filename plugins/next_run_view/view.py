"""Custom FAB view: DAG list with next execution time (next_dagrun_create_after)."""
from __future__ import annotations

from flask_appbuilder import BaseView, expose

from airflow.models.dag import DagModel
from airflow.utils import timezone
from airflow.utils.session import provide_session


def _to_hkt(dt):
    """Convert datetime to Hong Kong timezone. Handles None and naive datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = timezone.make_aware(dt, timezone.UTC)
    return dt.astimezone(timezone.parse_timezone("Asia/Hong_Kong"))


class NextRunView(BaseView):
    """View displaying DAGs with their actual next execution time."""

    default_view = "list"

    @expose("/")
    def list(self):
        """Render DAG list with next_dagrun_create_after."""
        dags = self._get_dags_with_next_run()
        return self.render_template(
            "next_run_view/dag_list.html",
            dags=dags,
        )

    @provide_session
    def _get_dags_with_next_run(self, session=None):
        """Query DagModel for dag_id, is_paused, next_dagrun_create_after, next_dagrun_data_interval_start."""
        rows = (
            session.query(
                DagModel.dag_id,
                DagModel.is_paused,
                DagModel.next_dagrun_create_after,
                DagModel.next_dagrun_data_interval_start,
            )
            .filter(DagModel.is_active == True)
            .order_by(DagModel.dag_id)
            .all()
        )
        return [
            {
                "dag_id": r.dag_id,
                "is_paused": r.is_paused,
                "next_run_time": _to_hkt(r.next_dagrun_create_after),
                "data_interval_start": _to_hkt(r.next_dagrun_data_interval_start),
            }
            for r in rows
        ]
