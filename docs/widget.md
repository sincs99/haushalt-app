# Homescreen-Widget (iPhone, Scriptable)

Web-Apps können auf iOS keine eigenen Widgets anbieten. Das Widget läuft deshalb in der kostenlosen App [Scriptable](https://scriptable.app): Ein kleines JavaScript holt die Daten über einen eigenen **Nur-Lese-Schlüssel** von der API und zeichnet daraus ein Widget (klein, mittel, gross).

## Einrichten (für Nutzerinnen und Nutzer)

1. In der App: **Haushalt → Widget (iPhone) → Widget einrichten**. Die App zeigt einmalig ein fertiges Skript mit Adresse und Schlüssel.
2. „Skript kopieren“ (oder „Als Datei laden“).
3. Scriptable aus dem App Store laden, öffnen, mit **+** ein neues Skript anlegen, einfügen.
4. Homescreen lange drücken → **+** → „Scriptable“ → Grösse wählen → hinzufügen.
5. Widget lange drücken → „Widget bearbeiten“ → bei „Script“ das Skript wählen.

Tippen aufs Widget öffnet die App (Startseite).

## Was das Widget zeigt

| Grösse | Inhalt |
|---|---|
| Klein | Zahl offener Dinge, die ersten 3 Einträge |
| Mittel | Zahl, Haushaltsname, 3 Einträge, offene Einkäufe |
| Gross | bis 8 Einträge, Termine von heute, Einkaufsliste (6 Artikel) |

Einträge sind dieselben wie bei der Zahl am App-Icon (`backend/app/services/attention.py`): bis heute fällige offene Aufgaben und Ämtli (eigene oder niemandem zugewiesene), Tier- und Pflanzenpflege. Überfälliges steht oben und ist rot.

Ohne Netz zeigt das Widget den letzten Stand mit Uhrzeit („Offline – Stand 08:15“). iOS aktualisiert Widgets nach eigenem Zeitplan; das Skript bittet um frühestens 15 Minuten.

## Schlüssel und Sicherheit

| Eigenschaft | Umsetzung |
|---|---|
| Rechte | Nur `GET /api/widget/summary`. Mit dem Schlüssel lässt sich nichts ändern und keine andere API aufrufen (andere Endpoints erwarten ein Login-JWT) |
| Bindung | Eine Person in einem Haushalt; höchstens ein Schlüssel pro Person und Haushalt |
| Speicherung | Nur SHA-256-Hash in `widget_tokens`; Klartext (`hw_…`, 256 Bit) wird einmal angezeigt |
| Laufzeit | Kein Ablauf; „Neuen Schlüssel erzeugen“ ersetzt, „Widerrufen“ löscht ihn. Gleichzeitiges Erzeugen (Doppelklick, zwei Geräte) läuft unter der Haushaltssperre nacheinander — am Ende gilt genau ein Schlüssel, der zuletzt ausgegebene |
| Haushalt verlassen / entfernt werden | Schlüssel wird im selben Commit wie der Austritt gelöscht (PD-H1) — auch nach erneutem Beitritt gilt er nicht mehr. Als Rückfall prüft jeder Abruf die Mitgliedschaft (sonst 401 und Löschung); beim Löschen von Person oder Haushalt per `ON DELETE CASCADE` |
| Zuständigkeit | „Mir zugewiesen“ zählt nur Zuweisungen an aktuelle Mitglieder; Aufgaben/Ämtli eines Ex-Mitglieds zählen wie „niemandem zugewiesen“ |
| Missbrauch | Rate-Limit 30/min pro IP; Antwort mit `Cache-Control: no-store`; `last_used_at` sichtbar in der App |

Der Schlüssel steht im Skript auf dem iPhone. Synchronisiert Scriptable seine Skripte über iCloud Drive, liegt er auch dort. Wer das Skript hat, kann die Widget-Daten lesen (Titel von Aufgaben, Ämtli, Einkäufen, Terminen von heute), bis der Schlüssel widerrufen wird.

## API

| Methode | Pfad | Auth | Beschreibung |
|---|---|---|---|
| GET | `/api/households/{id}/widget-token` | Login | Status: `exists`, `token_prefix`, `created_at`, `last_used_at` |
| POST | `/api/households/{id}/widget-token` | Login | Neuen Schlüssel erzeugen (ersetzt den alten), Antwort enthält `token` einmalig; 10/min |
| DELETE | `/api/households/{id}/widget-token` | Login | Widerrufen (idempotent, 204) |
| GET | `/api/widget/summary?lang=de\|en` | `Authorization: Bearer hw_…` | Widget-Daten; 401 `WIDGET_TOKEN_INVALID` bei falschem/widerrufenem Schlüssel |

Antwort von `/api/widget/summary`:

```json
{
  "household": "WG Sonnenweg",
  "user": "Anna Muster",
  "date": "2026-10-07",
  "generated_at": "2026-10-07T05:39:57Z",
  "due_count": 4,
  "due": [{ "kind": "todo", "title": "Steuererklärung abgeben", "overdue": true, "mine": false }],
  "shopping": { "open_count": 5, "items": ["2 Milch", "Brot"] },
  "events": [{ "title": "Zahnarzt", "time": "14:30" }]
}
```

`kind`: `todo`, `chore`, `pet`, `plant`. Termine: alle, die heute stattfinden — auch mehrtägige, die vorher begonnen haben. `time` ist `null` bei ganztägigen Terminen und bei solchen, die schon vor heute begonnen haben.

## Dateien

| Datei | Zweck |
|---|---|
| `backend/app/routers/widget.py` | Schlüssel verwalten, Widget-Daten |
| `backend/app/services/attention.py` | Liste und Zahl der fälligen Dinge (auch App-Icon-Badge) |
| `backend/migrations/versions/a3b4c5d6e7f8_add_widget_tokens.py` | Tabelle `widget_tokens` |
| `frontend/src/assets/scriptable-widget.js` | Skript-Vorlage (läuft nur in Scriptable) |
| `frontend/src/utils/widgetScript.ts` | Setzt Adresse, Schlüssel und Sprache ein |
| `frontend/src/components/WidgetSettingsCard.vue` | Karte unter Haushalt |

Die Skript-Vorlage wurde mit einem Nachbau der Scriptable-API in Node gegen das lokale Backend getestet (alle Grössen, falscher Schlüssel, offline), nicht auf einem echten iPhone.
