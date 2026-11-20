"""Development entrypoint: ``python -m psychtool.server``."""

from __future__ import annotations

import uvicorn

from psychtool.server.app import app


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
