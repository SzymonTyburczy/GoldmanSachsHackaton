# Wspólne ustalenia techniczne

**Wersja 2, 3.10.2026.** Specyfikacja do implementacji dla dwóch osób. Konkretne wybory poniżej zastępują warianty ze starszych planów. Działanie API, dostępność modelu na koncie i osiągi nie zostały jeszcze przetestowane.

Kolejność pracy: [plan](PLAN_DWOCH_OSOB.md). Właściciele plików i sposób wprowadzania zmian: [CONTRIBUTING](../CONTRIBUTING.md).

## 1. Co budujemy i co oboje musicie rozumieć

ContrAl jest serwerem kontrolującym dostęp do podłączonych narzędzi i modeli. Użytkownikiem panelu jest IT/security. Dokumenty klientów A/B są syntetycznym przykładem użycia.

| Pojęcie | Znaczenie w naszym projekcie |
|---|---|
| Gateway | Jedyny publiczny punkt wykonywania chronionych operacji |
| Adapter | Kod odczytujący dokument, przyjmujący artefakt albo wywołujący model |
| Polityka | Wersjonowana konfiguracja: kto, do czego, z jakimi limitami |
| Kontrola deterministyczna | Kod dający wynik na podstawie reguły, np. porównania właściciela dokumentu |
| Kontrola semantyczna | Model oceniający sens tekstu, np. próbę podsunięcia instrukcji |
| Redakcja | Usunięcie wskazanych pól/wzorców przed dalszym przekazaniem danych |
| Rezerwacja | Zajęcie części dostępnego budżetu przed rozpoczęciem operacji |
| Audyt | Zapis decyzji, powodu, wersji reguł i rzeczywistego skutku |

Zakres podstawowy: dostęp, redakcja, jeden detektor AI, budżet, feed artefaktów, panel, audyt i testy. Głębiej dopracowujemy budżet przy równoległych wywołaniach. Jednorazowe zgody człowieka i MCP mogą powstać dopiero po ukończeniu podstaw; nie są zależnością żadnego kroku.

## 2. Technologie i modele

| Element | Konkretny wybór | Sposób użycia |
|---|---|---|
| Runtime | Python 3.12 | Jeden język dla backendu, testów i skryptów |
| API | FastAPI + Uvicorn | Jeden proces, jeden worker podczas demo |
| Walidacja | Pydantic 2, `extra="forbid"` | Wspólne modele danych, odrzucanie nieznanych pól |
| Baza | SQLite przez `sqlite3` | Zadania, rezerwacje, audyt i aktywne wersje konfiguracji |
| Konfiguracja | JSON | `config/policy.json` i `config/threat-feed.json` jako pliki startowe |
| Panel | HTML/CSS/JavaScript, `fetch` | Statyczne pliki z FastAPI, jeden origin, odświeżanie co 2 s |
| OpenAI | Oficjalny pakiet Python `openai`, Responses API | Adapter generowania; żadnych kluczy w przeglądarce |
| Jev | TypeSafe `jev-1.13.0`, HTTPX AsyncClient | Osobny adapter oceny semantycznej |
| PII | `presidio-analyzer`, `presidio-anonymizer`, spaCy | Analiza i maskowanie lokalnie, przed każdym zewnętrznym API |
| Pakiety | uv + `pyproject.toml` + `uv.lock` | Wspólny, przypięty zestaw zależności |
| Testy | pytest, pytest-asyncio, HTTPX | Testy jednostkowe, HTTP, współbieżności i live |
| Kontrola kodu | Ruff | Formatowanie i lint |

Maciek podczas A1 zapisuje faktycznie zainstalowane wersje w `uv.lock`; Paweł sprawdza odtworzenie przez `uv sync --locked`. Zainstalowane w A1: Python 3.12.14, FastAPI 0.142.2 (Starlette 1.7.0), Pydantic 2.13.5, Uvicorn 0.54.0, HTTPX 0.28.1, `openai` 3.24.0, Presidio 2.2.364, spaCy 3.8.16 z `en_core_web_sm` i `pl_core_news_sm` 3.8.0 (wheele przypięte w lockfile), pytest 9.1.1, pytest-asyncio 1.4.0, Ruff 0.16.10. Natywna telemetria OpenTelemetry w FastAPI jest wyłączona, bo może eksportować treść błędów walidacji. Nie potrzebujemy osobnego frontendu Node, ORM ani wdrożenia chmurowego do podstawowego demo. Dokumentacja: [FastAPI](https://fastapi.tiangolo.com/), [uv: lockfile](https://docs.astral.sh/uv/concepts/projects/sync/).

### Podział między Jev, Presidio i Lunę

| Zastosowanie | Technologia | Ustawienia początkowe zespołu |
|---|---|---|
| Ocena podejrzanych instrukcji | TypeSafe `jev-1.13.0` | Dwa pytania Noul, próg 0.80, timeout 10 s, brak retry |
| Wykrywanie PII w tekście | Presidio Analyzer | Lokalny silnik, jawna lista encji i progi |
| Zastępowanie wykrytych fragmentów | Presidio Anonymizer | Zastąpienie placeholderem, np. `<EMAIL_ADDRESS>` |
| Podsumowanie dopuszczonego dokumentu | OpenAI `gpt-6-luna` | `reasoning.effort=low`, `max_output_tokens=2048` |

Jev zwraca odpowiedzi na pytania o podany tekst. Wybieramy przypięty identyfikator z [katalogu modeli TypeSafe](https://docs.typesafe.ai/models). Wywołanie: `POST https://api.typesafe.ai/v1/systemone` przez HTTPX, z `TYPESAFE_API_KEY`, `state`, `model` i `questions`; kształt opisuje [API TypeSafe](https://docs.typesafe.ai/api). Transport nie ponawia sam wywołania. Wersję odpowiedzi zapisujemy w audycie.

W jednym wywołaniu Jev zadajemy dwa pytania Noul: czy treść próbuje zmienić/ominąć instrukcje oraz czy próbuje wyprowadzić dane poza dozwolony zakres. `state` oddziela oczyszczony prompt, dokument i zaufany opis dozwolonego zadania; instrukcje/criteria pochodzą wyłącznie z serwera. Cytat o ataku nie jest automatycznie atakiem. Reguła gatewaya stosuje progi do ocen i nie oddaje modelowi prawa do zmiany ACL ani budżetu. Taki podział oceny i egzekwowania pokazuje [cookbook guardrails TypeSafe](https://docs.typesafe.ai/cookbooks/llm_guardrails).

Nie przenosimy bez testu deklaracji dostawcy o kalibracji na nasz przypadek. Jev również może ulec manipulacji przez treść; opisuje to [jego dokumentacja ograniczeń](https://docs.typesafe.ai/model-jaggedness/jev-1.13). Nie dodajemy Luny jako drugiego detektora w P0. Ewentualne porównanie obu detektorów jest późniejszym eksperymentem.

Luna wyłącznie generuje podsumowanie przez `AsyncOpenAI.responses.create`. Ustawienia: `store=false`, timeout 30 s, `max_retries=0`, brak narzędzi dostawcy, streaming wyłączony. Używamy własnego kompletnego wejścia bez `previous_response_id`. Identyfikator potwierdza [dokumentacja Luny](https://developers.openai.com/api/docs/models/gpt-6-luna). `store=false` nie jest obietnicą pełnego braku przechowywania danych u dostawcy. Oba klucze są tylko w backendzie. Dostęp do modeli na kontach sprawdzamy w B1.

### Presidio: konkretny zakres

Maciek instaluje dwa pakiety Presidio oraz lokalne pipeline'y spaCy: [`en_core_web_sm`](https://spacy.io/models/en) i [`pl_core_news_sm`](https://spacy.io/models/pl). Przypina wersje pakietów/modeli podczas A1/A4. Konfiguruje `NlpEngineProvider`, języki `en`/`pl`, właściwe etykiety NER i rejestr recognizerów; nie zakłada, że konfiguracja angielska zapewnia obsługę polskiego. Instalacja i sprawdzenie modeli odbywają się w setupie, nie podczas żądania.

W P0 wykrywamy `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IBAN_CODE`, `CREDIT_CARD` i `PL_PESEL`, wymienione w [katalogu encji Presidio](https://presidio.dataprivacystack.org/supported_entities/). Rejestrujemy ich obsługę dla obu języków i testujemy syntetyczne przykłady oraz fałszywe alarmy. Wykrywanie imion/nazwisk `PERSON` dopuszczamy dopiero po sprawdzeniu mapowania NER i próbek danego języka.

Najpierw usuwamy pola zabronione dla roli i dostawcy; potem Analyzer wskazuje fragmenty tekstu, a Anonymizer zastępuje je placeholderami. Osobna reguła rozpoznaje nasz syntetyczny sekret/API key. Presidio nie zastępuje ACL, metadanych właściciela ani kontroli sekretów. Nie gwarantuje wykrycia wszystkich danych; dokumentuje to [projekt Presidio](https://presidio.dataprivacystack.org/).

Konfiguracja `redaction` zawiera encje, progi per encja, placeholdery, języki i wersję recognizerów. Awaria silnika lub brak wymaganego modelu blokuje ścieżkę wychodzącą, zamiast przesyłać surowy tekst. Audyt zapisuje typy encji/liczby i wersję konfiguracji, bez wykrytych wartości. Te same reguły stosujemy do promptu, dokumentu i odpowiedzi Luny przed udostępnieniem jej użytkownikowi.

### Doprecyzowania z A4: redakcja — do potwierdzenia przez Pawła

- **Silnik.** `app/pii/engine.py` buduje jeden Analyzer na zestaw języków, z recognizerami `EMAIL_ADDRESS`, `PHONE_NUMBER` (regiony PL, US, GB, DE, FR), `IBAN_CODE`, `CREDIT_CARD` i `PL_PESEL` zarejestrowanymi dla `en` i `pl`. Przed budową sprawdza `spacy.util.is_package` dla `en_core_web_sm` i `pl_core_news_sm`, bo Presidio przy braku modelu uruchamia jego pobieranie (`pip` w podprocesie). E-mail jest sprawdzany lokalnie: domena musi kończyć się literami (co najmniej 2). Domyślny recognizer używa `tldextract`, który może pobierać listę domen z internetu i odrzuca domeny `.example` i `.test`. Zestaw recognizerów i reguł sekretów ma wersję `controlproof-pii-1`, zapisaną w polityce.
- **Analiza i scalanie.** Każdy tekst jest analizowany w każdym języku z polityki. Wyniki poniżej progu encji odpadają. Nakładające się wyniki, także z różnych języków, łączą się w jeden fragment obejmujący je wszystkie, z typem wyniku o najwyższym score (remis: kolejność `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IBAN_CODE`, `CREDIT_CARD`, `PL_PESEL`). Anonymizer zastępuje te fragmenty placeholderami w tym samym tekście.
- **Reguła sekretów.** `app/pii/secrets.py` działa przed Presidio i niezależnie od niego. Rozpoznaje `cpdemo_…`, klucze w stylu OpenAI (`sk-…`), AWS (`AKIA…`), GitHub (`gh?_…`), `Bearer …` i klucze PEM. Liczy je jako typ `SECRET`.
- **Logi.** Loggery `presidio-analyzer` i `presidio-anonymizer` są wyłączone, bo na poziomie DEBUG zapisują fragmenty analizowanego tekstu. Wykrył to test braku treści w logach.
- **Wyjście `documents.read`.** Kolejno: pola roli, reguła sekretów, Presidio. Decyzja `REDACT` z `PII_REDACTED` zapada, gdy usunięto pole albo zastąpiono fragment. Zdarzenie audytu ma `redacted_entity_counts`, np. `{"EMAIL_ADDRESS": 1, "SECRET": 1}`.
- **Awaria silnika.** Silnik niedostępny przed odczytem: `200 DENY PII_ENGINE_UNAVAILABLE`, etap `pre_document`, bez odczytu. Awaria w trakcie redakcji po odczycie: `DENY PII_ENGINE_UNAVAILABLE` z `execution_status=SUCCEEDED` i `output=null`.
- **Dane dla dostawców.** `redaction.prepare_provider_input` zwraca `ProviderInput`: pola z przecięcia zakresu roli i `outbound_fields`, po redakcji, oraz oczyszczony prompt. A5 przekazuje adapterom wyłącznie `ProviderInput.detector_state(trusted_task)` (Jev, przez `build_jev_state`) i `ProviderInput.summary_input()` (liczenie tokenów i Luna). Test podstawia adapterom Pawła klienta `httpx.MockTransport` i sprawdza treść żądań do `/v1/systemone`, `/v1/responses/input_tokens` i `/v1/responses`.
- **Dane demo.** `notes` w `doc-a` zawiera syntetyczny e-mail, telefon i sekret, a `review_note` – IBAN. Dzięki temu maskowanie widać w polach dostępnych dla ról.
- **Ograniczenie.** Recognizer telefonu daje score 0,4 każdej jedenastocyfrowej liczbie, więc np. numery zamówień też mogą zostać zamaskowane. Wolimy nadmiarowe maskowanie niż wyciek.

## 3. Architektura i kolejność kontroli

```mermaid
flowchart LR
    C[Panel lub klient HTTP] --> G[Gateway: tożsamość i polityka]
    G --> R[ACL i lokalne Presidio]
    R --> B[Wspólny limiter i rezerwacje]
    B --> D[Jev: ocena semantyczna]
    D --> B2[Rezerwacja operacji docelowej]
    B2 --> M[Adapter dokumentu, artefaktu lub Luny]
    M --> O[Filtr odpowiedzi]
    O --> A[Audyt i wynik]
    A --> C
    P[Wersjonowana polityka i feed] --> G
    DB[(SQLite)] --- B
    DB --- B2
    DB --- A
```

Diagram pokazuje ogólną zasadę. Podsumowanie wymaga wcześniej odczytania dozwolonego dokumentu; jego dokładny przebieg:

1. Ogranicz body do 32 KiB. Uwierzytelnij token, sprawdź schemat i przypisz `request_id`.
2. Pobierz zadanie, jego właściciela, klienta i kontekst agenta z serwera. Przypnij aktywną wersję polityki/feedu. Atomowo zajmij limit żądania i równoległości.
3. Sprawdź narzędzie, dozwolony model, zakres zadania i właściciela dokumentu w zaufanym katalogu. Twarda odmowa kończy ścieżkę przed odczytem treści i zewnętrznymi modelami.
4. Pobierz dozwolony dokument. Odfiltruj pola według roli i reguł wyjścia. Presidio maskuje PII w dokumencie i prompcie; własna reguła usuwa sekret. Dopiero oczyszczone dane mogą trafić do Jev lub OpenAI.
5. Zamroź przygotowany stan i pytania Jev. Po limitach zasobów zarezerwuj konserwatywną górną granicę kosztu z sekcji 7 i uruchom Jev. Detektor nie sprawdza rekurencyjnie własnego wywołania.
6. `risk_score >= block_threshold` daje `DENY`. Odmowa modelu, timeout, niepełna odpowiedź i błąd parsowania także blokują dalsze podsumowanie.
7. Przy dopuszczeniu przygotuj wejście modelu podsumowującego z tych samych dopuszczonych danych. Policz tokeny, zarezerwuj koszt i wywołaj adapter Luny.
8. Przed zwróceniem odpowiedzi sprawdź ją filtrem PII/sekretów. Rozlicz znane zużycie, zachowaj niepewną rezerwację i zapisz audyt, także przy błędzie.

`documents.read` kończy się po filtrze danych i detektorze, bez modelu podsumowującego. `artifacts.admit` używa walidacji formatu, manifestu i feedu; nie wywołuje AI. Odrębny test budżetu używa testowego adaptera o stałym koszcie.

Chronimy podłączone adaptery. Model/klient nie ma kluczy TypeSafe ani OpenAI, dostępu do plików dokumentów ani publicznego endpointu pomijającego gateway. W MVP adaptery są w procesie serwera: nie deklarujemy izolacji od administratora hosta ani złośliwego kodu z tymi samymi uprawnieniami.

### Doprecyzowania z A5 — do potwierdzenia przez Pawła

- **Przebieg.** `app/gateway.py` łączy kroki 2–8. Przy przyjęciu żądanie dostaje wiersz `requests` (`app/idempotency.py`), w jednej transakcji z limitami: na minutę (`429 RATE_LIMITED`, `Retry-After`), na zadanie (`200 DENY BUDGET_EXCEEDED`) i równoległości (`200 DENY CONCURRENCY_EXCEEDED`). Odmowy limitów nie są zapisywane, więc ten sam klucz można użyć później.
- **Idempotencja.** Ten sam klucz i body zwracają zapisaną (zredagowaną) odpowiedź bez nowych zdarzeń i wywołań; `request_id` w body jest pierwotny. Inne body: `409 IDEMPOTENCY_CONFLICT`. Żądanie w toku lub przerwane: `409 REQUEST_PENDING`. Gdy nic nie zostało wywołane ani zarezerwowane, wiersz jest usuwany (np. `503` przed adapterem). Nowe kody `RATE_LIMITED`, `IDEMPOTENCY_CONFLICT`, `REQUEST_PENDING` są zmianą kontraktu.
- **Dostawcy.** Klucze z `.env`, timeouty i `max_output_tokens` z przypiętej polityki (`app/adapters/providers.py`). Brak klucza TypeSafe: `DENY DETECTOR_UNAVAILABLE`, brak klucza OpenAI przy podsumowaniu: `DENY UPSTREAM_FAILED` — oba przed odczytem dokumentu. `controls.semantic` musi mieć `true`; stawki `typesafe_input` i `openai_output` muszą być dodatnie.
- **Detektor.** Także `documents.read` przechodzi przez Jev (stan: pola `outbound_fields` po redakcji, pusty prompt). Stan większy niż `max_detector_state_chars`: `INPUT_TOO_LARGE`. Każde wywołanie idzie przez `app.provider_calls`: rezerwacja, zdarzenie intencji `budget ALLOW STARTED`, wywołanie z limitem czasu polityki, rozliczenie. Błąd, timeout lub brak usage Jev: `DENY DETECTOR_UNAVAILABLE`, Luna nie startuje, rezerwacja zostaje `UNKNOWN`.
- **Podsumowanie.** Liczenie tokenów i generowanie dostają to samo wejście. Błąd liczenia: `TOKEN_COUNT_UNAVAILABLE`; za dużo tokenów: `INPUT_TOO_LARGE`; odmowa/niepełna odpowiedź Luny: `UPSTREAM_FAILED` (`FAILED`); timeout: `UPSTREAM_TIMEOUT` (`UNKNOWN`). Wynik przechodzi regułę sekretów i Presidio (`redaction/post_output`).
- **Limity rezerwacji.** Przypięte, obniżone do aktywnej polityki, jeśli admin zmienił ją w trakcie żądania; `limit_version` to wersja aktywna. Start serwera wywołuje `budget.reconcile_after_restart`.
- **Odpowiedź.** `usage` zawiera wszystkie wywołania dostawców, także przy `DENY`.
- **Ograniczenia.** Rezerwacje `UNKNOWN` trzymają slot wywołania dostawcy; przy `max_concurrency_per_principal=2` dwa timeouty blokują użytkownika do ręcznego uzgodnienia, którego nie ma. `review_note` widziany przez reviewera nie przechodzi przez Jev. Limit body 32 KiB nie jest zbudowany.

## 4. Wspólne kontrakty danych

Źródłem typów w kodzie będzie `app/contracts.py`. Czas: UTC w ISO 8601. ID: UUID, oprócz jawnych identyfikatorów danych demo. Wszystkie formaty mają `schema_version=1`. Pola nieznane są błędem. Modele API i modele wewnętrzne są oddzielne.

### Żądanie klienta

`POST /v1/execute`, nagłówki `Authorization: Bearer <lokalny token>` i `Idempotency-Key: <uuid>`:

```json
{
  "schema_version": 1,
  "task_id": "11111111-1111-4111-8111-111111111111",
  "tool": "documents.summarize",
  "arguments": {
    "document_id": "doc-a",
    "prompt": "Summarize this company in three sentences."
  }
}
```

W przykładzie `task_id` należy zastąpić identyfikatorem zwróconym przez `POST /v1/tasks`. Dozwolone narzędzia i argumenty: `documents.read` (`document_id`), `documents.summarize` (`document_id`, `prompt`, maks. 8000 znaków), `artifacts.admit` (`artifact_id`). Nie przyjmujemy dowolnej ścieżki pliku, URL, SQL, modelu ani roli od klienta.

Ten sam klucz idempotencji dla tego samego użytkownika i identycznego żądania nie wykonuje ponownie adapterów: zwraca zakończony wynik lub informację o trwającym/niepewnym wykonaniu. Zmieniona treść pod tym samym kluczem daje `409`. Stan jest trwały w SQLite; zapisany wynik jest już po redakcji i dostępny tylko właścicielowi/adminowi.

| Typ | Wymagane pola / znaczenie |
|---|---|
| `RequestContext` | `request_id`, `task_id`, `principal_id`, `agent_id`, `role`, `client_id`, `policy_version`, `feed_version`, `created_at`; tworzy serwer, nie klient |
| `ControlResult` | `control_id`, `decision`, `reason_code`, `stage`, `redacted_fields`; decyzja to `ALLOW`, `DENY` lub `REDACT` |
| `PiiFinding` | `entity_type`, `start`, `end`, `score`; indeksy w oryginalnym analizowanym tekście, wyłącznie do lokalnego maskowania; bez kopii wykrytej wartości |
| `SemanticResult` | `instruction_override_probability`, `data_exfiltration_probability` (0–1), `risk_score`, `category` (`benign`, `instruction_override`, `data_exfiltration`); normalizowany wynik Jev |
| `Usage` | `provider` (`typesafe`/`openai`), `model`, `provider_response_id`, `input_tokens`, `cached_input_tokens`, `output_tokens`, `cost_nusd`, `pricing_version`, `cost_status`; niedostępne wartości to `null`, nie zero |
| `Reservation` | `reservation_id`, `request_id`, `task_id`, `principal_id`, `purpose` (`detector`/`summary`/`fixture`), `unit`, `amount`, `state`, `created_at`, `pricing_version`, `limit_version` |
| `AuditEvent` | `event_id`, kontekst identyfikatorów, czas, `control_id`, `decision`, `reason_code`, `stage`, `execution_status`, `adapter_calls`, `usage`, `latency_ms`, `model`, `policy_version`, `feed_version` |

Presidio przekazuje pozycje wykrytych fragmentów bez zmieniania tekstu przed wywołaniem Anonymizera; oba moduły używają tego samego tekstu. Wyniki z różnymi językami i nakładające się fragmenty są łączone według jednej sprawdzonej reguły. Do audytu trafia jedynie typ encji i liczba zastąpień, bez pozycji i wartości. Score recognizera nie jest deklaracją pewnego wykrycia.

Adapter Jev wymaga odpowiedzi na oba pytania, prawidłowego typu `noul` i skończonych wartości 0–1; brak pola/NaN/wartość poza zakresem jest błędem kontroli. `risk_score = max(instruction_override_probability, data_exfiltration_probability)` to agregat do progowania, nie prawdopodobieństwo sumy zdarzeń. Przy wyniku poniżej progu kategoria jest `benign`; przy przekroczeniu wskazuje dominujące pytanie, a remis rozstrzyga stała kolejność z konfiguracji. Noul nie wymaga pola `confidence`.

`SemanticResult` opisuje ocenę tekstu. Nazwę modelu, czas i zużycie dopisuje adapter na podstawie odpowiedzi dostawcy; zachowuje również nazwę żądaną w konfiguracji, jeśli odpowiedź podaje inną wersję. `cost_status` ma wartości `calculated`, `estimated` lub `unknown`; `calculated` oznacza obliczenie z pełnego usage i cennika, nie uzgodnienie faktury. Powód dla UI pochodzi z naszej mapy kategorii i kodów; model nie generuje niekontrolowanej notatki trafiającej do logów.

`stage`: `admission`, `pre_document`, `pre_detector`, `pre_summary`, `post_output`, `artifact`. `execution_status`: `NOT_CALLED`, `STARTED`, `SUCCEEDED`, `FAILED`, `UNKNOWN`. Status odnosi się do wskazanego adaptera; `adapter_calls` rozdziela `document_read`, `token_count`, `detector`, `summary`, `artifact_admit`. Blokada po odczycie musi pokazywać ten odczyt.

Wynik API zawiera `schema_version`, `request_id`, `task_id`, `decision`, `reason_code`, `policy_version`, `execution_status`, `adapter_calls`, `output`, `redacted_fields`, `usage`, `audit_event_ids`. Przy `DENY` pole `output=null`; przy redakcji i udanym wykonaniu decyzja końcowa to `REDACT`. `usage` jest listą wywołań; status w wyniku dotyczy narzędzia żądanego przez klienta, szczegóły zależności są w audycie.

Minimalne kody: `OK`, `AUTH_REQUIRED`, `INVALID_INPUT`, `TASK_FORBIDDEN`, `CLIENT_FORBIDDEN`, `MODEL_FORBIDDEN`, `TOOL_FORBIDDEN`, `PII_REDACTED`, `SEMANTIC_RISK`, `DETECTOR_UNAVAILABLE`, `PII_ENGINE_UNAVAILABLE`, `BUDGET_EXCEEDED`, `CONCURRENCY_EXCEEDED`, `INPUT_TOO_LARGE`, `TOKEN_COUNT_UNAVAILABLE`, `ARTIFACT_BLOCKED`, `INVALID_CONFIG`, `UPSTREAM_FAILED`, `UPSTREAM_TIMEOUT`, `AUDIT_UNAVAILABLE`.

### Doprecyzowania z A1 — do potwierdzenia przez Pawła

Kod w `app/contracts.py` doprecyzowuje tabelę powyżej. Zmiana tych ustaleń jest zmianą kontraktu.

- Modele są niemutowalne i odrzucają nieznane pola. Liczby całkowite i `schema_version` nie przyjmują `true`, `1.0` ani `"1"`. Czas bez strefy jest błędem i jest normalizowany do UTC.
- `policy_version`, `feed_version` i `limit_version` to rosnące liczby całkowite od 1. `role` przyjmuje `analyst`, `reviewer` lub `admin`. Tożsamość jest w `principal_id`, np. `analyst-a`.
- `control_id` ma wartości `gateway`, `access`, `redaction`, `semantic`, `budget` i `artifacts`. `gateway` obejmuje uwierzytelnienie, schemat, idempotencję i limity żądania.
- `adapter_calls` to obiekt z polami `document_read`, `token_count`, `detector`, `summary` i `artifact_admit`. Każde pole ma `execution_status`, domyślnie `NOT_CALLED`.
- `Usage` ma dodatkowo `requested_model`, czyli nazwę z polityki. `model` jest nazwą z odpowiedzi dostawcy albo `null`. Wszystkie pola trzeba podać jawnie. `calculated` wymaga pełnego usage, kosztu i `pricing_version`, a `estimated` wymaga kwoty.
- `SemanticResult` wymaga `risk_score = max(...)`. Kategoria inna niż `benign` musi wskazywać pytanie o najwyższym wyniku. Wartości NaN, spoza 0–1 i bool są błędem.
- `Reservation` używa jednostki `test_credit` wtedy i tylko wtedy, gdy `purpose=fixture`. `nusd` wymaga `pricing_version`.
- `AuditEvent` ma dodatkowo `schema_version`, `tool`, `agent_id`, `client_id`, `redacted_fields`, `redacted_entity_counts` (tylko typ encji → liczba) i `semantic`. Wartości niedostępne, np. przed załadowaniem polityki, to `null`.
- `output` jest obiektem z polem `kind`: `document` (`document_id`, `fields`), `summary` (`document_id`, `text`) lub `artifact` (`artifact_id`, `sha256`). `DENY` wymaga `output=null`. `ALLOW`/`REDACT` wymagają `SUCCEEDED`, `output` i kodu `OK`/`PII_REDACTED`.
- Błędy HTTP mają postać `ErrorResponse`: `schema_version`, `request_id`, `reason_code` i przy `422` listę `errors` z polami `loc` i `type`, bez przesłanych wartości. Kod `NOT_IMPLEMENTED` zwracają wyłącznie trasy szkieletu.
- Schemat SQLite jest w `app/schema.sql` (`PRAGMA user_version = 1`). Nieznana wersja zatrzymuje start. `audit_events` jest tylko do dopisywania. `budget_accounts` przechowuje `spent`/`reserved`, a limit pochodzi z aktywnej polityki w chwili rezerwacji. Tabele budżetu domyka Paweł w B3.

## 5. API, tożsamości i dane demo

| Endpoint | Dostęp | Zachowanie |
|---|---|---|
| `GET /health` | Publiczny | Stan procesu i konfiguracji, bez kluczy i płatnego pingowania modelu |
| `POST /v1/tasks` | Zalogowany | Body: `schema_version`, `client_id`; serwer sprawdza zakres i nadaje ID/właściciela |
| `POST /v1/execute` | Właściciel zadania | Wykonuje opisany wyżej kontrakt |
| `GET /v1/tasks/{id}` | Właściciel/admin | Stan zadania |
| `GET /v1/tasks/{id}/events` | Właściciel/admin | Decyzje i wykonania w zadaniu, z paginacją |
| `GET /admin/policy` | Admin | Pełna aktywna polityka i wersja |
| `PUT /admin/policy` | Admin | Walidacja całej polityki i atomowa aktywacja |
| `GET /admin/feed`, `PUT /admin/feed` | Admin | Odczyt oraz walidacja/aktywacja pełnego feedu |
| `GET /admin/events` | Admin | Zdarzenia z limitowaną paginacją i filtrem zadania |
| `GET /admin/metrics` | Admin | Liczniki, aktywne/wyłączone kontrole, koszt i rezerwacje |
| `GET /admin/audit/export` | Admin | JSONL z tego samego magazynu co panel |
| `GET /admin/test-results` | Admin | Ostatni zapisany raport testów z czasem i commitem, bez wykonywania testów |

Prawidłowo oceniona operacja zwraca `200` z decyzją, także `DENY`. Brak uwierzytelnienia: `401`; niedozwolony endpoint/cudze zadanie: `403`; zły schemat: `422`; zbyt duże body: `413`; konflikt wersji/idempotencji: `409`; ograniczenie częstotliwości HTTP: `429`; awaria infrastruktury: `503` z bezpiecznym kodem i `request_id`. Awaria adaptera może dać `UPSTREAM_FAILED`; nie jest udaną operacją. Nie ujawniamy w błędach surowych danych wejścia.

MVP używa trzech losowych tokenów demo z `.env`, mapowanych na tożsamości po stronie serwera. Token nigdy nie jest parametrem URL. Panel przechowuje token tylko w pamięci bieżącej karty; nie umieszcza go w HTML repozytorium ani `localStorage`.

| Tożsamość | Zakres danych | Uprawnienia administracyjne |
|---|---|---|
| `analyst-a` | Klient A, pola `company_name`, `status`, `notes` | Brak |
| `reviewer-a` | Klient A, powyższe oraz `review_note` | Brak |
| `admin` | Własne zadania klienta A w zakresie reviewera; wgląd w audyt | Zmiana polityki/feedu, raporty |

`doc-a` należy do `client-a`, `doc-b` do `client-b`. Metadane są w katalogu serwera. W dokumentach umieszczamy syntetyczny email, identyfikator i sekret testowy. Pola `email`, `personal_id`, `secret` są zawsze usuwane w podstawowym profilu; dodatkowo filtrujemy ich określone wzorce w tekście. To ograniczona kontrola, nie wykrywanie wszystkich możliwych danych osobowych.

Do Jev i OpenAI dopuszczamy wyłącznie pola `company_name`, `status`, `notes` i oczyszczony prompt; `review_note` pozostaje poza wysyłką do dostawcy. Dotyczy to także endpointu liczenia tokenów. Wszystkie dane demonstracyjne są fikcyjne.

### Doprecyzowania z A2 — do potwierdzenia przez Pawła

- **Tokeny.** Katalog tożsamości jest w `app/auth.py`: `analyst-a` (rola `analyst`), `reviewer-a` (`reviewer`) i `admin` (`admin`). Wszystkie trzy mają klienta `client-a` i `agent_id=demo-agent`. Token jest przyjmowany wyłącznie z nagłówka `Authorization: Bearer`. Token za krótki (poniżej 32 lub powyżej 256 znaków), z innymi znakami niż RFC 6750 albo powtórzony dla dwóch tożsamości zatrzymuje start. Brak tokenu wyłącza tylko daną tożsamość. `make setup` wpisuje losowe tokeny w puste zmienne `.env` i nie nadpisuje istniejących wartości.
- **Kody `401` i `403`.** Bez poprawnego tokenu każdy endpoint poza `/health` i panelem zwraca `401 AUTH_REQUIRED` z nagłówkiem `WWW-Authenticate: Bearer`. Uwierzytelnienie poprzedza walidację schematu. Nowy kod `ADMIN_REQUIRED` (`403`) oznacza zalogowanego użytkownika bez roli admina na `/admin/*`. Wymaganie roli jest ustawione dla całego routera, więc obejmuje także przyszłe trasy.
- **Zadania.** `POST /v1/tasks` zwraca `201` z `TaskResponse` (`schema_version`, `task_id`, `principal_id`, `agent_id`, `client_id`, `created_at`). Klient spoza zakresu tożsamości, w tym nieistniejący, daje `403 CLIENT_FORBIDDEN`. `GET /v1/tasks/{id}` jest dostępny dla właściciela i admina. Nieznane i cudze zadanie dają ten sam `403 TASK_FORBIDDEN`. `POST /v1/execute` wykonuje wyłącznie właściciel zadania, także gdy jest nim admin.
- **Konfiguracja.** `POST /v1/execute` przypina aktywne wersje polityki i feedu. Bez obu kończy się `503 INVALID_CONFIG`, zanim zadziała jakikolwiek adapter. Od A4 `make setup` importuje pliki z `config/` (doprecyzowania w sekcji 6).
- **Dostęp do dokumentu.** Kontrola dostępu sprawdza katalog `data/documents/catalog.json` i nie otwiera treści. Dokument nieznany i dokument innego klienta dają ten sam wynik: `200`, `DENY`, `CLIENT_FORBIDDEN`, etap `pre_document`, wszystkie adaptery `NOT_CALLED`. Dotyczy to też `documents.summarize`.
- **Pola według roli.** Po odczycie zostają tylko pola z listy dozwolonych dla roli, zgodnie z tabelą powyżej; od A4 lista pochodzi z polityki (`acl.<rola>.fields`). Pozostałe pola trafiają z nazwy do `redacted_fields`, a wynik ma `REDACT` i `PII_REDACTED`.
- **Błąd adaptera.** Nieczytelny lub niezgodny plik dokumentu daje `DENY` z `UPSTREAM_FAILED`, `execution_status=FAILED` i `document_read=FAILED`, bez treści. `DocumentAdapter.reads` liczy każde wywołanie, także nieudane.
- **Kolejne kroki.** `documents.summarize` i zapis `Idempotency-Key` działają od A5 (sekcja 3), `artifacts.admit` od A6 (sekcja 6).
- **Logi i czas w bazie.** Access log Uvicorna zapisuje ścieżkę bez query stringu, bo token wysłany przez pomyłkę w URL nie może trafić do logów. Czas w bazie zapisuje `db.to_db_time()` w formacie `YYYY-MM-DDTHH:MM:SS.ffffffZ`.

## 6. Jedna polityka, jeden feed

Minimalna zawartość polityki, do zapisania w JSON podczas A4:

| Pole | Wartość początkowa / reguła |
|---|---|
| `schema_version`, `policy_version` | `1`, wersja generowana przez serwer przy zmianie |
| `controls` | Dostęp, redakcja, semantyka, budżet i artefakty: włączone |
| `semantic.block_threshold` | `0.80`; blokuj przy `score >= threshold` |
| `semantic.on_error` | `deny` |
| `models.allowed` | `jev-1.13.0`, `gpt-6-luna`; role modeli są rozdzielone |
| `models.detector`, `models.summary` | `jev-1.13.0`, `gpt-6-luna` |
| `models.summary_max_output_tokens` | `2048`; Jev nie używa parametru wyjścia OpenAI |
| `models.detector_reserved_input_tokens` | `65536`, konserwatywna granica do potwierdzenia z taryfą w B1 |
| `models.summary_reasoning_effort`, `models.summary_timeout_seconds` | `low`, `30` |
| `models.detector_timeout_seconds` | `10` |
| `resources.max_summary_input_tokens` | `8192`, dla kompletnego wejścia Luny |
| `resources.max_detector_state_chars` | `12000`, stan Jev plus ograniczone pytania; bez cichego ucinania |
| `resources.max_requests_per_task` | `20` |
| `resources.max_provider_calls_per_task` | `40`, łącznie liczenie tokenów, detekcja i podsumowanie |
| `resources.max_concurrency_per_principal` | `2` żądania aplikacyjne w toku |
| `resources.max_tasks_per_principal` | `10` w jednej bazie demo; nowy task nie zeruje limitów nadrzędnych |
| `resources.max_requests_per_minute_per_principal` | `30` |
| `budget.task_limit_nusd` | `50000000` = 0,05 USD |
| `budget.principal_limit_nusd` | `200000000` = 0,20 USD |
| `budget.global_limit_nusd` | `500000000` = 0,50 USD dla tego demo |
| `acl`, `outbound_fields` | Role i pola z sekcji 5; zakres narzędzi zapisany jawnie |
| `redaction` | Silnik Presidio, encje, języki, progi per encja, operatory i wersja recognizerów z sekcji 2 |
| `pricing` | Wersja, data i URL źródła, model/tryb, stawki i konserwatywna stawka wejścia |

Kwoty to nasze limity demonstracji, nie ceny modelu ani gwarancja całego rachunku dostawców. B4 potwierdza osobno taryfę [OpenAI](https://developers.openai.com/api/docs/pricing) i [TypeSafe](https://docs.typesafe.ai/models). Nie kopiujemy cen z wcześniejszego researchu. Do czasu wpisania poprawnej tabeli cen profil live nie uruchamia generowania.

Pliki JSON służą do startu/importu. Po aktywacji źródłem prawdy jest zapisana w SQLite aktywna wersja, widoczna w API; restart odtwarza ją z bazy. `make reload-config` ma importować zmienione pliki przez tę samą walidację co panel. Edycja pliku bez aktywacji nie zmienia stanu serwera. Żaden endpoint nie przyjmuje dowolnej ścieżki importu.

Aktualizacja wysyła `expected_version` i pełną konfigurację. Serwer waliduje, nadaje nową wersję i atomowo podmienia wskaźnik aktywnej konfiguracji. Stary `expected_version` daje `409`. Błędna aktualizacja zachowuje poprzednią wersję; pierwszy start bez poprawnej konfiguracji odmawia chronionych operacji. Zmniejszenie limitu poniżej obecnego `spent + reserved` blokuje nowe rezerwacje; nie usuwa historii ani zobowiązań. Przypięta polityka opisuje decyzje kontroli, a limiter przed każdą nową rezerwacją respektuje także aktualny nadrzędny limit; jego wersję zapisuje w rezerwacji/audycie.

Feed: `schema_version`, `feed_version`, `rules[]`; każda reguła ma `rule_id`, `kind=sha256`, `value`, `source`, `reason`, `is_test_fixture`. Walidujemy długość/format hashy i maks. 1000 reguł; bez skryptów czy wyrażeń wykonywalnych. Źródłem jest odrębny plik admina, imitujący zewnętrzne zarządzanie blokadami.

`artifacts.admit` przyjmuje ID z katalogu serwera. Serwer czyta maks. 64 KiB, liczy SHA-256, sprawdza manifest i feed, parsuje tylko JSON zgodny ze schematem. Sprawdza i używa tych samych bajtów. Nie deserializuje pickle, nie uruchamia kodu, nie pobiera malware. Test dopisuje hash bezpiecznego artefaktu do feedu i wykazuje blokadę przed jego użyciem. W README testu należy wskazać źródło historycznej klasy zagrożenia; ten test nie odtwarza pełnego ataku na łańcuch dostaw.

### Doprecyzowania z A4: polityka — do potwierdzenia przez Pawła

- **Plik i model.** `config/policy.json` waliduje model `Policy` w `app/policy.py`. Plik nie zawiera `policy_version`, bo numer nadaje serwer. Pola ponad tabelę powyżej:
  - `controls.access`, `redaction` i `budget` muszą mieć wartość `true`. Od A5 także `semantic`. `artifacts=false` odmawia całego `artifacts.admit` (`TOOL_FORBIDDEN`); nigdy nie przepuszcza artefaktu bez kontroli.
  - `models.allowed` może zawierać tylko `jev-1.13.0` i `gpt-6-luna`. Detektor musi być modelem TypeSafe, a podsumowanie modelem OpenAI. `summary_reasoning_effort` ma tylko wartość `low`, bo tak wysyła adapter.
  - `acl.<analyst|reviewer|admin>` ma `tools` i `fields`. `outbound_fields` to pola, które mogą trafić do dostawcy.
  - `email`, `personal_id` i `secret` nie mogą znaleźć się ani w `acl`, ani w `outbound_fields`.
- **Redakcja w polityce.** `redaction` wymaga:
  - `engine=presidio` i `recognizers_version=controlproof-pii-1`;
  - `languages` z zakresu `en`/`pl`;
  - wszystkich pięciu encji z `threshold` i `placeholder` w postaci `<WIELKIE_LITERY>` oraz `secret_placeholder`.
- **Ceny.** `pricing` ma pola `PricingTable` z `app/pricing.py` oraz `verified_on`, `mode=standard` i `source_urls` (tylko https). Modele w cenniku muszą zgadzać się z `models`.
- **Obiekty dla A5.** `Policy.budget_limits(policy_version)` daje `BudgetLimits` z `limit_version = policy_version`. `Policy.pricing.table()` daje `PricingTable`. Wartości w repo odpowiadają `DEFAULT_PRICING` Pawła.
- **Narzędzia.** Domyślnie `artifacts.admit` ma tylko admin. Narzędzie spoza `acl.<rola>.tools` daje `200 DENY TOOL_FORBIDDEN` (etap `pre_document`, dla artefaktów `artifact`) przed silnikiem PII i katalogiem.
- **API.** `GET /admin/policy` zwraca `ActivePolicy`: `schema_version`, `policy_version`, `sha256`, `created_at`, `created_by` i `policy`; bez aktywnej polityki odpowiada `503 INVALID_CONFIG`. `PUT /admin/policy` przyjmuje `{schema_version, expected_version, policy}`; `expected_version=null` działa tylko wtedy, gdy nic nie jest aktywne. Odpowiedzi:
  - niepoprawna polityka: `422 INVALID_INPUT`, bez zapisu;
  - nieaktualny `expected_version`: `409` z nowym kodem `VERSION_CONFLICT`.

  W obu przypadkach aktywna wersja zostaje.
- **Zapis.** Wersja jest zapisywana jako kanoniczny JSON (posortowane klucze) z SHA-256. Przy odczycie serwer sprawdza skrót i ponownie waliduje treść. Zmieniona lub niezgodna z kodem wersja daje `503 INVALID_CONFIG`, a `/health` pokazuje wtedy `protected_operations=disabled`.
- **Jedna wersja na żądanie.** Żądanie ładuje politykę przypiętą przy przyjęciu i używa jej do końca. Test zmienia politykę w trakcie odczytu dokumentu; odpowiedź i zdarzenia mają starą wersję, a dopiero następne żądanie nową.
- **Import z plików.** `make setup` uruchamia `python -m app.policy seed`, który importuje tylko rodzaje bez aktywnej wersji. `make reload-config` (`python -m app.policy reload`) najpierw waliduje oba pliki, a potem aktywuje te, których treść się zmieniła. Błąd w którymkolwiek pliku nie aktywuje niczego. Serwer nie czyta plików `config/` podczas pracy.
- **Feed.** Model `Feed`/`FeedRule` też jest w `app/policy.py`; `config/threat-feed.json` startuje z pustą listą `rules`. `source` i `reason` dopuszczają tylko krótki tekst bez znaków specjalnych. Użycie reguł i API opisuje sekcja „Doprecyzowania z A6”.

### Doprecyzowania z A6: feed, artefakty i panel — do potwierdzenia przez Pawła

- **Artefakty.** `data/artifacts/manifest.json` przypisuje `artifact_id` zadeklarowany SHA-256; treść leży w `data/artifacts/content/<id>.artifact` (`.gitattributes` zabrania konwersji bajtów). Nieznany lub błędny manifest zatrzymuje start. Dane demo: `art-summary-template` i `art-model-card` (poprawne), `art-tampered` (bajty inne niż w manifeście), `art-pickle` (nagłówek podobny do pickle, nie JSON; nigdy niedeserializowany).
- **Przebieg `artifacts.admit`** (etap `artifact`, bez AI i bez rezerwacji): narzędzie roli → `controls.artifacts` → artefakt w manifeście (brak: `DENY ARTIFACT_BLOCKED`, bez odczytu) → intencja `artifacts ALLOW STARTED` → jeden odczyt maks. 64 KiB (więcej: `INPUT_TOO_LARGE`, błąd: `UPSTREAM_FAILED`, oba `FAILED`) → SHA-256 tych bajtów = manifest → hash poza przypiętym feedem → parsowanie tych samych bajtów modelem `ArtifactDocument` (`schema_version`, `artifact_id` zgodny z wpisem, `kind` `prompt_template`/`model_card`, `title`, `body`). Każda niezgodność: `DENY ARTIFACT_BLOCKED` z `artifact_admit=SUCCEEDED` (odczyt się odbył). Sukces: `ALLOW OK`, `output.kind=artifact` z hashem. Kod nie rozróżnia w audycie, która z trzech kontroli zablokowała — wymagałoby to nowego pola `AuditEvent`.
- **Klasa zagrożenia.** CWE-502 (deserializacja niezaufanych danych), np. pliki modeli w formacie pickle wykonujące kod przy wczytaniu. Testy w `tests/gateway/test_artifacts.py` pokazują blokadę przed użyciem, nie odtwarzają ataku. Konkretny CVE do slajdów — do potwierdzenia z mentorem (sekcja 11).
- **Przypięcie feedu.** Przyjęcie żądania ładuje i waliduje także aktywny feed; uszkodzona wersja daje `503 INVALID_CONFIG` dla każdego narzędzia. Zmiana feedu w trakcie żądania działa od następnego żądania.
- **API feedu.** `GET /admin/feed` zwraca `ActiveFeed` (`schema_version`, `feed_version`, `sha256`, `created_at`, `created_by`, `feed`); bez feedu `503 INVALID_CONFIG`. `PUT /admin/feed` przyjmuje `{schema_version, expected_version, feed}`; niepoprawny feed `422`, stary `expected_version` `409 VERSION_CONFLICT`; w obu przypadkach reguły zostają.
- **`GET /admin/metrics`** (`app/metrics.py`): wersje i liczba reguł, stan przełączników `controls`, `requests_seen` (różne `request_id` w audycie), `outcomes` (zapisane odpowiedzi według decyzji oraz `IN_PROGRESS`/`UNKNOWN`), `denials` (zdarzenia `DENY` według kodu), budżet nUSD globalny i per użytkownik z limitami aktywnej polityki (`remaining` może być ujemne po obniżeniu limitu), koszt `detector`/`summary` (rozliczony i wstrzymany w `RESERVED`/`STARTED`/`UNKNOWN`), rezerwacje według stanu i opóźnienia (p50/max) per `control_id`/`stage`. Liczenie tokenów Luny ma własną rezerwację `summary`.
- **`GET /admin/test-results`** (`app/reports.py`): najnowszy czytelny raport każdego rodzaju z `var/reports` (`jev-evaluation-*`, `benchmark-offline-*`, `benchmark-live-*`), tylko liczby podsumowania, z commitem raportu i `matches_current_commit`. Nie uruchamia testów. `make test` nie zapisuje raportu (`offline_suite=not_recorded`) — propozycja dla B5.
- **Panel** (`app/static/`): jeden ekran — sesja z tokenem w pamięci karty, formularz żądania i przyciski demo przez tę samą funkcję i ten sam `POST /v1/execute`, stan kontroli (decyzja, adaptery, wynik Jev, redakcja, usage, ślad audytu), historia odpytywana co 2 s, eksport JSONL, a dla admina budżet, kontrole, edytor polityki i feedu (z blokowaniem hasha jednym przyciskiem) oraz raporty testów. Wartości renderuje wyłącznie `textContent`. Fonty Inter i Syne (OFL) są lokalne, bo CSP pozwala tylko na `'self'`.

## 7. Rezerwacje, rozliczanie i błędy

### Co jest wspólne dla obu osób

Paweł implementuje `reserve(context, purpose, unit, amount)`, `settle(reservation_id, actual_usage)`, `release_not_sent(reservation_id)` i `mark_unknown(reservation_id)`. Maciek używa ich w gatewayu. Jednostki `nusd` i `test_credit` mają osobne salda; nie wolno ich dodawać. 1 USD = 1 000 000 000 nUSD.

W jednej krótkiej transakcji SQLite sprawdzamy limity zadania, użytkownika i całego demo oraz dopisujemy rezerwację do wszystkich właściwych liczników. Warunek w każdym zakresie: `spent + reserved + requested <= limit`. Rezerwacja i liczniki są trwałe. Nie trzymamy transakcji przez czas wywołania Jev ani OpenAI. Przy zajętej bazie stosujemy ograniczony retry transakcji, nie ponowienie wywołania dostawcy. SQLite dopuszcza pojedynczego zapisującego; mechanikę transakcji opisuje [dokumentacja SQLite](https://www.sqlite.org/lang_transaction.html).

`RESERVED` → `STARTED` zapisujemy przed wysłaniem generacji; następnie `SETTLED` przy znanym zużyciu, `RELEASED` przy pewności, że nic nie wysłano, albo `UNKNOWN` przy niepewnym skutku. `UNKNOWN` zachowuje rezerwację pieniędzy/tokenów i zajęty slot wywołania dostawcy do wyjaśnienia. Slot żądania HTTP można zwolnić oddzielnie. Po restarcie pozostałe `RESERVED`/`STARTED` przechodzą konserwatywnie w `UNKNOWN`, bez zerowania sald.

Rozliczamy także detektor, który zakończył się blokadą, oraz odpowiedź odrzuconą przez filtr. Odmowa biznesowa nie cofa kosztu wykonanego wywołania. Odzyskanie statusu `UNKNOWN` wymaga dowodu z dostawcy lub jawnego ręcznego uzgodnienia; samo odświeżenie panelu nie zwalnia salda.

### Jev: osobna taryfa i rezerwacja

Adapter `jev.py` nie używa tokenizera OpenAI ani `max_output_tokens`. W P0 rezerwuje konserwatywnie koszt całego maksymalnego wejścia obsługiwanego przez wybraną wersję, z zapasem: `65536 × input_rate_nusd`. Paweł potwierdza tę granicę i taryfę przed live; przy braku potwierdzenia wywołanie jest blokowane. Taki zapas może odmówić taniej operacji przy końcówce budżetu — pokazujemy to jawnie.

Po odpowiedzi rozliczamy rzeczywiste `usage.input_tokens` według taryfy TypeSafe. Jeżeli taryfa nie nalicza wyjścia, jego tokeny zapisujemy jako zużycie z zerową stawką kosztową; nie stosujemy ceny wyjścia Luny. Przy nieznanym koszcie, błędzie po wysłaniu lub timeoutcie zachowujemy rezerwację. Oba adaptery korzystają z tych samych nadrzędnych sald, osobnych rekordów usage i tej samej zasady braku niejawnych retry.

### Realne OpenAI — podsumowanie

1. Najpierw sprawdź uprawnienia i usuń niedopuszczone dane. Zamroź kompletne wejście wraz z instrukcjami i schematem.
2. Ogranicz liczbę i równoległość żądań do dostawcy. Policz pełne wejście przez `responses.input_tokens.count`; uwzględnij instrukcje i schemat. Ten endpoint także otrzymuje dane, więc podlega regułom wyjścia. Jeśli liczenie nie działa, zakończ `TOKEN_COUNT_UNAVAILABLE` przed generowaniem.
3. Rezerwuj `input_tokens × max_input_rate_nusd + max_output_tokens × output_rate_nusd`. Stawka wejścia ma uwzględniać najdroższy możliwy wariant dla wybranego trybu, w tym zapis cache, jeśli może wystąpić. Profil demo dopuszcza tylko krótkie teksty i ustalony tryb; inne modele/usługi/regiony wymagają osobnej tabeli.
4. Wyślij dokładnie policzone wejście z ustalonym limitem wyjścia. Każde ponowienie potrzebuje nowej kontrolowanej próby; SDK nie ponawia automatycznie. Ta rezerwacja dotyczy podsumowania; Jev ma rezerwację według swojej taryfy.
5. Rozlicz na podstawie `usage`. `output_tokens` obejmuje również tokeny niewidoczne w odpowiedzi. Przy niepełnych danych o rozliczeniu zachowaj konserwatywną kwotę i oznacz koszt jako szacowany/niepewny. Nie pokazuj jej jako potwierdzonej faktury.

Endpoint liczenia i znaczenie tokenów wyjścia potwierdza [dokumentacja liczenia tokenów](https://developers.openai.com/api/docs/guides/token-counting). Dostępność na koncie i obsługę pełnego payloadu sprawdza B1. Bez potwierdzonej górnej granicy kosztu nie opisujemy limitu jako twardej gwarancji finansowej. Obsługa innych wywołań poza gatewayem jest poza zakresem naszego licznika.

### Test współbieżności

Oddzielny profil offline: 500 `test_credit`, 20 równoczesnych żądań, każde rezerwuje i ostatecznie zużywa 100. Limit równoległości co najmniej 20; limity użytkownika i globalny nie mogą wcześniej zablokować prób. Semantyka nie dotyczy tego testowego narzędzia. Bariera zatrzymuje pierwsze 5 w wykonawcy do czasu odmowy pozostałych. Oczekiwany wynik: 5 wykonań, 15 odmów budżetu, zużycie 500.

Ten profil jest dostępny wyłącznie w testach lub jawnie włączonym lokalnym środowisku laboratoryjnym. Nie jest narzędziem produkcyjnego API. Jednostki testowe nie są USD; kontrola zasobów lokalnego adaptera nie dowodzi uruchomienia lokalnego modelu.

## 8. Trwałość, audyt i panel

Minimalne tabele: `tasks`, `requests` (idempotencja i wynik), `budget_accounts`, `reservations`, `audit_events`, `config_versions`. Schemat i inicjalizację zapisuje Maciek, tabele budżetu uzgadnia z Pawłem. Wszystkie kwoty i liczniki są integer; wszystkie aktualizacje sald transakcyjne.

Audyt zawiera wynik każdej kontroli i wykonania. Nie zapisuje body, pełnego promptu, dokumentów, tokenów dostępowych ani surowych błędów SDK. `redacted_fields` zawiera nazwy pól, nie usunięte wartości. Zapis intencji przed chronionym wykonaniem jest wymagany; awaria tego zapisu kończy się `AUDIT_UNAVAILABLE`. Jeśli zapis końcowy zawiedzie po wykonaniu, stan pozostaje do uzgodnienia — odpowiedź nie może twierdzić, że nic się nie wykonało.

Panel pokazuje aktywne i wyłączone kontrole, wersję konfiguracji/feedu, ostatnie decyzje i powody, wykonania adapterów, `spent/reserved/remaining`, osobno koszt detektora i podsumowania, błędy oraz opóźnienia. Raport testów ma czas, commit, tryb offline/live i liczbę przypadków; stary raport nie może wyglądać jak bieżący test.

Eksport JSONL pochodzi z tych samych `audit_events`. Nie wymyślamy procentowego „poziomu bezpieczeństwa” ani „zaoszczędzonych pieniędzy”. Przełączniki bez kontroli backendowej nie są zabezpieczeniami.

### Doprecyzowania z A3 — do potwierdzenia przez Pawła

- **Zdarzenia.** Gateway zapisuje `AuditEvent` po każdym kroku (`RequestTrail` w `app/audit.py`). Każde zdarzenie ma `event_id`, `request_id` (ten sam co nagłówek `X-Request-ID`), kontrolę, etap, decyzję, kod, wersje polityki/feedu i stan `adapter_calls` z chwili zapisu. Odmowa po odczycie pokazuje więc ten odczyt. Odpowiedź `POST /v1/execute` podaje identyfikatory zdarzeń w `audit_event_ids`.
- **Kroki `documents.read`.** Zdarzenia w kolejności zapisu:

| Krok | `control_id` / `stage` | Zapis |
|---|---|---|
| Cudze lub nieznane zadanie | `access` / `admission` | `DENY TASK_FORBIDDEN`, `task_id` z żądania, `client_id=null` |
| Brak aktywnej polityki lub feedu | `gateway` / `admission` | `DENY INVALID_CONFIG` |
| Przyjęcie żądania | `gateway` / `admission` | `ALLOW OK`, przypięte wersje |
| Dokument innego klienta lub nieznany | `access` / `pre_document` | `DENY CLIENT_FORBIDDEN`, adaptery `NOT_CALLED` |
| Intencja przed odczytem | `access` / `pre_document` | `ALLOW OK`, `STARTED`, `document_read=STARTED` |
| Błąd odczytu | `gateway` / `pre_detector` | `DENY UPSTREAM_FAILED`, `FAILED`, `latency_ms` |
| Odczyt i usunięcie pól | `redaction` / `pre_detector` | `REDACT PII_REDACTED` lub `ALLOW OK`, `SUCCEEDED`, `redacted_fields`, `latency_ms` |

- **Znaczenie pól.** `pre_detector` to etap po odczycie dokumentu, przed wysłaniem danych do Jev lub OpenAI. Kolejne kroki od A5 opisuje sekcja 3. `execution_status` zdarzenia dotyczy adaptera, który dany krok uruchamia lub kończy; sama decyzja ma `NOT_CALLED`. `latency_ms` to czas wywołania adaptera; w pozostałych zdarzeniach `null`. `usage`, `model` i `semantic` wypełniają zdarzenia dostawców (A5). Kroki `artifacts.admit` opisuje sekcja 6 (A6).
- **Awaria zapisu.** Każde zdarzenie to jeden `INSERT` w autocommit, wykonany przed następnym krokiem. Jeśli nie zapisze się zdarzenie przed wywołaniem adaptera (przyjęcie, odmowa lub intencja), odpowiedź to `503 AUDIT_UNAVAILABLE`, a adapter nie startuje. Jeśli nie zapisze się wynik po odczycie, odpowiedź to `200`, `DENY`, `AUDIT_UNAVAILABLE` z `output=null`; `execution_status` i `adapter_calls` pokazują wykonany odczyt. Zapisana intencja zostaje `STARTED` do uzgodnienia. Log aplikacji podaje wtedy tylko `request_id`, etap i klasę błędu.
- **Odczyt.** `GET /v1/tasks/{id}/events` (właściciel i admin) zwraca zdarzenia właściciela zadania; próby innych osób na tym zadaniu widzi admin w `GET /admin/events`. `GET /admin/events` filtruje po `task_id` i `request_id`. Oba endpointy zwracają `AuditEventPage` (`schema_version`, `events`, `next_after`) od najstarszych; `limit` 1–200 (domyślnie 50), następna strona przez `after=next_after`, ostatnia ma `next_after=null`. `GET /admin/audit/export` zwraca wszystkie zdarzenia jako JSON Lines (`application/x-ndjson`), czytane partiami z tej samej tabeli. Odpowiedzi `/v1/*` i `/admin/*` mają `Cache-Control: no-store`.
- **Bez treści.** `AuditEvent` nie ma pola na dowolny tekst: tylko identyfikatory, wartości enum, nazwy pól, liczby i usage. Żądania bez poprawnego tokenu i z błędnym schematem nie trafiają do audytu, żeby anonimowy klient nie mógł zapisywać do bazy; widać je w access logu bez query stringu. Testy sprawdzają bazę, eksport i logi pod kątem tokenów i wartości dokumentów.

## 9. Wspólne testy i komendy do dostarczenia

| Grupa | Właściciel | Minimalny dowód |
|---|---|---|
| Tożsamość i dostęp | Maciek | Brak tokenu, cudzy task, podmieniona rola, A/B, niedozwolone narzędzie: odpowiedni etap odmowy |
| Dane | Maciek | Sekret/PII nie występuje w wyjściu do Jev/OpenAI, panelu ani audycie; role mają różny zakres |
| Polityka i feed | Maciek | Reload zmienia wynik, błędna aktualizacja zachowuje ochronę, podmiana bajtów/niebezpieczny format daje blokadę |
| Semantyka | Paweł | Granica progu na stubie; osobna ewaluacja prawdziwego Jev z błędami klasyfikacji |
| Budżet | Paweł | Granica limitu, 20/5, restart, timeout, retry, limity między zadaniami i koszt detektora |
| Integracja i audyt | Oboje | Legalny przepływ, każdy etap błędu, idempotencja i brak pominięcia gatewaya w pokazanym zakresie |

Każda kontrola ma test wykrywający jej wyłączenie w kopii testowej. Zestaw AI: co najmniej 12 nowych próbek, oddzielonych od strojenia progu; raportujemy false positives i false negatives oraz wynik każdej próbki. Ustalony cel odbioru dla tego małego zestawu: co najmniej 5/6 legalnych i 5/6 manipulacji ocenionych zgodnie z etykietą. To cel zespołu, nie dowód skuteczności ogólnej. Niespełniony cel oznacza jawny wynik negatywny, a nie podmianę próbek po fakcie.

| Planowana komenda | Zadanie |
|---|---|
| `make setup` | `uv sync --locked`, przygotowanie lokalnej bazy bez nadpisania istniejących sekretów |
| `make dev` | Uvicorn + statyczny panel, lokalnie na `127.0.0.1:8000` |
| `make check` | Ruff lint i sprawdzenie formatu |
| `make test` | Wszystkie testy offline, zablokowana sieć do TypeSafe i OpenAI |
| `make test-live` | Jawne płatne testy Jev i Luny, lokalne sprawdzenie Presidio i zapis raportu; brak klucza/modelu lub niespełnione kryteria dają niezerowy exit |
| `make verify` | `check`, `test`, `test-live` |
| `make benchmark` | Pomiar offline; `LIVE=1` dodaje ograniczoną serię Jev/OpenAI w obrębie budżetu |
| `make reload-config` | Zweryfikowany import plików polityki/feedu przez wspólną ścieżkę aktywacji |
| `make reset-demo` | Reset wyłącznie syntetycznych zadań i lokalnej bazy demo, po świadomym wywołaniu przez operatora |

Po A1 działają `make setup`, `make dev`, `make check` i `make test`; od A2 `make setup` uzupełnia także puste tokeny demo, a od A4 importuje konfigurację i sprawdza Presidio. Od A4 działa też `make reload-config`; `make test-live`, `make verify` i `make benchmark` dostarczyła osoba 2. `make reset-demo` kończy się błędem do czasu implementacji. README otrzyma sprawdzone instrukcje podczas A7/B6. Reset nie resetuje rzeczywistego rachunku dostawcy. Każdy raport podaje datę, model, konfigurację, commit, liczebność, błędy i zakres; offline oraz live są widoczne osobno.

## 10. Warunki ukończenia

Oboje potraficie: uruchomić projekt z lockfile, wykonać demo z planu, zmienić politykę i feed, odczytać przyczynę odmowy, pokazać test 20/5 i eksport audytu. Drugi laptop uruchamia całość z README. Wszystkie rodziny podstawowych kontroli mają działającą ścieżkę i wynik testów.

Maciek przygotowuje opis i PDF do 10 slajdów; Paweł dostarcza dowody, instrukcję i nagranie. Materiały konkursowe przygotowujemy po angielsku. Wskazujemy zależność od internetu/API, ograniczony zakres redakcji, omylność detektora oraz brak izolacji od administratora hosta.

## 11. Źródła i kwestie do potwierdzenia

Przeczytano [pełny brief](../dane_wejsciowe/opis_tasku.pdf), [regulamin](../dane_wejsciowe/terms.pdf) i [transkrypcję mentora](../dane_wejsciowe/rozmowa.txt). Wymagania podstawowe obejmują działającą warstwę, politykę, hybrydę reguł/AI, dashboard, audyt i wykonywalne testy. Jury może zmieniać konfigurację i wpisywać własne wejścia. Agent biznesowy nie jest ocenianym rdzeniem.

| Kwestia | Stan / właściciel |
|---|---|
| Zewnętrzne API zamiast lokalnego detektora | Decyzja zespołu: Jev do oceny i Luna do generowania; Presidio działa lokalnie. Brief wskazuje oczekiwanie modeli lokalnych i brak dostarczanych subskrypcji. Paweł potwierdza u mentora dopasowanie wariantu API. Nie uznajemy automatycznie tej różnicy za rozstrzygniętą. |
| Zasoby lokalnych modeli | W P0 pokazujemy wspólny mechanizm limitów na lokalnym adapterze testowym. To nie jest lokalna inferencja. Jeśli partner wymaga działającego lokalnego modelu, trzeba wspólnie zmienić zakres. |
| Dostęp do Jev i OpenAI | Osobne klucze, dostęp do obu modeli, taryfy/limity i internet — weryfikuje Paweł w B1. |
| Start i deadline | `terms.pdf`, pkt 5 zapisuje 3.10 11:00 PM → 4.10 11:00 PM; starsze materiały podawały 11:00. Maciek zapisuje wiążącą odpowiedź organizatora z datą i źródłem. Nie rozstrzygamy PM samodzielnie. |
| Wagi | Brief: 30/20/20/15/15; terms: 30/20/20/20/10. Maciek potwierdza wiążącą wersję. Testy i raportowanie pozostają w podstawie. |
| Historyczny exploit | Maciek pokazuje mentorowi walidację artefaktu/feed i potwierdza, czy taki zakres spełnia oczekiwanie, czy potrzebny jest przykład konkretnego CVE. |

Potwierdzenia dopisujemy w tej tabeli. Do czasu odpowiedzi zachowujemy bufor do wcześniejszego terminu. Starsze porównania pomysłów, czteroosobowy skład i inne kategorie są w archiwum i nie sterują implementacją.
