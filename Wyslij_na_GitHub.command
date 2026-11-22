#!/bin/zsh
cd "$(dirname "$0")"

if ! git config user.name >/dev/null; then
  read "gname?Podaj swoje imię lub login GitHub (np. leszekwojciechowski82-sudo): "
  git config user.name "${gname:-leszekwojciechowski82-sudo}"
fi

if ! git config user.email >/dev/null; then
  read "gemail?Podaj swój email z GitHuba: "
  git config user.email "${gemail:-user@users.noreply.github.com}"
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  read "rurl?Wklej link do pustego repozytorium z GitHub.com: "
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
echo "UWAGA: Gdy zapyta o Password, wklej wygenerowany TOKEN z GitHuba (zaczyna się od ghp_ lub github_pat_), NIE zwykłe hasło do konta."
echo ""

if git push -u origin main; then
  echo ""
  echo "SUKCES! Pliki wysłane na GitHuba."
  echo "Teraz na GitHub.com wejdź w Settings -> Pages -> Branch: main -> Folder: /docs -> Save."
else
  echo ""
  echo "BŁĄD WYSYŁKI: Upewnij się, że w polu Password wkleiłeś TOKEN (ghp_... lub github_pat_...) z uprawnieniami repo + workflow."
fi
read "?Naciśnij Enter, aby zamknąć..."
