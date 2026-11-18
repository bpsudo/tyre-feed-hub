import base64
import binascii
import re
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from feedhub import checks, db, onboarding, reports
from feedhub.mapping import CONFIG_DIR, supplier_codes
from feedhub.tyre_size import format_size, parse_size

WEB_DIR = Path(__file__).resolve().parent
SEVERITIES = ["critical", "warning", "info"]
STATUS_LABELS = {"success": "OK", "partial": "Partiel", "failed": "Échec"}
# The file goes back and forth in a hidden form field, which the form parser limits to 1 MB.
MAX_SAMPLE_BYTES = 500_000


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


def supplier_form_errors(code, name, existing_codes):
    errors = []
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", code):
        errors.append("Le code doit faire 2 à 10 caractères, lettres majuscules et chiffres, "
                      "en commençant par une lettre.")
    elif code in existing_codes:
        errors.append(f"Le code {code} est déjà utilisé.")
    if not name:
        errors.append("Le nom du fournisseur est obligatoire.")
    return errors


def known_brands(db_path):
    """Brands of the catalogue, with the query used. Empty when the database is not ready."""
    query = reports.page_query("known_brands")
    try:
        with closing(db.open_db(db_path)) as connection:
            return [row["brand"] for row in query.fetch(connection, {})], query
    except db.DatabaseNotReady:
        return [], query


def create_app(db_path=db.DEFAULT_DB_PATH, thresholds=None, demo=False,
               config_dir=CONFIG_DIR, docs_dir=onboarding.DOCS_DIR):
    """demo=True: the new supplier page shows the files it would write, without writing them."""
    thresholds = thresholds or checks.load_thresholds()
    app = FastAPI(title="Tyre Feed Hub", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")
    templates.env.globals["status_labels"] = STATUS_LABELS
    templates.env.globals["demo"] = demo

    def render(request, template, **context):
        return templates.TemplateResponse(request, template, context)

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
        oldest_allowed = checks.oldest_allowed_date(thresholds, datetime.now(timezone.utc)).isoformat()
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
            for offer in offers:
                # Offer of a supplier whose newest data is too old: price and stock may be wrong.
                offer["is_stale"] = offer["data_date"] is not None and offer["data_date"] < oldest_allowed
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

    @app.get("/nouveau-fournisseur", response_class=HTMLResponse)
    def new_supplier_form(request: Request):
        return render(request, "new_supplier.html", analysis=None, errors=[], code="", name="")

    @app.post("/nouveau-fournisseur", response_class=HTMLResponse)
    async def new_supplier(request: Request):
        form = await request.form()
        code = str(form.get("code", "")).strip().upper()
        name = str(form.get("name", "")).strip()
        upload = form.get("file")
        if upload is not None and getattr(upload, "filename", ""):
            content = await upload.read(MAX_SAMPLE_BYTES + 1)
            file_name = upload.filename
        else:
            try:
                content = base64.b64decode(str(form.get("content", "")), validate=True)
            except binascii.Error:
                content = b""
            file_name = str(form.get("file_name", ""))

        def start_again(message):
            return render(request, "new_supplier.html", analysis=None, errors=[message], code=code, name=name)

        if not content:
            return start_again("Choisissez un fichier d'exemple (CSV, XML ou JSON).")
        if len(content) > MAX_SAMPLE_BYTES:
            return start_again("Le fichier d'exemple est limité à 500 Ko : quelques centaines de lignes suffisent.")

        brands, brands_query = known_brands(db_path)
        try:
            analysis = onboarding.analyze(content, file_name, brands)
        except (ValueError, ET.ParseError, UnicodeDecodeError) as error:
            return start_again(f"Fichier illisible : {error}")

        # First visit: the proposal. After that: the columns chosen in the form.
        if "column_ean" in form:
            columns = {field: str(form.get(f"column_{field}", "")) for field in onboarding.FIELDS}
            transforms = {field: str(form.get(f"transform_{field}", "")) for field in ("size", "price_eur")}
        else:
            columns = analysis["proposal"]
            transforms = None
        mapping = onboarding.build_mapping(analysis, code or "NEW", name or "Nouveau fournisseur",
                                           columns, transforms)
        errors = supplier_form_errors(code, name, supplier_codes(config_dir))
        missing = onboarding.missing_fields(mapping["columns"])
        if missing:
            labels = ", ".join(onboarding.FIELD_LABELS[field] for field in missing)
            errors.append(f"Champs obligatoires sans colonne : {labels}.")

        saved = None
        if form.get("action") == "save" and not errors and not demo:
            try:
                saved = onboarding.save_supplier_files(mapping, config_dir, docs_dir)
            except FileExistsError as error:
                errors.append(str(error))

        return render(
            request, "new_supplier.html",
            analysis=analysis,
            code=code,
            name=name,
            mapping=mapping,
            columns=mapping["columns"],
            transforms=mapping.get("transforms", {}),
            fields=onboarding.FIELD_LABELS,
            unknown_values=onboarding.value_maps(analysis, mapping["columns"])[1],
            result=onboarding.dry_run(content, mapping),
            toml=onboarding.mapping_to_toml(mapping),
            doc=onboarding.supplier_doc(mapping),
            content=base64.b64encode(content).decode("ascii"),
            errors=errors,
            save_requested=form.get("action") == "save",
            saved=saved,
            queries=[shown_query(brands_query, {})],
        )

    return app
