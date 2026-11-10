# Raumklima (Sensoren)

Die Ansicht **Mehr → Raumklima** zeigt Temperatur, Luftfeuchtigkeit und Batteriestand von Sensoren, live aktualisiert, mit Verlauf über 24 Stunden und 7 Tage.

Die App spricht nicht selbst mit den Geräten. Eine **Brücke** im Heimnetz (z. B. Zigbee2MQTT, Home Assistant oder ein eigenes Skript) liest die Sensoren aus und schickt die Werte per HTTPS an die App. Welche Quelle liefert, ist dem Backend egal.

## Einrichten

1. Als Admin: **Haushalt → Raumklima-Sensoren → Schlüssel erzeugen**. Die App zeigt einmalig einen Beispielaufruf mit Adresse und Schlüssel.
2. Die Brücke mit Adresse und Schlüssel konfigurieren.
3. Sobald der erste Messwert eintrifft, erscheint der Sensor in der Ansicht. Name und Raum lassen sich dort ändern.

## Messwerte liefern

```bash
curl -X POST https://haushalt.example.com/api/sensors/ingest \
  -H "Authorization: Bearer hs_…" \
  -H "Content-Type: application/json" \
  -d '{"readings":[{"device_id":"0xa4c138…","name":"Wohnzimmer","temperature":21.4,"humidity":48,"battery":87}]}'
```

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `device_id` | ja | Kennung der Quelle (z. B. Zigbee-Adresse), 1–100 Zeichen, pro Haushalt eindeutig |
| `name` | nein | Anzeigename beim ersten Messwert; ein in der App geänderter Name bleibt bestehen |
| `temperature` | * | °C, −60 bis 100 |
| `humidity` | * | relative Feuchte in %, 0 bis 100 |
| `battery` | * | %, 0 bis 100 |

\* Mindestens einer der drei Werte. Fehlende Werte lassen den letzten Stand stehen.

Pro Aufruf höchstens 50 Messwerte. Antwort: `{"accepted": 1, "rejected": []}`; `rejected` nennt die `device_id` neuer Geräte, die wegen der Obergrenze von 50 Sensoren pro Haushalt verworfen wurden.

## Regeln

| Thema | Umsetzung |
|---|---|
| Verlauf | Der letzte Stand wird bei jedem Messwert aktualisiert. In den Verlauf kommt pro Sensor höchstens ein Eintrag alle 5 Minuten; Einträge älter als 30 Tage werden gelöscht |
| Verlauf lesen | Bis 48 Stunden Einzelwerte, darüber Stundenmittel |
| Offline | Die Ansicht markiert einen Sensor nach 3 Stunden ohne Messwert als offline |
| Hinweise | Luftfeuchtigkeit unter 30 % «trocken», über 65 % «feucht»; Batterie ab 15 % «schwach» |
| Sensor löschen | Löscht Sensor und Verlauf. Liefert die Quelle weiter, entsteht er neu |

## Schlüssel und Sicherheit

| Eigenschaft | Umsetzung |
|---|---|
| Rechte | Nur `POST /api/sensors/ingest`. Mit dem Schlüssel lässt sich nichts lesen und keine andere API aufrufen |
| Bindung | Ein Schlüssel pro Haushalt; erzeugen und widerrufen dürfen nur Admins |
| Speicherung | Nur SHA-256-Hash in `sensor_ingest_tokens`; Klartext (`hs_…`, 256 Bit) wird einmal angezeigt |
| Laufzeit | Kein Ablauf; «Neuen Schlüssel erzeugen» ersetzt, «Widerrufen» löscht ihn |
| Missbrauch | Rate-Limit 120/min pro IP; Wertebereiche werden geprüft |

Wer den Schlüssel hat, kann Messwerte des Haushalts verfälschen und bis zur Obergrenze Sensoren anlegen, bis der Schlüssel widerrufen wird.

## API

| Methode | Pfad | Auth | Beschreibung |
|---|---|---|---|
| GET | `/api/households/{id}/sensors` | Login | Sensoren mit letztem Stand |
| PATCH | `/api/households/{id}/sensors/{sensor_id}` | Login | `name`, `room` ändern |
| DELETE | `/api/households/{id}/sensors/{sensor_id}` | Login | Sensor und Verlauf löschen |
| GET | `/api/households/{id}/sensors/{sensor_id}/readings?hours=24` | Login | Verlauf (1 bis 720 Stunden) |
| GET | `/api/households/{id}/sensors/ingest-token` | Login | Status des Schlüssels |
| POST | `/api/households/{id}/sensors/ingest-token` | Admin | Schlüssel erzeugen (ersetzt den alten); 10/min |
| DELETE | `/api/households/{id}/sensors/ingest-token` | Admin | Widerrufen (idempotent, 204) |
| POST | `/api/sensors/ingest` | `Authorization: Bearer hs_…` | Messwerte liefern; 401 `SENSOR_TOKEN_INVALID` bei falschem Schlüssel |

Echtzeit-Events im Haushaltsraum: `sensor_updated` (Sensor mit neuem Stand), `sensor_deleted` (`{"id": …}`).

## Noch nicht enthalten

- Die Brücke selbst (z. B. ein Container, der Zigbee2MQTT liest und an die App liefert).
- Push-Warnungen (Luftfeuchtigkeit, Frost, Batterie, offline).
- Geräte steuern (z. B. Heizkörperthermostate); das Modul ist nur lesend.
