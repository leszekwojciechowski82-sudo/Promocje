#!/bin/zsh
cd "$(dirname "$0")"

if ! git config user.name >/dev/null; then
  git config user.name "leszekwojciechowski82-sudo"
fi

if ! git config user.email >/dev/null; then
  git config user.email "leszekwojciechowski82@gmail.com"
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  read "rurl?Wklej link do pustego repozytorium z GitHub.com: "
  rurl=$(printf '%s' "$rurl" | tr -d '[:space:]')
  if [[ -z "$rurl" ]]; then
    echo "Nie podano linku. Przerywam."
    exit 1
  fi
  git remote add origin "$rurl"
fi

git add -A
if ! git diff --cached --quiet; then
  git commit -m "Aktualizacja Monitor Okazji by Luis"
fi

echo ""
echo "Próba wysyłki na GitHuba..."
if GIT_TERMINAL_PROMPT=0 git push -u origin main 2>/dev/null; then
  echo ""
  echo "SUKCES! Pliki wysłane na GitHuba."
  echo "Teraz na GitHub.com wejdź w Settings -> Pages -> Branch: main -> Folder: /docs -> Save."
  read "?Naciśnij Enter, aby zamknąć..."
  exit 0
fi

echo ""
echo "Potrzebne jednorazowe zapisanie tokena z GitHuba (zaczyna się od ghp_)."
echo "Wskazówka: jeśli masz już skopiowany token w schowku, wystarczy nacisnąć Enter."
read -s "raw_token?Wklej TOKEN (lub naciśnij Enter, aby użyć ze schowka): "
echo ""

clean_token=$(printf '%s' "$raw_token" | tr -d '[:space:]')
if [[ -z "$clean_token" ]]; then
  clip_token=$(pbpaste | tr -d '[:space:]')
  if [[ "$clip_token" == ghp_* || "$clip_token" == github_pat_* ]]; then
    clean_token="$clip_token"
    echo "Pobrano token ze schowka."
  fi
fi

if [[ -z "$clean_token" ]]; then
  echo "BŁĄD: Nie podano ani nie wykryto tokena (ghp_...) w schowku."
  read "?Naciśnij Enter, aby zamknąć..."
  exit 1
fi

printf "protocol=https\nhost=github.com\nusername=leszekwojciechowski82-sudo\npassword=%s\n\n" "$clean_token" | git credential approve

if GIT_TERMINAL_PROMPT=0 git push -u origin main; then
  echo ""
  echo "SUKCES! Pliki wysłane na GitHuba i logowanie zapamiętane."
  echo "Teraz na GitHub.com wejdź w Settings -> Pages -> Branch: main -> Folder: /docs -> Save."
else
  echo ""
  echo "BŁĄD WYSYŁKI: Upewnij się, że token ma uprawnienia 'repo' oraz 'workflow' i nie wygasł."
  printf "protocol=https\nhost=github.com\nusername=leszekwojciechowski82-sudo\n\n" | git credential reject
fi
read "?Naciśnij Enter, aby zamknąć..."
