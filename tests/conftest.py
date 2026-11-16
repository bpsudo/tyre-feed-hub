import os

# On GitHub Actions, Typer forces colors and boxes in error messages, which breaks the text checks.
# Set before Typer is imported by the test modules.
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"
