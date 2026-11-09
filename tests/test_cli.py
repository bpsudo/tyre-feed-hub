from typer.testing import CliRunner

from feedhub.cli import app

runner = CliRunner()


def test_init_db_creates_the_file(tmp_path):
    db_path = tmp_path / "sub" / "feedhub.db"

    result = runner.invoke(app, ["init-db", "--db", str(db_path)])

    assert result.exit_code == 0
    assert db_path.exists()
