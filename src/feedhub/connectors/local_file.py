from feedhub.db import PROJECT_ROOT


def folder_path(source):
    return PROJECT_ROOT / source["local_dir"]


def describe(source):
    return f"local folder {folder_path(source)}"


def fetch_files(source, skip_names=()):
    """Return (name, content) for each file of the folder not in skip_names, sorted by name."""
    folder = folder_path(source)
    if not folder.is_dir():
        raise FileNotFoundError(f"folder not found: {folder}")
    files = []
    for path in sorted(folder.glob(source["file_pattern"])):
        if path.name not in skip_names:
            files.append((path.name, path.read_bytes()))
    return files
