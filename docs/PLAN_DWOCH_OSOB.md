# Plan pracy dwóch osób

**Cel:** działający ControlProof z kontrolą dostępu, redakcją, detektorem OpenAI Luna, limitami, zmienną polityką/feedem, audytem, panelem i testami. To lista pracy do wykonania, nie raport z gotowego produktu.

**Osoba 1:** gateway, dane, konfiguracja, audyt, panel i integracja. **Osoba 2:** OpenAI, semantyka, budżet, pomiary i scalanie testów. Zasady edycji plików: [CONTRIBUTING](../CONTRIBUTING.md). Wszystkie wspólne formaty: [ustalenia techniczne](WSPOLNE_USTALENIA.md).

## 0. Pierwsze 30 minut — razem

1. Przeczytajcie ten plan i sekcje 1–5 wspólnych ustaleń. Wpiszcie w zadaniach swoje imiona pod osobą 1 i 2.
2. Wyjaśnijcie sobie przepływ: użytkownik → gateway → kontrola → wykonawca → audyt. Gateway to nasz serwer decydujący, czy wolno wywołać narzędzie/model. Adapter to kod faktycznie wykonujący tę czynność.
3. Przejdźcie papierowo dwa przypadki: analityk czyta dokument A; ten sam analityk próbuje dokumentu B. Ustalcie, w którym miejscu drugi przypadek musi się zatrzymać.
4. Ustalcie repo/gałąź integracyjną. Każdy używa własnego klonu lub worktree. Osoba 1 tworzy szkielet i wspólne kontrakty, osoba 2 w tym czasie przygotowuje dostęp do API.
5. Osoba 1 ustala z organizatorem terminy i zapisuje odpowiedź w sekcji 11 wspólnych ustaleń. Osoba 2 sprawdza dostęp do wybranego modelu i wymaganą konfigurację konta; klucze pozostają lokalnie.

**Wynik:** wiecie, co budujecie, kto dotyka których plików i jakie są warunki odbioru. Szczegóły kontraktów z sekcji 4–5 są uzgodnione przed pierwszą integracją.

## 1. Osoba 1 — wykonuj w tej kolejności

### A1. Szkielet i wspólne formaty

**Zrozum:** żądanie HTTP, odpowiedź JSON, walidację Pydantic i różnicę między danymi od użytkownika a danymi ustalonymi przez serwer.

**Zrób:** utwórz projekt uv z Pythonem 3.12, zależnościami, lockfile i `.gitignore`. Dodaj `app/contracts.py`, schemat SQLite, `GET /health`, szkielety API i statyczny panel. Przygotuj `.env.example` bez sekretów. Z osobą 2 zamknij format `RequestContext`, `ControlResult`, `SemanticResult`, `Usage`, `Reservation`, `AuditEvent`.

**Gotowe, gdy:** osoba 2 uruchamia szkielet, otwiera `/health` i importuje te same kontrakty. Przekaż jej commit; od tego momentu możecie niezależnie pisać moduły.

### A2. Tożsamość, zadania i dokumenty

**Zrozum:** uwierzytelnienie mówi „kto pyta”, autoryzacja „co wolno tej osobie”. `role=admin` w JSON-ie nie nadaje uprawnień.

**Zrób:** trzy tożsamości demo, serwerowe mapowanie tokenów na role, tworzenie zadań przypisanych do użytkownika i klienta. Dodaj dwa syntetyczne dokumenty A/B oraz zaufany katalog ich właścicieli. Uprawnienia sprawdzaj przed odczytem treści. Adapter dokumentów ma licznik wykonania używany w testach.

**Gotowe, gdy:** poprawny odczyt A działa, B i cudze zadanie są blokowane przed adapterem. Brak tokenu i próba podmiany roli nie dają dostępu. Zapisz testy w `tests/gateway/`.

### A3. Audyt od pierwszej ścieżki

**Zrozum:** decyzja kontroli i wynik wykonania to różne informacje. `DENY` po odczycie dokumentu nie oznacza, że dokument nie został wcześniej odczytany.

**Zrób:** zapis zdarzeń do SQLite, identyfikatory operacji, etap kontroli, wersję polityki i liczniki adapterów. Rozdziel wywołania dokumentu, detektora i modelu podsumowującego. Dodaj odczyt historii dla właściciela zadania oraz eksport dla admina.

**Gotowe, gdy:** osoba 2 na podstawie audytu potrafi wskazać, co zostało wywołane i gdzie nastąpiła odmowa. Logi nie zawierają tokenów dostępowych ani surowych treści.

### A4. Polityka i redakcja danych

**Zrozum:** polityka to wersjonowany zestaw reguł; redakcja usuwa wskazane pola/wzorce przed przekazaniem danych dalej. Samo zamazanie danych w panelu ich nie zabezpiecza.

**Zrób:** walidację `config/policy.json`, listę modeli/narzędzi, zakresy ról i redakcję. Osobno ogranicz dane dopuszczone do OpenAI. Dodaj zmianę polityki przez admina; błędna aktualizacja pozostawia poprzednią wersję. Jedno żądanie używa jednej wersji.

**Gotowe, gdy:** analityk i reviewer widzą odpowiedni zakres A, żaden nie widzi B, a syntetyczny sekret nie występuje w danych przekazywanych do detektora, modelu, panelu ani eksportu. Testy sprawdzają wejścia adapterów.

### A5. Połączenie z modułami osoby 2

**Zrozum:** detektor także zużywa zasoby. Każda płatna próba potrzebuje rezerwacji przed wywołaniem; twardy zakaz dostępu kończy ścieżkę wcześniej.

**Zrób:** połącz B2–B4 z gatewayem zgodnie z kolejnością z sekcji 3 wspólnych ustaleń. Włącz prawdziwe podsumowanie przez Lunę i osobny detektor. Obsłuż odmowę, niepełną odpowiedź, timeout i brak budżetu. Nie przekazuj danych do OpenAI poza kontrolowanym adapterem.

**Gotowe, gdy:** wspólne demo pokazuje legalne podsumowanie, redakcję, semantyczną blokadę i limit. Przy niedostępnym detektorze nie uruchamia się model podsumowujący.

### A6. Feed i panel

**Zrozum:** feed dostarcza dane o blokadach. Panel pokazuje fakty z serwera i pozwala adminowi zmienić regułę.

**Zrób:** bezpieczne dopuszczanie artefaktów JSON, porównanie z manifestem i hashem w feedzie. Następnie jeden ekran: formularz żądania, stan kontroli, edycja polityki, historia, budżet, wynik testów i pobranie audytu. Odpytywanie co 2 sekundy wystarczy. Używaj `textContent` do treści z wejść/modelu.

**Gotowe, gdy:** dopisanie hasha do feedu blokuje wcześniej dozwolony artefakt; niepoprawny feed nie usuwa istniejących reguł. Nowe żądanie wpisane ręcznie działa przez ten sam backend co przyciski demo.

### A7. Oddanie produktu

**Zrozum:** slajdy muszą wyjaśniać działający mechanizm i pokazywać zmierzone wyniki.

**Zrób:** diagram, krótki przykład integracji klienta, opis, PDF do 10 slajdów i zgłoszenie. Wstaw wyniki od osoby 2 wraz z liczebnością, modelem i ograniczeniami. Usuń z materiałów deklaracje funkcji, których nie ukończyliście.

**Gotowe, gdy:** osoba 2 przechodzi demo z instrukcji; pakiet zapisany w formularzu ma działające linki, właściwy skład i załączniki.

## 2. Osoba 2 — wykonuj w tej kolejności

### B1. OpenAI Luna i próba integracji

**Zrozum:** aplikacja korzysta z własnego dostępu do OpenAI API. Model w Codex służy do pisania kodu; osobne wywołania backendu realizują detekcję i podsumowanie.

**Zrób:** przygotuj lokalnie klucz, uruchom SDK w środowisku uzgodnionym w A1. Sprawdź `gpt-6-luna`, Responses API, odpowiedź strukturalną oraz liczenie tokenów. Próby wykonuj tylko na syntetycznych danych, z małym limitem i wyłączonym automatycznym ponawianiem. Zapisz model, czas i `usage`, bez klucza i pełnych promptów.

**Gotowe, gdy:** model odpowiada i format da się sparsować. Jeśli model/konto nie działa, zgłoś blokadę od razu; nie przedstawiaj stubu jako rozwiązanej integracji. Do czasu integracji limitera dopuszczone są tylko ręczne próby uruchomieniowe o znanej liczbie i limicie tokenów.

### B2. Jeden adapter OpenAI i detektor

**Zrozum:** model ocenia niezaufany tekst, a kod stosuje regułę. Wynik `risk_score` nie jest pewnym ani skalibrowanym prawdopodobieństwem ataku.

**Zrób:** adapter `openai_luna.py`, osobne prompty detektora i podsumowania. Detektor zwraca ścisły `SemanticResult` z sekcji 4; nie ma narzędzi. Próg pochodzi z polityki. Timeout, odmowa modelu, brak wyniku i niezgodny format kończą kontrolę błędem, który blokuje dalszą płatną operację. Przygotuj testowy provider dla testów offline.

**Gotowe, gdy:** wynik detektora dla nowego tekstu pochodzi z prawdziwego modelu, a testy granicy progu i błędów są przewidywalne dzięki jawnemu stubowi. Przekaż osobie 1 interfejs i przykłady.

### B3. Atomowy budżet

**Zrozum:** „sprawdź saldo, potem odejmij” może dopuścić za dużo równoległych operacji. Rezerwacja i sprawdzenie limitu muszą być jedną transakcją. Timeout nie dowodzi, że dostawca nic nie policzył.

**Zrób:** trwałe rezerwacje SQLite dla zadania, użytkownika i całego demo; limity liczby żądań, wywołań dostawcy i równoległości. Zaimplementuj stany z sekcji 7. Pieniądze przechowuj jako liczby całkowite. Domknij test 20 równoległych prób przy budżecie wystarczającym na 5.

**Gotowe, gdy:** dokładnie 5 testowych wywołań wchodzi do wykonawcy, 15 dostaje odmowę i limit nie jest przekroczony. Restart nie zeruje rezerwacji. Nowy `request_id` lub zadanie nie usuwa nadrzędnego limitu użytkownika.

### B4. Koszt prawdziwej Luny

**Zrozum:** maksymalny koszt rezerwuje się przed generowaniem, a faktyczny koszt rozlicza po odpowiedzi. Do kosztu wchodzą także detektor i niewidoczne tokeny wyjścia.

**Zrób:** zweryfikowaną tabelę cen w polityce, liczenie pełnego wejścia i ograniczenie wyjścia. Podłącz B3 do wszystkich dróg wywołania adaptera, także liczenia tokenów w zakresie limitów zasobów. Rozlicz `usage`, błędy i niepewny koszt. Wspólnie z osobą 1 sprawdź całość przez API.

**Gotowe, gdy:** mały realny scenariusz pokazuje rezerwację i rozliczenie, a wyczerpany budżet zatrzymuje kolejną generację. Nie ma niejawnych ponowień SDK ani płatnej drogi omijającej limiter.

### B5. Testy całego produktu i ewaluacja detektora

**Zrozum:** test mechanizmu sprawdza kod na kontrolowanym wyniku modelu. Ewaluacja sprawdza, czy prawdziwy model poprawnie ocenia tekst. Te wyniki trzeba pokazać oddzielnie.

**Zrób:** scal testy osoby 1 i własne w `make test`; dodaj `make test-live` i `make verify`. Przygotuj co najmniej 12 próbek sprawdzających: 6 legalnych i 6 manipulacji, PL/EN, parafrazy oraz cytat o ataku. Przykłady do dobierania progu trzymaj oddzielnie. Dodaj niezależne testy braku PII, obejścia dostępu, feedu, zmian polityki, limitów i audytu.

**Gotowe, gdy:** każda obiecana kontrola ma dowód działania. Raport pokazuje fałszywe blokady i przeoczenia. Niedostępny model nie daje zielonego wyniku pełnej weryfikacji.

### B6. Pomiary i start na drugim laptopie

**Zrozum:** czas reguł, czas OpenAI i czas całego żądania są różnymi pomiarami. Wartości bez liczby prób nie pozwalają ocenić wyniku.

**Zrób:** pomiar na tych samych danych dla profilu laboratoryjnego, kontroli regułowych i pełnej hybrydy. Zapisz p50/p95, liczbę prób, błędy, koszt i wersję kodu. Zacznij od 100 prób offline i 12 live, jeśli mieszczą się w ustawionym budżecie. Uruchom projekt na drugim laptopie wyłącznie według README.

**Gotowe, gdy:** osoba 1 ma liczby do slajdów, wszystkie timeouty są ujęte w raporcie, a start nie wymaga nieopisanych poprawek. Przygotuj reset danych demo i zapasowe nagranie z opisem wersji.

## 3. Punkty wspólnej integracji

Godziny są orientacyjne i liczone od faktycznego, dozwolonego startu pracy. Ostatnie trzy godziny przed potwierdzonym terminem pozostają na oddanie.

| Kiedy | Osoba 1 | Osoba 2 | Razem sprawdzacie |
|---|---|---|---|
| H0–H1 | A1 | B1 | Wspólne środowisko i realny model |
| H1–H3 | A2–A3 | B2, początek B3 | Odczyt A, blokada B i audyt |
| H3–H6 | A4–A5 | B3–B4 | Redakcja, semantyka i atomowy limit |
| H6–H9 | A6 | B5 | Polityka/feed zmieniają wynik, panel pokazuje fakty |
| H9–H12 | Poprawki i początek A7 | B6 | Pełne demo, raport testów, drugi laptop |
| Ostatnie 3 h | A7 | Nagranie, test końcowy | Komplet materiałów i zapis zgłoszenia |

Jeżeli etap się spóźnia, usuwacie ozdobniki i dodatki. Jednorazowe zgody człowieka, MCP, drugi model, rozbudowany agent i funkcje KYC pozostają poza podstawowym planem. Nie zastępujcie wymaganej semantyki, limitu czy audytu atrapą; nieukończony element oznaczcie jako brak.

## 4. Wspólne demo do przećwiczenia

1. Legalny odczyt/podsumowanie A kończy się wynikiem; widać wykonanie.
2. Próba odczytu B zostaje zatrzymana przed adapterem dokumentów.
3. Syntetyczny sekret zostaje usunięty przed wyjściem do OpenAI.
4. Własny tekst jurora przechodzi prawdziwą kontrolę semantyczną; wynik i próg są widoczne.
5. Oddzielny test 20 żądań / 5 rezerwacji pokazuje rzeczywistą liczbę wykonanych operacji.
6. Admin zmienia regułę lub feed, a następne żądanie daje wynik zgodny z nową wersją.
7. Otwieracie raport testów i eksport audytu, pokazujecie jedno ograniczenie rozwiązania.

Każdy segment ma własne zadanie i przygotowany stan. Wyczerpany budżet z poprzedniego testu nie może udawać skutecznej blokady semantycznej.
