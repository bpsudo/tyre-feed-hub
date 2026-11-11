import io

from feedhub.connectors import sftp

SOURCE = {
    "host_env": "TEST_SFTP_HOST",
    "port_env": "TEST_SFTP_PORT",
    "user_env": "TEST_SFTP_USER",
    "password_env": "TEST_SFTP_PASSWORD",
    "remote_dir": "/upload",
    "file_pattern": "stock_*.csv",
}


class FakeSftpClient:
    def __init__(self, files):
        self.files = files
        self.opened = []

    def listdir(self, path):
        return list(self.files)

    def open(self, path, mode):
        self.opened.append(path)
        return io.BytesIO(self.files[path.rsplit("/", 1)[1]])


def test_download_only_new_matching_files():
    client = FakeSftpClient({
        "stock_20260120.csv": b"b",
        "stock_20260119.csv": b"a",
        "readme.txt": b"c",
    })
    files = sftp.download_new_files(client, "/upload", "stock_*.csv", {"stock_20260119.csv"})
    assert files == [("stock_20260120.csv", b"b")]
    assert client.opened == ["/upload/stock_20260120.csv"]


def test_without_host_reads_local_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_SFTP_HOST", raising=False)
    (tmp_path / "stock_20260120.csv").write_bytes(b"content")
    source = {**SOURCE, "local_dir": str(tmp_path)}

    assert sftp.fetch_files(source) == [("stock_20260120.csv", b"content")]
    assert "TEST_SFTP_HOST not set" in sftp.describe(source)


def test_server_settings_from_environment(monkeypatch):
    monkeypatch.setenv("TEST_SFTP_HOST", "localhost")
    monkeypatch.setenv("TEST_SFTP_PORT", "2222")
    monkeypatch.setenv("TEST_SFTP_USER", "nord")
    monkeypatch.setenv("TEST_SFTP_PASSWORD", "secret")

    assert sftp.server_settings(SOURCE)["port"] == 2222
    assert sftp.describe(SOURCE) == "sftp://nord@localhost:2222/upload"
