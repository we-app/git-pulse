# git-pulse i Slack (svenska, macOS)

Klistra in det här i Slack för att dela vidare.

---

## Installera git-pulse på 30 sekunder (macOS)

git-pulse visar en sammanfattning av vad som hänt i ett repo varje gång du öppnar Claude Code. Funkar både i CLI och Desktop-appen.

### 1. Öppna Terminal och klistra in

```
curl -fsSL https://raw.githubusercontent.com/we-app/git-pulse/main/install.sh | bash
```

Tryck Enter. Klart på några sekunder.

### 2. Starta om Claude Code

Stäng helt och öppna igen.

### 3. Skicka vilket meddelande som helst i ett git-projekt

Skriv till exempel `hej`. Claudes första svar börjar med en sammanfattning av vad som ändrats sedan du var där sist.

Det körs en gång per session. Inga upprepningar.

---

## Vad du får se

```
[git-pulse · 14:22 UTC] acme/widgets · branch: main

Det finns 23 ändringar på remoten som du inte har lokalt än,
gjorda under de senaste ~3 månaderna.

Vem har jobbat:    alice (17), bob (6)
Typ av ändringar:  11 buggfixar, 3 config, 2 docs, 1 ny feature
Påverkan totalt:   27 filer, +981 / −157 rader
Senaste:           "fix: handle expired auth tokens" (2d sen)

Kunskap eller docs (läs dessa först):
  · [ny] docs/auth-flow.md (+165 rader)

Refererade PR:er: #421, #438

Senaste aktivitet (nyast först):
  · 2d  alice  fix: handle expired auth tokens
  · 3d  bob    chore: bump axios to 1.7.4

→ Be Claude köra `git fetch` och `git pull` så hämtas det in.
```

Claude skriver sedan två tre meningar på svenska om vad som faktiskt hände, så du slipper läsa hela tabellen.

---

## Krav

* `git` och `python3` i PATH (har du redan om du kodar på Mac)
* Claude Code v2.x eller Desktop-appen
* Valfritt: `gh` (GitHub CLI) inloggad. Behövs för författarnamn, PR-referenser och dokumentfiler.

---

## Uppdatera

Kör samma kommando igen. Idempotent.

## Avinstallera

```
bash ~/.claude/git-pulse/dist/uninstall.sh
```

## Om inget syns

1. Starta om Claude Code helt.
2. Kontrollera att du står i ett git-repo med en remote.
3. Kör skriptet manuellt för att se eventuella fel:

```
echo '{"cwd": "'$PWD'"}' | python3 ~/.claude/git-pulse/git-pulse/scripts/git-pulse.py user-prompt-submit
```

---

Frågor: peta @we-dan.
