"""
Runs model-written Python in a subprocess: stripped environment (no API keys),
CPU/memory/file-size limits, a per-session working directory, and the lab toolkit on the path.
"""

import json
import os
import re
import resource
import site
import subprocess
import sys
import tempfile

import pandas as pd

from bot.config import ASSETS_DIR, BRAIN_DIR
from bot.lab.data import PRICES_DIR, UNIVERSE_PATH

SANDBOX_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sandbox_lib")
LAB_DIR = os.path.join(BRAIN_DIR, "lab")
LIBRARY_DIR = os.path.join(LAB_DIR, "library")
LIBRARY_INDEX = os.path.join(LIBRARY_DIR, "index.json")
HOLDOUT_DAYS = 252
MAX_OUTPUT = 10000


def holdout_start() -> str:
    """First date of the most recent ~1 trading year, reserved for judging signals."""
    idx = pd.read_parquet(os.path.join(PRICES_DIR, "close.parquet"), columns=["SPY"]).index
    return str(idx[-HOLDOUT_DAYS].date()) if len(idx) > HOLDOUT_DAYS * 2 else str(idx[len(idx) // 2].date())


def _limits():
    resource.setrlimit(resource.RLIMIT_AS, (8 * 1024 ** 3, 8 * 1024 ** 3))
    resource.setrlimit(resource.RLIMIT_CPU, (600, 600))
    resource.setrlimit(resource.RLIMIT_FSIZE, (500 * 1024 ** 2, 500 * 1024 ** 2))


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    half = MAX_OUTPUT // 2
    return f"{text[:half]}\n... [{len(text) - MAX_OUTPUT} chars truncated] ...\n{text[-half:]}"


def _ensure_library():
    os.makedirs(LIBRARY_DIR, exist_ok=True)
    init = os.path.join(LIBRARY_DIR, "__init__.py")
    if not os.path.exists(init):
        open(init, "w").close()


class Sandbox:
    def __init__(self, workdir: str | None = None, research: bool = True):
        """research=True hides the holdout year entirely: cells only see a truncated copy of the prices."""
        self.workdir = workdir or tempfile.mkdtemp(prefix="andiamo-lab-")
        self.fig_dir = os.path.join(self.workdir, "figures")
        os.makedirs(self.fig_dir, exist_ok=True)
        self.cells = 0
        self.holdout = holdout_start()
        self.prices_dir = PRICES_DIR
        if research:
            self.prices_dir = os.path.join(self.workdir, "prices")
            os.makedirs(self.prices_dir, exist_ok=True)
            cutoff = pd.Timestamp(self.holdout)
            for fname in os.listdir(PRICES_DIR):
                if fname.endswith(".parquet"):
                    df = pd.read_parquet(os.path.join(PRICES_DIR, fname))
                    df[df.index < cutoff].to_parquet(os.path.join(self.prices_dir, fname))
        _ensure_library()

    def env(self) -> dict:
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.workdir,
            "LANG": "C.UTF-8",
            "MPLBACKEND": "Agg",
            # HOME is redirected, so pass the parent's package dirs through explicitly
            "PYTHONPATH": os.pathsep.join([SANDBOX_LIB, LAB_DIR, *site.getsitepackages(), site.getusersitepackages()]),
            "ANDIAMO_PRICES_DIR": self.prices_dir,
            "ANDIAMO_ASSETS_DIR": ASSETS_DIR,
            "ANDIAMO_UNIVERSE_PATH": UNIVERSE_PATH,
            "ANDIAMO_FIG_DIR": self.fig_dir,
            "ANDIAMO_HOLDOUT_START": self.holdout,
        }

    def run(self, code: str, timeout: int = 300, prelude: bool = True) -> tuple[int, str]:
        self.cells += 1
        path = os.path.join(self.workdir, f"cell_{self.cells}.py")
        with open(path, "w") as f:
            f.write(("from andiamo_lab import *\n" if prelude else "") + code)
        try:
            proc = subprocess.run(
                [sys.executable, path], cwd=self.workdir, env=self.env(),
                capture_output=True, text=True, timeout=timeout, preexec_fn=_limits,
            )
            out = proc.stdout + (f"\n[stderr]\n{proc.stderr}" if proc.stderr.strip() else "")
            return proc.returncode, _truncate(out.strip() or "(no output — print() what you want to see)")
        except subprocess.TimeoutExpired:
            return -1, f"[timeout after {timeout}s — sample less data or vectorize]"

    def figures(self) -> list[str]:
        return sorted(os.listdir(self.fig_dir))


def load_library_index() -> dict:
    try:
        with open(LIBRARY_INDEX) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_to_library(sandbox: Sandbox, name: str, code: str, description: str) -> str:
    name = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    if not name or name[0].isdigit():
        return "Invalid module name — use snake_case starting with a letter."
    _ensure_library()
    path = os.path.join(LIBRARY_DIR, f"{name}.py")
    previous = open(path).read() if os.path.exists(path) else None
    with open(path, "w") as f:
        f.write(f'"""{description.strip()}"""\n\n{code.strip()}\n')
    rc, out = sandbox.run(f"import library.{name} as m\nprint(sorted(n for n in dir(m) if not n.startswith('_')))")
    if rc != 0:
        if previous is None:
            os.remove(path)
        else:
            with open(path, "w") as f:
                f.write(previous)
        return f"Import failed; library unchanged:\n{out}"
    index = load_library_index()
    index[name] = {"description": description.strip(), "exports": out.strip()}
    with open(LIBRARY_INDEX, "w") as f:
        json.dump(index, f, indent=2)
    return f"Saved library.{name}. Import in future cells with `from library import {name}`. Exports: {out.strip()}"
