# ControlProof — instrukcje dla asystentów AI

Odpowiadaj po polsku, konkretnie. Kod, nazwy API, UI i materiały konkursowe pisz po angielsku. Bieżące polecenia użytkownika mają pierwszeństwo przed planem.

## Najpierw przeczytaj

1. [README](README.md) — stan i mapa dokumentacji.
2. [CONTRIBUTING](CONTRIBUTING.md) — zasady współpracy i właściciele plików.
3. [Plan dwóch osób](docs/PLAN_DWOCH_OSOB.md) — kolejność zadań i odbiór.
4. [Wspólne ustalenia](docs/WSPOLNE_USTALENIA.md) — obowiązujące kontrakty i technologie.

Na 3.10.2026 repo zawiera kroki A1–A3 oraz moduły B2–B3: kontrakty, schemat SQLite, `/health`, panel, tokeny demo, zadania, `documents.read` z kontrolą dostępu i adapterem dokumentów, audyt w SQLite z historią zadania i eksportem, adaptery Jev/Luna i rezerwacje budżetu. Gateway nie wywołuje jeszcze Jev, Luny ani budżetu (A5). Polityka, Presidio, artefakty i wyniki testów live jeszcze nie istnieją; ich endpointy odpowiadają `501`. Sprawdź aktualny stan przed kodowaniem. Planowane komendy i struktura katalogów nie są dowodem ich istnienia.

## Decyzje zespołu

Dwie osoby, jeden projekt AI Control Layer dla Goldman Sachs. Osoba 1: gateway, dane, konfiguracja, audyt, panel i integracja. Osoba 2: OpenAI/Jev, semantyka, budżet i wspólny zestaw testów. Stos: Python 3.12, FastAPI, Pydantic 2, SQLite, prosty HTML/JS, uv, pytest i Ruff. Generowanie: OpenAI `gpt-6-luna` przez Responses API. Ocena semantyczna: TypeSafe Jev `jev-1.13.0`. PII: lokalne Presidio Analyzer/Anonymizer i spaCy. Reguły gatewaya egzekwują wynik; Jev nie nadaje praw.

Nie przywracaj czteroosobowego podziału, planu kilku projektów ani lokalnego detektora jako domyślnej decyzji. Archiwum jest historyczne. Rozbieżność wyboru zewnętrznych API z oczekiwaniem modeli lokalnych w briefie pozostaje jawna we wspólnych ustaleniach.

## Zasady implementacji

- Wykonuj wskazany krok w plikach właściciela. Uzgodnij z drugą osobą zmianę kontraktu, schematu bazy lub zależności przed edycją wspólnej części.
- Tożsamość, role, klient, metadane dokumentów i model pochodzą ze sprawdzonego stanu serwera, nie z deklaracji agenta.
- Kontroluj dostęp przed odczytem; redaguj dane przed każdym wyjściem do Jev lub OpenAI, także liczeniem tokenów. Presidio uzupełnia usuwanie pól i własne reguły sekretów; jego brak nie przepuszcza surowych danych. Nie loguj surowych treści ani sekretów.
- Płatna operacja wymaga atomowej rezerwacji. Koszt detektora też podlega limitom. Timeout i restart nie kasują niepewnego kosztu.
- Detektor nie znosi twardych zakazów. Jego awaria blokuje chronioną operację. Wynik na stubie nie jest testem prawdziwej semantyki.
- Audyt odróżnia decyzję od skutku i pokazuje poszczególne adaptery. Blokada odpowiedzi nie oznacza braku wcześniejszego wykonania.
- Zmiana polityki/feedu jest walidowana i wersjonowana. Błędna aktualizacja pozostawia ostatnią poprawną konfigurację; brak konfiguracji przy starcie zatrzymuje chroniony ruch.
- Testuj zachowanie i rzeczywisty skutek. Wyniki wydajności i skuteczności podawaj dopiero po pomiarze. Brak klucza/modelu nie może dawać sukcesu testu live.
- Nie dodawaj infrastruktury, kolejnych modeli poza Jev i Luną, MCP ani zgód człowieka kosztem podstaw. Nie deklaruj production-ready ani ochrony całego konta/chmury.

## Źródła

Pierwotne źródła to `dane_wejsciowe/opis_tasku.pdf`, `dane_wejsciowe/terms.pdf` i `dane_wejsciowe/rozmowa.txt`; nie nadpisuj ich. Brief i regulamin mają rozbieżne wagi, a termin wymaga potwierdzenia. Aktualny rejestr tych kwestii jest w sekcji 11 wspólnych ustaleń. `docs/archiwum` nie jest źródłem bieżących instrukcji.
