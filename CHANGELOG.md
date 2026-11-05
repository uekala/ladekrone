# Änderungen

## 0.6.0

- **Vertrag und Abo, wenn der Betreiber sie veröffentlicht.** Neben dem Ad-hoc-Preis behält Ladekrone weitere Tarife aus derselben Mobilithek-Meldung (DATEX `ratePolicy`, z. B. `contract` oder `subscription`). Im Suchgebiet und in der Web-App lässt sich so ein Tarif wählen. Wo der Betreiber ihn meldet, gilt er. Wo nicht, bleibt der Ad-hoc-Preis und ist weiter als solcher gekennzeichnet. Der eigene Vertragssatz einer Ladekarte steht in diesen Daten nicht.

## 0.5.1

- **Ad-hoc-Preis klar gekennzeichnet.** Web-App und Home-Assistant-Karte weisen direkt am angezeigten Preis darauf hin, dass es sich um einen Ad-hoc-Preis ohne Vertrag handelt. Preise mit Ladekarte oder Abo können abweichen.

## 0.5.0

- **Feiertagstarife.** Tarife, die an Feiertagen anders gelten (DATEX II `recurringSpecialDay`), werden jetzt ausgewertet, in der Integration, in der Karte und in der Web-App. Es zählen die gesetzlichen Feiertage des Bundeslands, in dem die Station steht, dazu „Tag vor“ und „Tag nach einem Feiertag“. Bisher galt eine Feiertagsregel nie, ein Feiertagspreis wurde also nie angezeigt und ein Werktagspreis auch an Feiertagen.
- Der Datensammler ordnet Stationen mit Feiertagstarif einem Bundesland zu (Landesgrenzen aus Natural Earth, gemeinfrei) und zählt in der Diagnose je Quelle, welche Sondertage in den Tarifen vorkommen (`special_days`).
- README: Der Hinweis zu XML-Angeboten ist korrigiert. Die Mobilithek sieht für AFIR-Angebote JSON vor, und alle abonnierten Angebote liefern es.

## 0.4.3

- **Karte zusätzlich als Dashboard-Ressource.** Ladekrone trägt die Karte selbst unter Einstellungen → Dashboards → Ressourcen ein und setzt dort nach jedem Update die neue Version. So lädt ein Dashboard die Karte auf demselben Weg wie Karten aus HACS, auch in Handy-Apps. Dashboards im YAML-Modus bleiben unberührt. Doppelte Einträge der Karte werden zusammengefasst.

## 0.4.2

- **Karte lädt zuverlässig, auch in der Handy-App.** Die Karte meldete sich manchmal an, bevor Home Assistant seine Oberfläche fertig geladen hatte. HA ersetzt dabei die Liste der Bausteine, und das Dashboard zeigte dann „Konfigurationsfehler“ (Custom element doesn't exist: ladekrone-card). Ob das passierte, hing vom Tempo ab, deshalb traf es vor allem Handys. Jetzt wartet die Karte, bis HA bereit ist.

## 0.4.1

- **Karte: Supercharger mit Ort.** Statt „Tesla, Inc.“ steht „Supercharger Willich“, in der Liste dann die Straße. Zeigt die Karte Supercharger-Preise, weist sie darauf hin, dass der Preis in der Tesla-App abweichen kann.
- Ein Release, das schon von Hand angelegt ist, lässt den Release-Workflow nicht mehr scheitern.

## 0.4.0

- **Dashboard-Karte im Look der Web-App**: `custom:ladekrone-card` zeigt den günstigsten Preis groß, Ladenetz, Adresse, Leistung, Ladepunkte, Gebühren und bis wann der Preis gilt, dazu „Route starten“, „Später günstiger“ und die weiteren Stationen zum Aufklappen. Mit den Schriften der App, hell und dunkel, Deutsch und Englisch. Die Karte kommt mit der Integration, ist im Karten-Dialog unter „Ladekrone“ zu finden und lässt sich dort ohne YAML einrichten.

## 0.3.2

- **Ladenetze aus Entität**: Die Liste „Nur diese Ladenetze“ kann zusätzlich aus dem Attribut `operators` einer Entität kommen, z. B. aus `sensor.ladecockpit_multipass` (Ladenetze, an denen Tesla MultiPass schon funktioniert hat). Kommt ein Ladenetz dazu, zählen sofort alle seine Stationen, ohne Neustart. Die zuletzt bekannte Liste übersteht Neustarts und kurze Ausfälle der Entität. Ist noch kein Ladenetz bekannt, wird keine Station vorgeschlagen.
- Namen aus der Liste werden wortweise verglichen: „Aral pulse“ findet auch „Aral AG“, „E.ON Drive“ auch „E.ON Drive Infrastructure GmbH“.
- Der Sensor „Ladestationen im Umkreis“ zeigt die aktuelle Liste im Attribut `networks`.

## 0.3.1

- **Durchschnittspreis**: neuer Sensor mit dem mittleren aktuellen Ad-hoc-Preis aller passenden Stationen im Umkreis, mit `stations`, `min_price` und `max_price`. Gut als Standardpreis, wenn der echte Preis einer Ladung fehlt.

## 0.3.0

- **Neuer Name: Ladekrone.** Ladekönig heißt jetzt Ladekrone, die Krone bleibt. Repository, Integration (`ladekrone`) und Datenseite sind umbenannt.
- **Web-App** unter uekala.github.io/ladekrone/app: günstigster Preis in der Nähe per Standort oder Ortssuche, „Später günstiger“ für die nächsten 24 Stunden, Filter, Route, offline nutzbar und installierbar. Rechnet mit derselben Logik wie die Integration.
- **Ortsverzeichnis** (`v1/places.json`): Postleitzahlen und Orte aus den Adressen der Stationen, für die Suche ohne fremden Dienst.
- Die Standard-Datenquelle wird in den Optionen nicht mehr festgeschrieben. So ziehen Einträge bei einem Umzug der Daten automatisch mit.
- **Umstieg:** In HACS das Repository `uekala/ladekrone` hinzufügen und Ladekrone installieren, die alte Integration Ladekönig entfernen und die Suchgebiete neu anlegen. Entitäts-IDs richten sich wie bisher nach dem Namen des Suchgebiets.

## 0.2.0

- **Günstigster Preis in 24 h**: neuer Sensor mit dem niedrigsten Preis der nächsten 24 Stunden im Umkreis, inklusive Zeitfenster (`from`, `until`).
- **Tageszeitpreise**: Jedes Angebot zeigt, bis wann sein Preis gilt (`until`) und welcher danach kommt (`next_price`).
- **Suche, die mitfährt**: Der Mittelpunkt kann einem `device_tracker`, einer `person` oder einer `zone` folgen. Fehlende Kacheln werden beim Ortswechsel nachgeladen.
- **Betreibernamen**: Wo eine Quelle nur die Betreiber-ID meldet (z. B. `DE*EWE`), steht jetzt der Firmenname. Betrifft über 11.000 Stationen.
- **Dynamische AFIR-Preise**: Der Datensammler liest Preisaktualisierungen aus den dynamischen Angeboten.
- **Logo** für Home Assistant ab 2026.3.
- **Neue Datenseite**: freundlich gestaltet, mit einer Punktkarte Deutschlands aus den echten Daten, hellem und dunklem Modus und gut lesbarer Schrift (Atkinson Hyperlegible). Sie zeigt auch abonnierte Quellen ohne Preise und verlinkt eine Diagnose je Quelle.
- **Sprache**: „Ladenetze“ statt „Betreiber“ in Einrichtung, Datenseite und README.
- Die Vorschau auf 24 Stunden läuft außerhalb der Ereignisschleife und wird nur einmal pro Viertelstunde neu berechnet.

## 0.1.0

- Erste Version: günstigster Ad-hoc-Preis im Umkreis, Filter, mehrere Suchgebiete, Datensammler mit GitHub Pages.
