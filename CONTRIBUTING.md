# Zasady pracy dwóch osób

Obowiązują dla ludzi i używanych przez nich asystentów AI. Kolejność zadań jest w [planie](docs/PLAN_DWOCH_OSOB.md), a techniczny kontrakt we [wspólnych ustaleniach](docs/WSPOLNE_USTALENIA.md).

## 1. Odpowiedzialność

**Maciek integruje produkt. Paweł odpowiada za AI, budżet i wspólny zestaw testów. Każda osoba testuje własne moduły.**

| Właściciel | Planowane pliki / katalogi |
|---|---|
| Maciek | `app/main.py`, `app/api/`, `app/gateway.py`, `app/auth.py`, `app/policy.py`, `app/audit.py`, `app/controls/access.py`, `app/controls/redaction.py`, `app/pii/`, `app/controls/artifacts.py`, `app/adapters/documents.py`, `app/tasks.py`, `data/`, `app/static/` |
| Paweł | `app/controls/semantic.py`, `app/budget.py`, `app/adapters/openai_luna.py`, `app/adapters/jev.py`, `app/prompts/`, `tests/semantic/`, `tests/budget/`, `tests/live/`, `scripts/evaluate.py`, `scripts/benchmark.py` |
| Wspólne; zapis koordynuje Maciek | `app/contracts.py`, `app/db.py`, `app/schema.sql`, `config/`, `pyproject.toml`, `uv.lock`, `Makefile`, README i dokumentacja |
| Testy własnej części | Maciek: `tests/gateway/`, `tests/policy/`, `tests/data/`, `tests/audit/`. Paweł scala wykonanie całego zestawu. |

Właściciel to pierwsza osoba odpowiedzialna za ukończenie i poprawki. Druga osoba może pomóc po krótkim ustaleniu zakresu. Nie edytujcie równocześnie tego samego pliku. Zmianę kontraktu, schematu bazy lub zależności najpierw opiszcie drugiej osobie, potem wprowadźcie razem z aktualizacją dokumentacji i wywołań.

## 2. Małe zadania i częsta integracja

1. Weź jeden krok z planu, np. A3 lub B4. Powiedz drugiej osobie, które pliki zmieniasz.
2. Zapisz jedno zdanie: „Gotowe, gdy …”, z obserwowalnym wynikiem.
3. Zaimplementuj ten krok, wykonaj testy jego zachowania i obejrzyj diff.
4. Przekaż zmianę wraz z komendą weryfikacji, wynikiem i znanymi brakami.
5. Połączcie pracę co 1–2 godziny. Po integracji uruchomcie wspólną ścieżkę allow/deny.

Nie czekajcie do końca, aż cała połowa projektu będzie gotowa. Testowy zamiennik drugiego modułu ma być jawnie oznaczony i usunięty ze ścieżki live przed odbiorem etapu.

## 3. Git

- Każda osoba pracuje we własnym klonie lub worktree. Dwa branche w tym samym katalogu nie izolują edycji plików.
- Krótkie branche: `codex/a-gateway`, `codex/b-budget`, potem następne zadania. Punktem wyjścia jest aktualna wspólna gałąź główna.
- Małe commity według rezultatu, np. `feat: deny cross-client document access` albo `test: verify concurrent budget reservations`.
- Maciek scala zmiany po przeglądzie przez drugą osobę i przejściu wymaganych testów. Zmiany Maćka przegląda Paweł.
- Przed integracją pobierz aktualny stan. Konflikty we wspólnych kontraktach rozwiążcie razem; nie wybierajcie automatycznie całej „naszej” lub „ich” wersji.
- Nie commitujcie `.env`, kluczy, baz roboczych, logów z treścią wejść ani katalogu `.venv`. Syntetyczne dane i zanonimizowane wyniki testów można wersjonować.

## 4. Korzystanie z Luna do kodowania

W Codex wybierzcie **`gpt-6-luna`**, reasoning **`medium`** do ograniczonych zadań. Dla transakcji budżetu, kontroli dostępu i przeglądu zmian wybierzcie **`high`**. To ustawienia zespołu; model nie zastępuje testów ani przeglądu przez człowieka.

Każdy prompt do AI powinien zawierać:

```text
Przeczytaj AGENTS.md, CONTRIBUTING.md i docs/WSPOLNE_USTALENIA.md.
Wykonaj wyłącznie krok [A3/B4/...] z docs/PLAN_DWOCH_OSOB.md.
Moje pliki: [lista]. Wspólne kontrakty: [właściwa sekcja].
Warunek odbioru: [konkretny wynik].
Dodaj lub uruchom test zachowania, obejrzyj diff i opisz wynik.
Jeśli potrzebna jest zmiana wspólnego kontraktu, wskaż ją przed edycją.
```

Przed przyjęciem kodu właściciel musi umieć wyjaśnić: jakie dane przyjmuje funkcja, skąd bierze uprawnienia, jaki ma skutek i co dzieje się przy błędzie. Gdy tego nie rozumiesz, poproś AI o wyjaśnienie na jednym przykładzie i przeczytaj implementację.

Nie przekazujcie asystentom kluczy API. Klucze OpenAI i TypeSafe wpisuje właściciel kont lokalnie; do repo trafia wyłącznie `.env.example` z pustymi wartościami. Model w Codex i model wywoływany przez aplikację mają osobną konfigurację i dostęp. Wybór Luna w edytorze nie ustawia modelu backendu.

## 5. Zależności i środowisko

- Jeden Python 3.12 i jeden `uv.lock`. Maciek tworzy projekt, Paweł sprawdza go na swoim laptopie. Modele spaCy pobieramy w setupie i przypinamy ich wersje; aplikacja nie pobiera ich podczas obsługi żądania.
- Wersje pakietów są przypinane przy pierwszej instalacji i zapisywane w lockfile. Nie wpisujemy nieprzetestowanych wersji patch do planu.
- Po sklonowaniu używamy `uv sync --locked`. Zmiana zależności wymaga uzgodnienia i aktualizacji lockfile w tym samym commicie.
- Do zakończenia podstaw używamy wyłącznie stosu z dokumentacji. Dodatkowa biblioteka musi skracać konkretne zadanie.
- Ustawienia produktu są w polityce; sekrety i lokalne ścieżki w zmiennych środowiska. Progi nie mogą mieć osobnych kopii w UI i backendzie.

## 6. Kiedy zadanie jest gotowe

- Działa przez rzeczywisty punkt wejścia do aplikacji, jeśli dotyczy przepływu użytkownika.
- Ma sprawdzony przypadek dozwolony, blokowany i istotny błąd; redakcja także test braku danych w kolejnych etapach.
- Test sprawdza skutek: wywołanie konkretnego adaptera, zawartość przekazanych danych, rezerwację lub zapis audytu.
- Kontrola nie przyznaje dostępu po błędzie; testowy model nie pojawia się jako działająca semantyka.
- Zmiany polityki/API/schematu mają aktualną dokumentację. Kod i UI są po angielsku, instrukcje zespołu po polsku.
- Druga osoba potrafi uruchomić przykład i odczytać wynik.

Planowane komendy: `make check` — Ruff; `make test` — testy bez płatnych wywołań; `make test-live` — prawdziwe Jev i OpenAI; `make verify` — wszystkie powyższe. Brak klucza w `test-live`/`verify` oznacza brak pełnej weryfikacji i niezerowy kod wyjścia. Nie uruchamiajcie płatnych testów przy każdym zapisie.

Zmiana samej dokumentacji wymaga sprawdzenia linków, zgodności kontraktów i `git diff --check`; nie wymaga wywołań API.

## 7. Końcowe przekazanie

Trzy godziny przed potwierdzonym deadline zamrażamy funkcje. Maciek kończy opis, slajdy i zgłoszenie; Paweł sprawdza start na drugim laptopie, testy i nagranie. Oboje ćwiczymy demonstrację. Godzinę przed terminem wysyłamy pakiet, a następnie sprawdzamy zapis i dostęp do linków.
