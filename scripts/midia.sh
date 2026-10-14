#!/usr/bin/env bash
# Imagens dos posts ficam no branch "midia", recriado a cada vez SEM HISTÓRICO.
# Assim o repositório não cresce a cada post: o branch principal guarda só textos
# e estado, e o "midia" guarda só as imagens dos posts recentes ou pendentes.
#
#   bash scripts/midia.sh restaurar   baixa as imagens do branch midia para data/drafts/
#   bash scripts/midia.sh publicar    recria o branch midia com as imagens atuais
#
# URL pública das imagens do Instagram:
#   https://raw.githubusercontent.com/<usuario>/<repo>/midia/<id>/slide_01.jpg
set -euo pipefail
acao="${1:?uso: bash scripts/midia.sh restaurar|publicar}"
raiz="$(git rev-parse --show-toplevel)"
cd "$raiz"

case "$acao" in
  restaurar)
    if git ls-remote --exit-code --heads origin midia >/dev/null 2>&1; then
      git fetch -q --depth=1 origin midia
      mkdir -p data/drafts
      git archive FETCH_HEAD | tar -x -C data/drafts
      echo "Mídia restaurada do branch midia ($(find data/drafts -name '*.jpg' | wc -l | tr -d ' ') imagens)"
    else
      echo "O branch midia ainda não existe (primeira execução)"
    fi
    ;;
  publicar)
    python main.py midia-branch --saida "$raiz/_midia"
    if [ -z "$(find _midia -name '*.jpg' 2>/dev/null | head -1)" ]; then
      echo "Nenhuma imagem para publicar"
      rm -rf _midia
      exit 0
    fi
    git config user.name >/dev/null || git config user.name "como-vota-bot"
    git config user.email >/dev/null || git config user.email "bot@users.noreply.github.com"
    indice="$(mktemp)"; rm -f "$indice"
    # índice temporário + commit sem pai: nada do branch principal é tocado
    arvore="$(cd _midia && GIT_INDEX_FILE="$indice" git --git-dir="$raiz/.git" --work-tree=. add -A . \
              && GIT_INDEX_FILE="$indice" git --git-dir="$raiz/.git" write-tree)"
    commit="$(echo "Mídia dos posts recentes" | git commit-tree "$arvore")"
    git push -q --force origin "$commit:refs/heads/midia"
    rm -rf _midia "$indice"
    echo "Branch midia atualizado ($commit)"
    ;;
  *)
    echo "ação desconhecida: $acao" >&2; exit 2 ;;
esac
