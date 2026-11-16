import re

from feedhub.db import PROJECT_ROOT

QUERIES_DIR = PROJECT_ROOT / "sql" / "queries"
PAGES_DIR = PROJECT_ROOT / "sql" / "pages"


class Query:
    def __init__(self, path):
        self.path = path
        prefix = path.name.split("_", 1)[0]
        # Only the files of sql/queries are numbered.
        self.number = int(prefix) if prefix.isdigit() else None
        self.sql = path.read_text(encoding="utf-8")
        # The first line of each file is the business question, as a comment.
        self.question = self.sql.splitlines()[0].removeprefix("--").strip()

    @property
    def parameters(self):
        """Names of the :parameters of the query, in order of first use."""
        code = "\n".join(line.split("--", 1)[0] for line in self.sql.splitlines())
        return list(dict.fromkeys(re.findall(r"(?<!:):([a-z_]+)", code)))

    @property
    def optional_parameters(self):
        # Written ":supplier IS NULL OR s.code = :supplier" in the query: NULL means no filter.
        return {name for name in self.parameters if f":{name} IS NULL" in self.sql}

    def run(self, connection, values):
        cursor = connection.execute(self.sql, {name: values.get(name) for name in self.parameters})
        columns = [column[0] for column in cursor.description]
        return columns, [tuple(row) for row in cursor.fetchall()]


    def fetch(self, connection, values):
        """Run the query and return one dictionary per row."""
        columns, rows = self.run(connection, values)
        return [dict(zip(columns, row)) for row in rows]


def all_queries(queries_dir=QUERIES_DIR):
    return [Query(path) for path in sorted(queries_dir.glob("[0-9][0-9]_*.sql"))]


def page_query(name, pages_dir=PAGES_DIR):
    return Query(pages_dir / f"{name}.sql")


def find_query(number, queries_dir=QUERIES_DIR):
    for query in all_queries(queries_dir):
        if query.number == number:
            return query
    return None


def cell(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def format_table(columns, rows, max_width=30):
    """Plain text table, one line per row."""
    table = [columns] + [[cell(value)[:max_width] for value in row] for row in rows]
    widths = [max(len(line[i]) for line in table) for i in range(len(columns))]
    lines = ["  ".join(text.ljust(width) for text, width in zip(line, widths)).rstrip() for line in table]
    lines.insert(1, "  ".join("-" * width for width in widths))
    return "\n".join(lines)
