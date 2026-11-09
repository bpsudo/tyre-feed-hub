from typer.testing import CliRunner

from feedhub.cli import app

runner = CliRunner()


def test_init_db_creates_the_file(tmp_path):
    db_path = tmp_path / "sub" / "feedhub.db"

    result = runner.invoke(app, ["init-db", "--db", str(db_path)])

    assert result.exit_code == 0
    assert db_path.exists()


def test_generate_writes_files(tmp_path):
    result = runner.invoke(
        app, ["generate", "--days", "2", "--end-date", "2026-01-20", "--output", str(tmp_path)]
    )

    assert result.exit_code == 0
    assert (tmp_path / "nord" / "stock_20260120.csv").exists()


def test_scenarios_need_three_days(tmp_path):
    result = runner.invoke(
        app, ["generate", "--days", "2", "--scenario", "api-down", "--output", str(tmp_path)]
    )

    assert result.exit_code != 0


def test_unknown_scenario_is_refused(tmp_path):
    result = runner.invoke(
        app, ["generate", "--days", "3", "--scenario", "flood", "--output", str(tmp_path)]
    )

    assert result.exit_code != 0
