#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$project_dir"

compose_up_args=(up --detach --wait --wait-timeout 120)
open_browser=true
run_collection=true
for argument in "$@"; do
  case "$argument" in
    --build) compose_up_args+=(--build) ;;
    --no-browser) open_browser=false ;;
    --no-collect) run_collection=false ;;
    --help|-h)
      echo 'Uso: ./iniciar.sh [--build] [--no-browser] [--no-collect]'
      echo 'Inicia o aplicativo, coleta fontes pendentes e abre o navegador.'
      echo 'Use --build após mudar o código. A primeira execução constrói a imagem.'
      exit 0
      ;;
    *) echo "Opção desconhecida: $argument" >&2; exit 2 ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo 'Docker não encontrado. Instale Docker Engine com Compose v2 ou Docker Desktop.' >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo 'Docker Compose v2 não encontrado. Verifique a instalação do plugin Compose.' >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo 'Não foi possível acessar o Docker. Verifique se ele está iniciado e acessível ao seu usuário.' >&2
  exit 1
fi

export LOCAL_UID="${LOCAL_UID:-$(id -u)}"
export LOCAL_GID="${LOCAL_GID:-$(id -g)}"
mkdir -p backend/data

echo 'Iniciando Market Hunter…'
if ! docker compose "${compose_up_args[@]}" app; then
  echo 'Falha ao iniciar. Diagnóstico: docker compose logs --tail=100 app' >&2
  exit 1
fi

published_address="$(docker compose port app 8000)"
app_url="http://${published_address}"
echo "Aplicativo disponível em $app_url"

if "$run_collection"; then
  echo 'Consultando fontes com atualização pendente…'
  if ! docker compose exec -T app python -m collector; then
    echo 'A coleta encontrou uma falha. O aplicativo continua disponível; veja Fontes de vagas.' >&2
  fi
fi

if "$open_browser"; then
  if [[ "$(uname -s)" == Darwin ]] && command -v open >/dev/null 2>&1; then
    open "$app_url" >/dev/null 2>&1 || echo "Abra no navegador: $app_url"
  elif command -v xdg-open >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    xdg-open "$app_url" >/dev/null 2>&1 &
  else
    echo "Abra no navegador: $app_url"
  fi
fi

echo 'Para encerrar: docker compose stop app'
