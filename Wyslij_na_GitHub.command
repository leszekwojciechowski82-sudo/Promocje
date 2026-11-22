#!/bin/zsh
cd "$(dirname "$0")"

if ! git config user.name >/dev/null; then
  read "gname?Podaj swoje imię lub login GitHub (np. Luis): "
  git config user.name "${gname:-Luis}"
fi

if ! git config user.email >/dev/null; then
  read "gemail?Podaj swój email z GitHuba: "
  git config user.email "${gemail:-user@users.noreply.github.com}"
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  read "rurl?Wklej link do pustego repozytorium z GitHub.com (np. https://github.com/login/monitor-okazji.git): "
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

git push -u origin main
echo ""
echo "Gotowe! Teraz na GitHub.com wejdz w Settings -> Pages -> Branch: main -> Folder: /docs -> Save."
read "?Nacisnij Enter, aby zamknac..."
