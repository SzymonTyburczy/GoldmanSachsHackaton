# Kontekst agenta — HackYeah 2026 / Goldman Sachs

Stan: 3 października 2026, Europe/Warsaw. Dokument powstał po przeczytaniu wszystkich pięciu merytorycznych plików wejściowych. `.DS_Store` jest metadanymi systemowymi. W chwili opracowania katalog zawierał wyłącznie materiały, bez implementacji. Ten plik i `PLAN_DZIALANIA.md` opisują rekomendację; nie są raportem z działającego produktu.

## Cel i sposób pracy

Pomóc zespołowi wygrać wyzwanie **AI Control Layer** Goldman Sachs. Optymalizować pod kryteria i dowody działania, nie liczbę funkcji. Być krytycznym: wskazywać luki, fałszywe założenia, obejścia i koszt zakresu. Nie obiecywać wygranej ani wyliczać jej prawdopodobieństwa bez danych o konkurencji.

Komunikacja z zespołem po polsku. Rekomendowany język UI, README i materiałów konkursowych: angielski. Stos i podział ludzi są roboczymi założeniami do potwierdzenia, nie decyzją użytkownika. Bieżące polecenia zespołu mają pierwszeństwo przed rekomendacją.

## Źródła i ich znaczenie

| Plik | Co z niego wynika | Jak go używać |
|---|---|---|
| `opis_tasku.pdf`, 4 strony | Pełne wymagania techniczne, deliverables, sposób oceny i wagi | Główna podstawa zakresu produktu |
| `terms.pdf`, 3 strony | Regulamin konkretnego konkursu, zgłoszenie, nagrody, prawa i inne wagi | Podstawa formalna; sprzeczności wyjaśnić z organizatorem |
| `rozmowa.txt` | Transkrypcja konsultacji z mentorem | Interpretacja potrzeb; nie zastępuje formalnego briefu |
| `GOLDMAN_SACHS_PROBLEMY_I_ROZWIAZANIA.md` | Research sprzed pełnego briefu, warianty ActionSeal i inne | Tło i pomysły, nie aktualna specyfikacja |
| `HACKYEAH_2026_RESEARCH.md` | Research wydarzenia i wielu kategorii | Pomocniczo; rekomendacja kilku projektów nie jest strategią tego zadania |

Starsze pliki zawierają odnośniki do nieobecnych plików na komputerze innej osoby. Nie twierdzić, że je przeczytano. Nie przenosić deklaracji z wcześniejszego researchu do pitchu jako samodzielnie zweryfikowanych faktów. Nie nadpisywać materiałów źródłowych.

## Wymagania potwierdzone w pełnym briefie

1. Działająca, lekka warstwa kontroli: gateway, proxy, middleware lub SDK wrapper. MCP jest przykładem, nie obowiązkowym protokołem.
2. Centralna konfiguracja: kontrole, progi, dozwolone modele, zasoby i budżety. Dołączyć opisany plik polityki.
3. Architektura hybrydowa: rzeczywiste kontrole deterministyczne **oraz** semantyczne AI. Sekcja formalna używa łagodniejszego sformułowania o AI, ale sekcja Challenge wymaga hybrydy; plan zakłada oba rodzaje.
4. Ochrona danych, dostępów i zasobów; uwzględnienie komercyjnych API i modeli lokalnych. Nie wystarczy wykres kosztów po wykonaniu.
5. Uwzględnienie historycznych exploitów i zewnętrznie zarządzanych sygnatur. Dostarczyć konkretną, ograniczoną demonstrację i testy.
6. Prosty interaktywny dashboard: kontrole, stan ochrony, blokady, zużycie/koszt. Raportowanie dla managementu oraz eksport audytu dla security.
7. Wykonywalny zestaw testów allowed, blocked i redacted, w tym budżety i ograniczanie exploitów.
8. Diagram architektury i łatwa integracja.

Jury ma uruchamiać testy, wpisywać własne prompty oraz zmieniać konfigurację i feedy. Może oceniać telemetrię wydajności. System musi działać dla nowych wejść, nie tylko przycisków demo.

Agent, aplikacja biznesowa i inne komponenty pomocnicze **nie podlegają ocenie** według sekcji 5 briefu. Można wykorzystać gotowe komponenty i biblioteki z uwzględnieniem licencji. Organizator nie zapewnia danych, sprzętu ani płatnych subskrypcji; brief wskazuje lokalne modele jako oczekiwany kierunek. Brak dowodu, że własne płatne API są zakazane — potwierdzić przed uzależnieniem od nich demo.

## Co powiedział mentor

- Klient produktu: dział IT / zespoły wdrażające agentów. Priorytet: bezpieczeństwo.
- Pokazać katalog kontroli i ich egzekwowanie; przykłady: authentication, access control, input validation, output filtering, resource management.
- Pokazać ten sam przepływ bez kontroli i po ich włączeniu; zmieniać użytkownika, próg i konfigurację.
- Wybrać jedną kontrolę do pogłębienia oraz kilka przykładowych.
- Liczą się mały narzut, łatwa integracja i możliwość dodania kontroli.
- Dynamiczny dostęp z udziałem człowieka został pozytywnie przyjęty, ale nie jest obowiązkowym wymaganiem ani gwarancją punktów.
- Wzmianka o „Jeffie” była hipotetyczna; mentor zaznaczył, że nie zna modelu. Nie zakładać dostępności, jakości ani konkretnego API tego narzędzia.
- W transkrypcji nazwy positive/negative są chwilami odwrócone. W testach: positive = dozwolone, negative = zatrzymane lub zredagowane, zgodnie z briefem.

## Punktacja i otwarte sprzeczności

| Kryterium | Brief, s. 4 | Regulamin, s. 2 |
|---|---:|---:|
| Robustness / guardrails | 30% | 30% |
| Architecture / performance | 20% | 20% |
| Security reporting | 20% | 20% |
| Self-testing suite | 15% | 20% |
| Implementability / scalability | 15% | 10% |

Nie rozstrzygać samodzielnie konfliktu. Pod obiema wersjami testy i raportowanie razem stanowią 35–40%, a jakość zabezpieczeń 30%. Ogólna punktacja innowacyjności/designu ze starego researchu nie jest punktacją tego wyzwania.

`terms.pdf`, pkt 5: dosłownie **3.10 godz. 11:00 PM → 4.10 godz. 11:00 PM**. Starszy research wskazuje **11:00 → 11:00** i rejestrację projektu do soboty 20:00. Nie uznawać PM za potwierdzoną literówkę. Potwierdzić start, deadline i checkpoint na miejscu oraz zapisać źródło odpowiedzi. Do planowania czasu zachować rezerwę na wcześniejszy deadline; to założenie operacyjne, nie ustalenie regulaminu. W tej analizie nie udało się odczytać aktualnego regulaminu online, więc konflikt pozostał otwarty.

`terms.pdf` dopuszcza PL/EN, starszy research podaje EN na karcie. Wybranie EN spełnia oba warianty. Pula 15 000 zł to **6 000 / 5 000 / 4 000 zł brutto**. Do 6 osób; tytuł, nazwa i skład zespołu, opis, PDF do 10 slajdów; zgłoszenie przez HackTribe. Dwa etapy: ocena zgłoszenia, potem prezentacje finalistów; skład oceniających może się różnić. Regulamin mówi o minimum 50% punktów w pierwszym etapie dla nagrody, zakazie zmian po terminie i braku przeniesienia autorskich praw majątkowych do nagrodzonego rozwiązania na sponsora. Nie traktować ostatniego zdania jako analizy wszystkich możliwych licencji z regulaminu ogólnego.

## Rekomendacja robocza

**ControlProof — AI Control Layer**: mały hybrydowy gateway, którego działanie można sprawdzić na żywo przez zmianę polityki, powtórzenie żądania i obejrzenie dowodu po stronie wykonawcy.

- Rdzeń: kontrola tożsamości i dostępu, redakcja danych, jeden realny detektor semantyczny, atomowe limity zasobów, wymienny feed blokad, audyt i testy.
- Pogłębiona kontrola: budżet i rezerwacje odporne na współbieżność; także koszt samego detektora.
- Scenariusz: agent analizuje syntetyczne dokumenty dwóch klientów. Różne role dostają różny zakres danych; próba wyjścia poza zakres zostaje zatrzymana.
- Wyróżnik prezentacji: zmiana polityki → nowe wyniki testów i metryk → rzeczywisty skutek. Sam symulator nie wystarcza.
- ActionSeal / jednorazowa zgoda człowieka jest P1 po zamknięciu P0, a nie całym produktem. Delegacja wielu agentów i pełny system KYC poza zakresem.
- Stos domyślny: Python/FastAPI, SQLite, prosty frontend w znanym zespołowi narzędziu, lokalny model. To propozycja; nie ma jeszcze wybranych wersji ani benchmarku sprzętu.

Dokładny zakres, kolejność, testy, harmonogram i demo: `PLAN_DZIALANIA.md`.

## Niezmienniki implementacji

1. Agent nie nadaje sobie roli, klienta, klasyfikacji danych ani prawa do zmiany polityki. Tożsamość i metadane są weryfikowane przez serwer.
2. `DENY` przed wykonaniem oznacza zero wywołań chronionego wykonawcy. Blokada wyjścia oznacza, że narzędzie mogło już działać; raportować te stany oddzielnie.
3. Dane są filtrowane przed przekazaniem do modelu i odbiorcy. Filtr na końcu odpowiedzi nie cofa ujawnienia danych modelowi.
4. Wrażliwe operacje bez poprawnej decyzji są zatrzymywane. Awaria modelu/konfiguracji nie daje automatycznego `ALLOW`.
5. Rezerwacja budżetu poprzedza kosztowną operację i jest atomowa. Timeout nie dowodzi zerowego kosztu; nie zwalniać automatycznie niepewnej rezerwacji.
6. Wynik semantyczny nie znosi twardego zakazu. Score nie jest skalibrowanym prawdopodobieństwem ataku.
7. Jedna wersja polityki na operację; walidacja i atomowa aktywacja zmian. Błędna zmiana zostawia ostatnią poprawną wersję; brak poprawnej konfiguracji przy starcie zatrzymuje ruch.
8. Agent nie ma kluczy backendu ani drogi poza gatewayem w deklarowanym zakresie. Zwykły wrapper w procesie nie izoluje złośliwego kodu mającego te same uprawnienia.
9. Logi, UI i raporty nie ujawniają surowych sekretów/PII. Admin ma oddzielne uprawnienia; wyłączenie kontroli do demonstracji jest ograniczone do syntetycznego środowiska.
10. Zapisuj decyzję, wersję polityki/feedu/modelu, powód, czas i wynik wykonania. Nie wymyślaj danych dla dashboardu.

## Jak pracować i kiedy uznać zadanie za domknięte

Przed kodowaniem przeczytać plan, sprawdzić aktualny stan repozytorium i odpowiedzi zespołu. Implementować pionowo: wejście → kontrola → realny adapter → audyt → test. Każda funkcja ma właściciela i warunek akceptacji. Nie dodawać frameworka, chmury ani drugiego protokołu bez korzyści dla demo lub kryteriów.

Testy mechanizmu mogą używać stubu modelu, lecz muszą być oznaczone. Osobny zestaw z prawdziwym detektorem ma wykazać semantykę i jej ograniczenia. Wyniki, liczebności i opóźnienia podawać dopiero po pomiarze. Niedostępny detektor nie może zmienić testu semantycznego na zielony.

Wymagane do domknięcia implementacji: powtarzalny start, działający przepływ i ochrona, edytowalna polityka, model semantyczny, limity, feed, testy, dashboard, eksport audytu, pomiary, instrukcja integracji i materiały zgłoszenia. Nie deklarować production-ready, pełnej zgodności regulacyjnej, odporności na wszystkie ataki ani ochrony całego rachunku chmurowego.

Przy braku czasu usuwać P1, drugi adapter, ozdobniki i biznesowe funkcje agenta. Nie usuwać prawdziwego enforcementu, semantyki, testów i raportowania, pozostawiając ich atrapy.
