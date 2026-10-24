import argparse
import json
import time

from app.db import initialize
from collector.service import collect


def main():
    parser = argparse.ArgumentParser(description="Coleta local de vagas Greenhouse")
    parser.add_argument("--force", action="store_true", help="Ignora o intervalo de 48 horas")
    parser.add_argument(
        "--watch", action="store_true", help="Verifica coletas pendentes a cada minuto"
    )
    args = parser.parse_args()
    initialize()
    while True:
        result = collect(force=args.force)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not args.watch:
            raise SystemExit(1 if any(r["status"] == "error" for r in result["results"]) else 0)
        args.force = False
        time.sleep(60)


if __name__ == "__main__":
    main()
