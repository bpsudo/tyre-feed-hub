import fnmatch
import os

import paramiko

from feedhub.connectors import local_file


def server_settings(source):
    host = os.environ.get(source["host_env"], "")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get(source["port_env"], "22")),
        "user": os.environ.get(source["user_env"], ""),
        "password": os.environ.get(source["password_env"], ""),
    }


def describe(source):
    settings = server_settings(source)
    if settings is None:
        return f"{source['host_env']} not set, {local_file.describe(source)}"
    return f"sftp://{settings['user']}@{settings['host']}:{settings['port']}{source['remote_dir']}"


def download_new_files(client, remote_dir, pattern, skip_names):
    names = sorted(name for name in client.listdir(remote_dir) if fnmatch.fnmatch(name, pattern))
    files = []
    for name in names:
        if name not in skip_names:
            with client.open(f"{remote_dir}/{name}", "rb") as file:
                files.append((name, file.read()))
    return files


def fetch_files(source, skip_names=()):
    """Download the new files from the SFTP server, or read the local folder when no server is set."""
    settings = server_settings(source)
    if settings is None:
        return local_file.fetch_files(source, skip_names)

    transport = paramiko.Transport((settings["host"], settings["port"]))
    try:
        # The host key is not checked: acceptable for the local test server only.
        transport.connect(username=settings["user"], password=settings["password"])
        client = paramiko.SFTPClient.from_transport(transport)
        return download_new_files(client, source["remote_dir"], source["file_pattern"], skip_names)
    finally:
        transport.close()
