"""Consistent SQLite backup, including pending WAL content."""

import argparse
import sqlite3
from pathlib import Path

from app.db import connect, initialize


def main():
    parser = argparse.ArgumentParser(description="Cria um backup consistente do Market Hunter")
    parser.add_argument("destination", type=Path, help="Caminho de um novo arquivo de backup")
    args = parser.parse_args()
    if args.destination.exists():
        parser.error("O destino já existe; escolha outro caminho")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    initialize()
    with connect() as source:
        destination = sqlite3.connect(args.destination)
        try:
            source.backup(destination)
        finally:
            destination.close()
    print(f"Backup salvo em {args.destination.resolve()}")


if __name__ == "__main__":
    main()
