# ControlProof — AI Control Layer

Warstwa kontroli pomiędzy aplikacją/agentem a dokumentami i modelami AI. Sprawdza dostęp, usuwa wskazane dane wrażliwe, wykrywa podejrzane instrukcje, ogranicza zużycie i zapisuje wynik każdej operacji.

**Stan na 3.10.2026:** dokumentacja wykonawcza; implementacja i wyniki testów jeszcze nie powstały. Plan dotyczy **dwóch osób**. Polecenia uruchomienia opisane w dokumentacji są celem do zaimplementowania.

## Czytaj w tej kolejności

1. [Podział pracy krok po kroku](docs/PLAN_DWOCH_OSOB.md) — czego każda osoba ma się nauczyć, co wykonać i kiedy połączyć pracę.
2. [Zasady współpracy](CONTRIBUTING.md) — właściciele plików, Git, korzystanie z AI, testowanie i odbiór zmian.
3. [Wspólne ustalenia techniczne](docs/WSPOLNE_USTALENIA.md) — stos, modele, API, formaty danych, polityka, budżet i scenariusz demo.

## Decyzje

| Obszar | Wybór |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic 2, Uvicorn |
| Dane | SQLite, standardowy moduł `sqlite3` |
| Panel | HTML, CSS i JavaScript z `fetch`, serwowane przez FastAPI |
| Model generujący | OpenAI `gpt-6-luna`, Responses API, oficjalny SDK Python |
| Ocena semantyczna | TypeSafe Jev `jev-1.13.0`, osobny adapter HTTP |
| Wykrywanie i maskowanie PII | Presidio: `presidio-analyzer`, `presidio-anonymizer`, lokalne modele spaCy |
| Praca nad kodem | Codex z modelem Luna; zasady w CONTRIBUTING |
| Narzędzia | uv, pytest, pytest-asyncio, HTTPX, Ruff |
| Uruchomienie demo | Jeden laptop, jeden proces aplikacji, przeglądarka i dostęp do internetu |

Modele i konkretne ustawienia są opisane w jednym miejscu: we wspólnych ustaleniach. Dostęp do API, działanie modelu i wersje pakietów trzeba potwierdzić w pierwszym etapie implementacji.

## Materiały źródłowe

- [Pełny brief](dane_wejsciowe/opis_tasku.pdf) — wymagania techniczne i sposób oceny.
- [Regulamin zadania](dane_wejsciowe/terms.pdf) — wymagane zgłoszenie i zasady konkursu.
- [Rozmowa z mentorem](dane_wejsciowe/rozmowa.txt) — kontekst i interpretacja potrzeb; transkrypcja może zawierać błędy.

Starszy research, warianty projektów i plan dla większego zespołu są w [archiwum](docs/archiwum/README.md). Nie należą do bieżącej instrukcji realizacji. Otwarte kwestie briefu i terminu znajdują się na końcu wspólnych ustaleń.
