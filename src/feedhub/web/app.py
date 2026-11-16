from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from feedhub import checks, db, reports
from feedhub.tyre_size import format_size, parse_size

WEB_DIR = Path(__file__).resolve().parent
SEVERITIES = ["critical", "warning", "info"]
STATUS_LABELS = {"success": "OK", "partial": "Partiel", "failed": "Échec"}


def status_colour(row):
    """green, orange or red for a dashboard row."""
    if row["status"] in (None, "failed") or row["is_stale"] or row["critical_count"]:
        return "red"
    if row["status"] == "partial":
        return "orange"
    return "green"


def shown_query(query, values):
    """What the page prints in its SQL block: the query and the values given to it."""
    return {"sql": query.sql, "values": {name: values.get(name) for name in query.parameters}}


def blank_to_none(value):
    # An empty filter field means no filter.
    return value.strip() or None


def create_app(db_path=db.DEFAULT_DB_PATH, thresholds=None):
    thresholds = thresholds or checks.load_thresholds()
    app = FastAPI(title="Tyre Feed Hub", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")
    templates.env.globals["status_labels"] = STATUS_LABELS

    def render(request, name, **context):
        return templates.TemplateResponse(request, name, context)

    @app.exception_handler(db.DatabaseNotReady)
    def database_not_ready(request, error):
        return templates.TemplateResponse(request, "error.html", {"message": str(error)}, status_code=503)

    @app.exception_handler(StarletteHTTPException)
    def http_error(request, error):
        message = "Page introuvable." if error.status_code == 404 else str(error.detail)
        return templates.TemplateResponse(request, "error.html", {"message": message},
                                          status_code=error.status_code)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request):
        oldest_allowed = checks.oldest_allowed_date(thresholds, datetime.now(timezone.utc))
        suppliers_query = reports.page_query("dashboard")
        history_query = reports.find_query(5)
        suppliers_values = {"oldest_allowed_date": oldest_allowed.isoformat()}
        with closing(db.open_db(db_path)) as connection:
            suppliers = suppliers_query.fetch(connection, suppliers_values)
            history = history_query.fetch(connection, {})
        for row in suppliers:
            row["colour"] = status_colour(row)
        return render(
            request, "dashboard.html",
            suppliers=suppliers,
            history=history,
            oldest_allowed=oldest_allowed,
            queries=[shown_query(suppliers_query, suppliers_values), shown_query(history_query, {})],
        )

    @app.get("/anomalies", response_class=HTMLResponse)
    def anomalies(request: Request, supplier: str = "", rule_code: str = "", severity: str = "",
                  data_date: str = ""):
        query = reports.page_query("anomalies")
        values = {
            "supplier": blank_to_none(supplier),
            "rule_code": blank_to_none(rule_code),
            "severity": blank_to_none(severity),
            "data_date": blank_to_none(data_date),
        }
        with closing(db.open_db(db_path)) as connection:
            rows = query.fetch(connection, values)
            options = {
                "supplier": [r[0] for r in connection.execute("SELECT code FROM suppliers ORDER BY code")],
                "rule_code": [r[0] for r in connection.execute(
                    "SELECT DISTINCT rule_code FROM anomalies ORDER BY rule_code")],
                "data_date": [r[0] for r in connection.execute(
                    """
                    SELECT DISTINCT COALESCE(r.feed_date, DATE(a.created_at)) AS data_date
                    FROM anomalies AS a LEFT JOIN import_runs AS r ON r.id = a.run_id
                    ORDER BY data_date DESC
                    """)],
                "severity": SEVERITIES,
            }
        return render(request, "anomalies.html", rows=rows, values=values, options=options,
                      queries=[shown_query(query, values)])

    @app.get("/imports/{run_id}", response_class=HTMLResponse)
    def import_run(request: Request, run_id: int):
        run_query = reports.page_query("import_run")
        anomalies_query = reports.page_query("import_run_anomalies")
        values = {"run_id": run_id}
        with closing(db.open_db(db_path)) as connection:
            runs = run_query.fetch(connection, values)
            if not runs:
                raise HTTPException(status_code=404)
            rows = anomalies_query.fetch(connection, values)
        for row in rows:
            # Row rejections are written "row N: message | raw row".
            message, _, raw = (row["details"] or "").partition(" | ")
            row["message"], row["raw"] = message, raw
        return render(request, "import_run.html", run=runs[0], anomalies=rows,
                      queries=[shown_query(run_query, values), shown_query(anomalies_query, values)])

    @app.get("/search", response_class=HTMLResponse)
    def search(request: Request, size: str = ""):
        search_query = reports.find_query(6)
        top_query = reports.find_query(10)
        parsed = parse_size(size.strip()) if size.strip() else None
        values = {}
        offers = []
        with closing(db.open_db(db_path)) as connection:
            if parsed:
                values = {"width": parsed.width, "aspect_ratio": parsed.aspect_ratio,
                          "rim_diameter": parsed.rim_diameter}
                offers = search_query.fetch(connection, values)
            top_sizes = top_query.fetch(connection, {})
        return render(
            request, "search.html",
            size=size,
            parsed=format_size(*parsed[:3]) if parsed else None,
            unreadable=bool(size.strip()) and parsed is None,
            offers=offers,
            top_sizes=top_sizes,
            queries=[shown_query(search_query, values), shown_query(top_query, {})],
        )

    return app
