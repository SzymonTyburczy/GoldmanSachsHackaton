# ContrAl — AI Control Layer

Warstwa kontroli pomiędzy aplikacją/agentem a dokumentami i modelami AI. Sprawdza dostęp, usuwa wskazane dane wrażliwe, wykrywa podejrzane instrukcje, ogranicza zużycie i zapisuje wynik każdej operacji.

**Stan na 3.10.2026:** ukończone kroki A1–A6. Działają: `GET /health`, uwierzytelnienie trzema tokenami demo, zadania, `documents.read` i `documents.summarize` (kontrola dostępu przed odczytem, redakcja przez lokalne Presidio i regułę sekretów, Jev, Luna, rezerwacje budżetu, idempotencja i limity), `artifacts.admit` (manifest SHA-256, feed, ścisły schemat JSON), wersjonowana polityka i feed (`GET`/`PUT /admin/policy`, `/admin/feed`, `make reload-config`), audyt z historią i eksportem JSONL, `/admin/metrics`, `/admin/test-results` oraz panel operatora pod `/`. `make test` nie zapisuje raportu, więc panel pokazuje tylko raporty `make test-live` i `make benchmark`. Plan dotyczy **dwóch osób**.

## Uruchomienie

Wymagane: [uv](https://docs.astral.sh/uv/) i dostęp do internetu przy pierwszej instalacji. uv pobiera Pythona 3.12, pakiety i modele spaCy według `uv.lock`.

```bash
make setup   # uv sync --locked, .env z .env.example (jeśli brak), puste tokeny demo, lokalna baza, import config/, test Presidio
make dev     # API i panel: http://127.0.0.1:8000
make check   # Ruff
make test    # testy offline; sieć do TypeSafe i OpenAI jest zablokowana
make reload-config  # walidacja i aktywacja zmienionych config/policy.json i config/threat-feed.json
```

`make test-live`, `make verify` i `make benchmark LIVE=1` wysyłają płatne zapytania do TypeSafe i OpenAI i wymagają lokalnych kluczy; `make benchmark` bez `LIVE=1` mierzy tylko lokalne komponenty. `make reset-demo` jeszcze nie istnieje i kończy się błędem, żeby nie udawał udanej operacji.

API wymaga nagłówka `Authorization: Bearer <token>` z `.env`: `CONTROLPROOF_TOKEN_ANALYST_A`, `CONTROLPROOF_TOKEN_REVIEWER_A` lub `CONTROLPROOF_TOKEN_ADMIN`. Tokenu nie podaje się w URL. `POST /v1/execute` wymaga aktywnej polityki i feedu; `make setup` aktywuje je z `config/`, jeśli baza jeszcze ich nie ma. Później źródłem prawdy jest wersja w bazie: zmiany wprowadza admin przez `PUT /admin/policy` albo `make reload-config`.

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
