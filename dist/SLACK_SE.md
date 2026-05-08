# git-pulse i Slack (svenska)

Klistra in det här i en Slack-kanal eller DM för att dela vidare.

---

## Hur du installerar git-pulse på 30 sekunder

git-pulse visar dig en sammanfattning av vad som hänt i ett repo varje gång du öppnar Claude Code. Funkar både i Claude Code CLI och i Desktop-appen.

### macOS eller Linux

Öppna Terminal. Klistra in:

```
curl -fsSL https://raw.githubusercontent.com/we-app/git-pulse/main/install.sh | bash
```

### Windows

Öppna PowerShell. Klistra in:

```
irm https://raw.githubusercontent.com/we-app/git-pulse/main/install.ps1 | iex
```

### Sen då?

1. Stäng Claude Code helt och starta om.
2. Öppna ett git-projekt.
3. Skicka vilket meddelande som helst (till exempel `hej`).
4. Claudes första svar börjar med en sammanfattning av vad som ändrats på remoten sedan du var här sist.

Det körs en gång per session. Inga upprepningar.

### Vad du får se

```
[git-pulse · 14:22 UTC] acme/widgets · branch: main

Det finns 23 ändringar på remoten som du inte har lokalt än, gjorda
under de senaste ~3 månaderna.

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
  ...

→ Be Claude köra `git fetch` och `git pull` så hämtas det in.
```

Claude inleder sedan svaret med två tre meningar på vanlig svenska om vad som faktiskt hände, så du slipper läsa hela tabellen.

### Krav

* `git` och `python3` i din PATH (har du redan om du kodar)
* Claude Code v2.x eller Desktop-appen
* Valfritt men rekommenderat: `gh` (GitHub CLI) inloggad. Krävs för att se commit-författare, PR-referenser och dokumentfiler.

### Avinstallera

macOS eller Linux:

```
bash ~/.claude/git-pulse/dist/uninstall.sh
```

Windows:

```
pwsh -File "$env:USERPROFILE\.claude\git-pulse\dist\uninstall.ps1"
```

### Om något inte fungerar

* Inget syns: starta om Claude Code helt och kontrollera att du står i ett git-repo med en konfigurerad remote.
* "hook fired but errored": kör skriptet manuellt för att se felet:

  ```
  echo '{"cwd": "'$PWD'"}' | python3 ~/.claude/git-pulse/git-pulse/scripts/git-pulse.py user-prompt-submit
  ```
* Ingen rik info (inga författare, inga PR:er): installera och logga in på `gh`.

### Uppdatera senare

Kör samma installations-kommando igen. Det är idempotent och uppgraderar utan att gå sönder.

---

Frågor: peta @we-dan.
