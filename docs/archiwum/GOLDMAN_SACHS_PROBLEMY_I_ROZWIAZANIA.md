# Goldman Sachs: problemy, potrzeby i rozwiązania dla HackYeah 2026

**Research: 2 października 2026. Kontekst: zadanie „AI Control Layer”, HackYeah 3–4 października 2026.**

Dokument rozwija [wcześniejszy research](/Users/maciejklepacki/Documents/ChatGPT/HackYeah/HACKYEAH_2026_RESEARCH.md), szczególnie rozdział 8.1, oraz [plan zespołu](/Users/maciejklepacki/Documents/ChatGPT/HackYeah/HACKYEAH_2026_PLAN_JUTRO.md). Uwzględnia cztery osoby, trzy osoby techniczne, równoległe projekty i ograniczony czas. Nazwa firmy to **Goldman Sachs**.

**Najważniejszy wniosek: Goldman Sachs potrzebuje sposobu, żeby agenci AI mogli wykonywać pożyteczną pracę, a firma zachowała kontrolę nad danymi, uprawnieniami, kosztami i odpowiedzialnością za wynik.** Najbardziej obiecujący projekt dla was to mała, działająca warstwa kontroli na przykładzie przygotowania dokumentów nowego klienta.

W tekście rozróżniam:

- **Fakt:** informacja potwierdzona w publicznym źródle firmy, organizatora, regulatora albo dokumentacji technicznej.
- **Hipoteza potrzeby:** prawdopodobny problem operacyjny wywnioskowany z tych źródeł. Nie oznacza potwierdzonej luki w Goldman Sachs.
- **Propozycja:** mój pomysł na produkt, demonstrację lub pomiar. Nie jest wymaganiem partnera.

Scenariusze, klienci, adresy, kwoty i reguły w przykładach są **fikcyjne**. Nie opisują incydentu w Goldman Sachs. Nie mamy dostępu do wewnętrznej architektury banku, jego backlogu ani danych klientów.

## 1. Problem w bardzo prostych słowach

Wyobraź sobie nowego pracownika. Jest szybki, potrafi czytać dokumenty i obsługiwać programy. Czasem źle zrozumie polecenie. Czasem uwierzy komuś, kto udaje przełożonego.

Jeżeli może tylko przygotować szkic, pomyłkę zwykle da się poprawić. Jeżeli ma dostęp do dokumentów klientów, wysyłania wiadomości, zmiany danych i płatnych usług, ta sama pomyłka może wywołać rzeczywistą szkodę.

**Agent AI jest podobny do takiego pracownika: otrzymuje cel i sam wybiera kolejne czynności.** Na przykład ma przygotować pakiet dokumentów klienta. W tym celu wyszukuje pliki, odczytuje dane, tworzy podsumowanie, uzupełnia system i proponuje wysłanie wyniku.

Goldman Sachs chce korzystać z tej szybkości. Jednocześnie musi umieć odpowiedzieć:

1. Kto zlecił zadanie i jakie ma uprawnienia?
2. Do których dokumentów agent może zajrzeć?
3. Czy może tylko przygotować wynik, czy również go wysłać albo zmienić system?
4. Kto zatwierdził konkretną operację?
5. Czy zatwierdzona operacja nie została później zmieniona?
6. Ile agent może wydać i kiedy trzeba go zatrzymać?
7. Jak odtworzyć przebieg po błędzie?

Publiczna zapowiedź zadania wymienia ujawnienie danych, nieautoryzowane działania i nieprzewidywalne koszty oraz podkreśla zachowanie produktywności. [HackYeah: karta zadania][hack-task].

**Proste rozwiązanie:** pomiędzy agentem a narzędziami stawiamy kontrolera. Agent proponuje działanie, kontroler sprawdza reguły, a wykonawca realizuje wyłącznie dopuszczoną operację. Człowiek podejmuje decyzję tam, gdzie reguła wymaga jego zgody.

## 2. Czym zajmuje się Goldman Sachs i dlaczego to ma znaczenie

To globalna instytucja finansowa obsługująca między innymi firmy, instytucje, rządy i osoby prywatne. Dla projektu istotne są konkretne czynności, które wykonują jej pracownicy. [Goldman Sachs: działalność][gs-business].

| Obszar | Proste wyjaśnienie | Przykładowa praca, w której AI może pomagać — hipoteza zastosowania |
|---|---|---|
| Bankowość inwestycyjna | Pomoc firmom w pozyskaniu kapitału, przejęciach i innych dużych transakcjach | Czytanie dokumentów, porównywanie firm, przygotowanie materiałów |
| Rynki finansowe | Obsługa transakcji i ryzyka klientów na różnych rynkach | Analiza danych, przygotowanie scenariuszy, korzystanie z narzędzi analitycznych |
| Zarządzanie aktywami i majątkiem | Zarządzanie inwestycjami i finansami klientów | Raporty, wyszukiwanie informacji, przygotowanie materiałów dla doradcy |
| Bankowość transakcyjna | Usługi płatnicze i zarządzanie gotówką dla firm i instytucji | Sprawdzanie instrukcji, obsługa wyjątków, uzgadnianie danych |
| Funkcje wspierające | Technologia, operacje i kontrola umożliwiające działanie organizacji | Integracje, kontrola dostępu, dokumentacja, raportowanie, obsługa dostawców |

W takim środowisku **poprawny tekst to za mało**. Liczą się również właściwy klient, aktualne dane, dopuszczony odbiorca, odpowiedni zakres dostępu i dowód wykonania. To wniosek projektowy z charakteru pracy, a nie opis konkretnej awarii firmy.

Warszawa ma znaczenie techniczne: Goldman Sachs opisuje tam własny hub inżynieryjny i organizację hackathonów. W publicznym materiale o edycji z listopada 2025 wyróżnia ścieżki Software Engineering i Quantitative Strats. To sugeruje, że warto przygotować demonstrację z mechanizmem, który da się sprawdzić, i sensownym uzasadnieniem biznesowym. [Goldman Sachs: Warsaw Hackathon, publikacja 23.12.2025][gs-warsaw].

## 3. Co publiczne źródła mówią o ich realnym kierunku

### 3.1. AI ma zmieniać całe procesy

**Fakt:** w liście do akcjonariuszy opublikowanym 20 marca 2026 Goldman Sachs przedstawia **One Goldman Sachs 3.0**, ogłoszony w 2025, jako nowy model operacyjny wspierany przez AI. Wskazuje szybkość, sprawność działania oraz terminowe, poprawne i kompletne dane. Wymienia sześć początkowych obszarów:

1. Onboarding klientów / KYC.
2. Zarządzanie dostawcami.
3. Raportowanie regulacyjne.
4. Kredyty.
5. Zarządzanie ryzykiem przedsiębiorstwa.
6. Wsparcie sprzedaży.

To deklaracja kierunku i prac, a nie dowód, że wszystkie te procesy już działają autonomicznie. [Goldman Sachs: Annual Report 2025, list do akcjonariuszy][gs-letter].

**Wniosek dla was:** wybrać jeden z tych procesów jako kontekst. Dzięki temu kontrola agentów ma użytkownika i cel. „Bezpieczny onboarding” jest łatwiejszy do uzasadnienia niż ogólna obietnica zabezpieczenia wszystkich agentów świata.

### 3.2. Firma już ma narzędzia AI

**Fakt:** w podcaście z 4 lutego 2025 Goldman Sachs opisuje uruchomienie **GS AI Assistant**, który daje pracownikom dostęp do modeli w sposób uwzględniający bezpieczeństwo i wymagania instytucji regulowanej. Źródło nie pozwala ustalić jego dzisiejszej architektury ani uprawnień. [Goldman Sachs: AI Exchanges][gs-assistant].

**Wniosek:** projekt powinien wnosić konkretną kontrolę lub dowód działania. Sama możliwość rozmowy z modelem będzie słabym wyróżnikiem.

### 3.3. Firma sama opisuje ryzyka AI

**Fakt:** Form 10-K za 2025 wskazuje możliwość błędnych wyników i działań AI, ujawnienia poufnych informacji, uprzedzeń oraz trudności wyjaśniania rezultatów. Opisuje także zależność od modeli i podmiotów trzecich. Raport wymienia **Firmwide Artificial Intelligence Risk and Controls Committee**, podlegający komitetowi ryzyka technologicznego. To potwierdza istnienie nadzoru, nie skuteczność każdego zabezpieczenia. [Goldman Sachs: Form 10-K, Risk Factors i Risk Management][gs-10k].

**Wniosek:** trafny język rozmowy z partnerem to „ułatwiamy egzekwowanie waszych reguł w konkretnym przepływie”. Nie ma podstaw, żeby przedstawiać Goldman Sachs jako organizację bez kontroli AI.

### 3.4. Szczególnie ważne jest działanie w czyimś imieniu

**Fakt:** w publikacji z 24 sierpnia 2026 Chris Churchman, kierujący Marquee i współprzewodniczący grupy AI w Global Banking & Markets, omawia wiarygodność wyników, powiązanie ze źródłami, bezpieczne środowisko agentów i zakres ich upoważnienia. W rozmowie pojawia się pojęcie **mandate engineering**: określenie, co AI może zrobić i z czyjego upoważnienia. Rozmowę nagrano 11 sierpnia. [Goldman Sachs: Building AI Systems for Capital Markets][gs-capital-ai].

**Wniosek:** uprawnienie powinno obejmować konkretny cel i działanie. Samo „agent ma dostęp do programu pocztowego” nie określa, jakie dane może wysłać ani komu.

### 3.5. Automatyzacja rośnie również poza firmą

**Fakt:** analiza Goldman Sachs Research z 18 września 2026 opisuje przejście od eksperymentów do wdrażania AI oraz rozwój agentów konsumenckich. Jest to analiza rynku, nie specyfikacja wewnętrznego systemu Goldman Sachs. [Goldman Sachs: Consumer Agents][gs-consumer].

**Fakt rynkowy:** Anthropic udostępnił 5 maja 2026 szablony agentów dla finansów, w tym pracy nad materiałami, KYC i zamknięciem ksiąg. Oddzielny komunikat z 4 maja dotyczy nowej firmy usług AI z udziałem między innymi Goldman Sachs. Żaden z tych komunikatów sam w sobie nie dowodzi produkcyjnego użycia konkretnych agentów w banku. [Anthropic: agenci dla finansów][anthropic-finance], [Anthropic: firma usług AI][anthropic-services].

**Wniosek:** przewagę warto budować na poprawnym przebiegu i kontroli operacji, bo gotowe komponenty do wykonywania pracy już istnieją.

## 4. Co dokładnie wiadomo o zadaniu HackYeah

**Kartę sprawdzono ponownie w działającej przeglądarce 2 października 2026.** Jest zgodna z [lokalnym snapshotem](/Users/maciejklepacki/Documents/ChatGPT/HackYeah/zrodla/Publiczne_tresci_strony_2026.json).

| Potwierdzone na karcie | Znaczenie |
|---|---|
| Nazwa: AI Control Layer | Projekt powinien pokazać kontrolę działania agentów |
| Pula: 15 000 PLN | To pula zadania; karta nie ustala jej podziału |
| Zgłoszenia po angielsku | Opis, slajdy i demonstrację przygotować w EN |
| Ujawnienie wrażliwych danych | Trzeba kontrolować dostęp i przekazywanie danych |
| Nieautoryzowane działania | Trzeba odróżnić propozycję od prawa do wykonania |
| Nieprzewidywalne koszty | Trzeba ograniczać wykorzystanie zasobów |
| Zachowanie produktywności | Dopuszczone działania powinny przechodzić sprawnie |

Źródło: [HackYeah: Tasks & Prizes][hack-task].

**Na karcie nie było odnośnika do osobnego regulaminu ani pełnej specyfikacji zadania.** Nie potwierdzono obowiązkowego SDK, modelu, protokołu, zestawu danych, punktacji partnera ani konkretnego workflow. KYC, eksport dokumentów i jednorazowe zgody poniżej są propozycjami do skonfrontowania z pełnym briefem.

## 5. Sześć obszarów biznesowych: czego mogą konkretnie potrzebować

Poniższe obszary pochodzą z listu do akcjonariuszy; **problemy, użytkownicy i proponowane produkty w tabeli są hipotezami**. Nie znamy obecnych narzędzi ani czasu obsługi tych procesów w Goldman Sachs.

| Obszar | Problem po ludzku | Potencjalny użytkownik | Konkretna potrzeba / rezultat | Gdzie przydaje się AI Control Layer |
|---|---|---|---|---|
| Onboarding / KYC | Trzeba ustalić, kim jest klient, zebrać dokumenty i rozstrzygnąć braki | Analityk onboardingowy, compliance | Pakiet z dokumentami, brakami, źródłami i statusem przeglądu | Dostęp tylko do danego klienta; kontrola eksportu; zatwierdzenie zmian statusu |
| Dostawcy | Informacje o usłudze, umowie, dostępie i ryzyku są w różnych miejscach | Zakupy, vendor risk, security | Karta dostawcy i lista kwestii wymagających decyzji | Agent może analizować, lecz nie przyznać dostępu ani sam zawrzeć zobowiązania |
| Raportowanie | Trzeba uzgodnić dane i umieć wykazać, skąd pochodzą liczby | Finance, regulatory reporting | Roboczy raport z pochodzeniem wartości i listą wyjątków | Kontrola danych wejściowych, wersji i zatwierdzenia wysyłki |
| Kredyty | Dokumenty i parametry wymagają sprawdzenia przed decyzją | Lending operations, analityk | Zestawienie warunków, braków i rozbieżności | Przygotowanie materiału oddzielone od przyznania finansowania |
| Ryzyko | Trzeba wychwycić przekroczenia i ustalić, kto reaguje | Risk, właściciel procesu | Wyjątek z kontekstem, właścicielem i śladem obsługi | Limity działania agenta, eskalacja, zatrzymanie i rejestr decyzji |
| Sprzedaż | Pracownik musi szybko zebrać aktualne materiały dla właściwego klienta | Relationship manager, zespół sprzedaży | Dopuszczony zestaw materiałów i szkic komunikacji | Dobór odbiorcy, kontrola udostępnienia danych i zatwierdzenie wysyłki |

**Najbardziej przydatne przekrojowe potrzeby:** dostęp do właściwych danych, mniejsza liczba ręcznych przepisań, widoczne wyjątki, kontrola działań i jasna odpowiedzialność. AI może przyspieszyć część pracy, ale wynik powinien dać się sprawdzić przed użyciem.

## 6. Dwanaście problemów, które warto rozumieć

To **analiza zagrożeń i hipotez potrzeb**, oparta na kierunku zadania, ujawnieniach firmy i źródłach technicznych. Nie jest listą potwierdzonych podatności Goldman Sachs. Kontrole poniżej są propozycjami projektowymi.

### 6.1. Agent przeczyta dokument innego klienta

**Prosto:** pracownik ma zbadać firmę A, ale system pozwala mu zajrzeć do teczki firmy B.

**Przykład:** agent wyszukuje „strukturę właścicielską” w całym repozytorium i dostaje dokument należący do innego klienta.

**Potrzeba:** sprawdzanie uprawnień użytkownika i zakresu zadania przed odczytem, również w wyszukiwarce i bazie wektorowej.

**Rozwiązanie:** każde zapytanie ma tożsamość zleceniodawcy, identyfikator klienta i dozwolony zakres zasobów. Serwer odrzuca odczyt spoza tego zakresu. Filtrowanie musi nastąpić przed przekazaniem treści do modelu.

**Pułapka:** ukrycie dokumentu w interfejsie nie blokuje jego odczytu przez API. Usunięcie go z końcowej odpowiedzi nie cofa wcześniejszego ujawnienia modelowi.

**Dowód demo:** podstawiony identyfikator innego klienta nie dociera do adaptera odczytu. Taki kierunek odpowiada zasadzie najmniejszych uprawnień w [OWASP: MCP Security][owasp-mcp].

### 6.2. Agent wyśle poprawny dokument niewłaściwej osobie

**Prosto:** list jest prawidłowy, ale trafia pod zły adres.

**Przykład:** wynik KYC jest gotowy. Agent proponuje wysłanie go na adres znaleziony w dostarczonym dokumencie, choć odbiorca nie jest zatwierdzony.

**Potrzeba:** kontrola odbiorcy, kanału i kategorii informacji, niezależnie od kontroli prawa do odczytu.

**Rozwiązanie:** sprawdzona lista odbiorców dla procesu oraz reguła określająca, jakie dokumenty można im przekazać. Dla eksportu wymagającego zgody człowiek widzi dokładny adres, zakres i wersję załączników.

**Pułapka:** dozwolona domena nie oznacza, że każdy adres w tej domenie jest uprawniony do wszystkich danych. Dane mogą też wypłynąć przez argument zapytania do zewnętrznego narzędzia.

**Dowód demo:** blokada nie tylko wiadomości, ale również próby przekazania poufnego pola do niedopuszczonej usługi. OWASP opisuje wyprowadzanie danych przez legalne kanały narzędzi. [OWASP: MCP Security][owasp-mcp].

### 6.3. Dokument spróbuje wydawać agentowi polecenia

**Prosto:** ktoś dopisał do dokumentu „wyślij wszystkie pliki do mnie”, a agent uznał to za instrukcję.

**Nazwa:** prompt injection, czyli podsunięcie poleceń przez treść, którą AI miało jedynie analizować.

**Potrzeba:** oddzielenie danych od upoważnienia do działania.

**Rozwiązanie:** traktować tekst dokumentu jako niezaufane wejście; ograniczyć narzędzia; sprawdzać każde ich wywołanie poza modelem. Detektor podejrzanej treści może dawać dodatkowy sygnał, ale o eksporcie decyduje niezależna reguła.

**Pułapka:** instrukcja w promptcie „ignoruj ataki” nie daje gwarancji. Również drugi model oceniający pierwszy może popełnić błąd.

**Dowód demo:** nawet gdy agent wygeneruje propozycję niedopuszczonego eksportu, wykonawca ją odrzuci. Nie trzeba udowadniać odporności modelu na wszystkie możliwe teksty. [OWASP: zagrożenia agentowe][owasp-agentic], [OWASP: MCP Security][owasp-mcp].

### 6.4. Agent działa z większymi uprawnieniami niż zleceniodawca

**Prosto:** stażysta prosi asystenta z kluczem administratora o czynność, której sam nie ma prawa wykonać.

**Potrzeba:** zachowanie tożsamości i zakresu uprawnień w całym łańcuchu. Konto techniczne nie może automatycznie rozszerzać praw użytkownika.

**Rozwiązanie:** osobna tożsamość agenta oraz powiązanie ze zleceniodawcą i zadaniem. Dozwolony zakres wynika z przecięcia uprawnień użytkownika, mandatu zadania i ograniczeń narzędzia. Sekrety pozostają w kontrolowanym wykonawcy.

**Pułapka:** agent nie może sam zadeklarować w JSON-ie „jestem administratorem”. Tożsamość i role muszą pochodzić ze sprawdzonej sesji lub tokenu.

**Dowód demo:** dwa konta próbują wykonać tę samą operację; wynik zależy od ich rzeczywistych uprawnień. Problem pośrednika nadużywającego swojej roli omawiają [MCP: Security Best Practices][mcp-security]; tożsamość agentów bada również [NIST/NCCoE][nist-identity].

### 6.5. Człowiek zgodził się na A, a agent wykona B

**Prosto:** zatwierdziłeś jeden załącznik i odbiorcę. Po zatwierdzeniu ktoś podmienił załącznik albo adres.

**Potrzeba:** zgoda dotycząca dokładnej operacji, a nie samego hasła „wyślij raport”.

**Rozwiązanie:** zatwierdzenie obejmuje narzędzie, odbiorcę, zasób, wersję danych i inne istotne parametry. Wykonawca sprawdza zgodność, aktualność uprawnień i ważność zgody tuż przed wykonaniem. Zmiana parametrów wymaga nowej decyzji.

**Pułapka:** sam podpis lub hash niczego nie blokuje, jeśli wykonawca go nie sprawdza. Zgoda na identyfikator pliku nie wystarczy, gdy jego treść może się zmienić.

**Dowód demo:** po zatwierdzeniu podmieniamy odbiorcę albo wersję pliku. Żadna z tych operacji nie dochodzi do wysyłki. To proponowany rdzeń **ActionSeal**.

### 6.6. Ta sama operacja wykona się dwa razy

**Prosto:** system ponowił próbę i wysłał pakiet drugi raz, chociaż pierwsza próba się udała.

**Potrzeba:** rozróżnianie ponowienia od nowej operacji oraz bezpieczna obsługa niepewnego wyniku.

**Rozwiązanie:** identyfikator operacji, atomowe zużycie zgody i klucz idempotencji w systemie docelowym, jeśli go obsługuje. Po timeoutcie sprawdzić status, zanim ponowi się działanie.

**Pułapka:** blokada ponownego użycia tokenu nie daje sama z siebie wykonania „dokładnie raz” w zewnętrznym systemie. Operacja może się udać, a odpowiedź zginąć. Potrzebne są stan wykonania i uzgodnienie statusu.

**Dowód demo:** równoczesne użycie tej samej zgody nie powoduje dwóch wywołań wykonawcy; timeout ma jawny stan „wynik do ustalenia”.

### 6.7. Agent zapętli się i zużyje budżet

**Prosto:** jedna analiza staje się setką płatnych prób, bo AI stale poprawia wynik albo uruchamia podagentów.

**Potrzeba:** limit zadania, liczby kroków, czasu i równoległości, kontrolowany przed kolejnym wywołaniem.

**Rozwiązanie:** rezerwowanie maksymalnego dopuszczonego kosztu przed wywołaniem i rozliczenie po nim. Wspólny licznik dla wszystkich podagentów, limit prób i sygnał zatrzymania. Gdy koszt nie ma znanej górnej granicy, zastosować twarde limity zasobów i jasno określić zakres gwarancji.

**Pułapka:** licznik aktualizowany po fakcie przegrywa z równoległymi wywołaniami. Alert rozliczeniowy może przyjść z opóźnieniem — dokumentacja AWS Budgets wprost o tym uprzedza. [AWS: zarządzanie budżetami][aws-budgets].

**Dowód demo:** 20 równoległych żądań; dopuszczone mieszczą się w rezerwacjach, pozostałe są blokowane przed płatnym narzędziem. To dobry zakres dla **AgentSpend**.

### 6.8. Nie wiadomo, dlaczego coś się stało

**Prosto:** widzisz wysłany dokument, ale nie wiesz, kto to zlecił, co zatwierdził i która reguła na to pozwoliła.

**Potrzeba:** odtworzenie łańcucha zlecenie → propozycja → kontrola → zgoda → wykonanie → rezultat.

**Rozwiązanie:** identyfikatory zleceniodawcy, agenta, zadania i operacji; wersja polityki; wynik sprawdzenia; zatwierdzający; identyfikatory i wersje źródeł; potwierdzenie albo błąd wykonania. Dostęp do rejestru również podlega kontroli.

**Pułapka:** przechowywanie całych promptów i dokumentów tworzy kolejne miejsce z poufnymi danymi. Zapisać minimalny potrzebny dowód, a treść przechowywać osobno zgodnie z zasadami organizacji. Nie trzeba ujawniać ukrytego toku rozumowania modelu.

**Dowód demo:** osoba spoza zespołu odtwarza zdarzenie z rejestru. FINRA wskazuje audytowalność i śledzenie działań agentów jako istotne kwestie nadzoru. [FINRA: GenAI, raport 2026][finra-ai].

### 6.9. Podagent rozszerzy zakres pracy

**Prosto:** asystent, który miał prawo czytać dokumenty, przekazał pomocnikowi prawo ich wysyłania.

**Potrzeba:** uprawnienia i budżet, które nie rosną podczas delegacji.

**Rozwiązanie:** dziecko dostaje podzbiór uprawnień rodzica i zadania. Wspólny identyfikator zadania, ograniczony czas życia, wspólny budżet i możliwość odwołania całego łańcucha.

**Pułapka:** kontrola tylko pierwszego agenta nie obejmuje późniejszych wywołań jego pomocników. Oddzielne limity podagentów mogą sumarycznie przekroczyć limit zadania.

**Dowód demo:** podagent może wyciągnąć pola z dokumentu, lecz nie dostaje funkcji eksportu. To ambitniejszy wariant **DelegationFirewall**; na hackathonie ograniczyć go do dwóch–trzech agentów.

### 6.10. Wszystko wymaga kliknięcia „zatwierdź”

**Prosto:** zabezpieczenie pyta tak często, że pracownik zaczyna zatwierdzać mechanicznie.

**Potrzeba:** kontrola proporcjonalna do operacji i czytelna informacja w momencie decyzji.

**Rozwiązanie:** bezpieczne odczyty w dozwolonym zakresie przechodzą automatycznie; określone działania wymagają zgody; zakazane są blokowane. Interfejs pokazuje dokładne parametry, zmianę względem poprzedniej propozycji i powód wymagania zgody.

**Pułapka:** liczba kliknięć nie jest miarą bezpieczeństwa. „Zatwierdź całe zadanie” może ukrywać wiele bardzo różnych operacji.

**Dowód demo:** kilkanaście legalnych odczytów bez przerwania pracy i jedno precyzyjne zatwierdzenie eksportu. Mierzyć również niepotrzebne blokady.

### 6.11. AI podejmie działanie na podstawie błędnych danych

**Prosto:** podsumowanie wygląda wiarygodnie, ale zawiera zmyślony fakt lub starą wartość.

**Potrzeba:** wskazanie źródła, wersji, czasu danych i rzeczy nierozstrzygniętych; sprawdzanie faktów ważnych dla danej operacji.

**Rozwiązanie:** ekstrakcja pól ze wskazaniem fragmentu dokumentu, walidacja formatów i obliczeń, jawne konflikty oraz braki. W krytycznych miejscach wynik trafia do specjalisty. Zgoda na wysyłkę jest osobna od weryfikacji treści.

**Pułapka:** lista linków nie dowodzi, że każdy fakt ma oparcie w źródle. Autoryzowana operacja może nadal przekazać błędną analizę. Goldman Sachs omawia ten problem w kontekście Marquee. [Goldman Sachs: AI dla rynków kapitałowych][gs-capital-ai].

**Dowód demo:** brak numeru rejestracyjnego pozostaje brakiem; dwa sprzeczne dokumenty powodują flagę konfliktu, a nie pewną odpowiedź.

### 6.12. Kontrolę można obejść albo wyłączyć awarią

**Prosto:** agent zna alternatywną drogę do narzędzia; albo kontroler przestał działać i system przepuszcza wszystko.

**Potrzeba:** wszystkie chronione działania przechodzą przez punkt kontroli; awaria ma zdefiniowane zachowanie.

**Rozwiązanie:** wykonawca przechowuje sekrety, agent nie ma bezpośredniego dostępu do chronionych API, a sieć i narzędzia ograniczają obejścia. Dla wrażliwego zapisu brak decyzji oznacza zatrzymanie. Odwołanie uprawnień sprawdzane jest przed kolejną operacją.

**Pułapka:** dodatkowy gateway nie jest skuteczny, gdy agent nadal ma klucz do systemu docelowego. „Kill switch” nie cofa już wysłanej wiadomości ani rozpoczętej transakcji.

**Dowód demo:** próba bezpośredniego wywołania i awaria silnika reguł nie uruchamiają chronionego narzędzia. Punkt kontroli przed dostępem do narzędzia istnieje też w [AWS AgentCore Policy][aws-agentcore]; własne demo musi pokazać, gdzie dokładnie egzekwuje decyzję.

## 7. Szersze problemy firmy: gdzie kontrola AI pomaga, a gdzie jej nie wystarczy

Goldman Sachs musi także zarządzać ryzykiem rynku i kontrahentów, wymaganiami różnych jurysdykcji, konkurencją, ciągłością działania i zasobami ludzkimi. Te obszary są opisane w raporcie rocznym. [Goldman Sachs: Form 10-K][gs-10k]. Poniższe przełożenie na produkty jest **analizą**, nie potwierdzonym zamówieniem.

| Problem biznesowy | Wyjaśnienie po ludzku | Co mogłoby pomóc | Rola warstwy kontroli AI |
|---|---|---|---|
| Skalowanie operacji | Więcej pracy wymaga większej zdolności obsługi | Automatyzacja dobrze określonych kroków i obsługa wyjątków | Pozwala dopuścić więcej działań bez ręcznego przeglądania każdego kroku |
| Jakość danych | Dwa systemy mogą podawać różne informacje | Uzgadnianie wartości, źródła, wersje i właściciel rozbieżności | Zatrzymuje wybrane operacje, dopóki rozbieżność nie zostanie rozstrzygnięta |
| Rosnący zakres integracji | Każde nowe narzędzie to nowe dane, uprawnienia i zależności | Rejestr narzędzi, zatwierdzone adaptery i testy integracyjne | Sprawdza, czy agent korzysta z dopuszczonego narzędzia i wersji |
| Produktywność specjalistów | Kontrole i ręczne czynności zajmują czas | Wspomaganie pracy i dobrze zaprojektowane eskalacje | Automatyzuje oczywiste decyzje, pokazuje człowiekowi konkretne wyjątki |
| Zaufanie klienta | Klient oczekuje poprawnej i poufnej obsługi | Spójne dane, kontrola udostępniania i wyjaśnialny przebieg | Daje dowód zakresu i zatwierdzenia operacji |
| Ryzyko rynkowe i kredytowe | Zmiana rynku lub niewypłacalność może spowodować straty | Odpowiednie modele, limity, scenariusze i decyzje specjalistów | Kontroluje użycie narzędzi; sama nie ocenia poprawnie całego ryzyka inwestycji |

**Dobra obietnica projektu:** skrócić konkretną pracę i zachować ustalone granice działania. Realizacja strategii rynkowej, zastąpienie całego compliance czy rozwiązanie ryzyka kredytowego wymaga znacznie szerszego produktu i walidacji.

## 8. Co regulacje i standardy rzeczywiście wnoszą do researchu

| Źródło | Co potwierdza | Praktyczne znaczenie dla projektu | Granica |
|---|---|---|---|
| FINRA, raport nadzorczy 2026 | Zasady nadzoru i prowadzenia działalności nadal dotyczą użycia GenAI; opisano ryzyka autonomii, zakresu, audytowalności i danych | Pokazać zakres upoważnienia, rejestr operacji i miejsca ludzkiej decyzji | Raport nie stanowi certyfikacji produktu ani osobnego uniwersalnego prawa o agentach |
| EBA / DORA | Od 17.01.2025 stosowane są wymagania dotyczące odporności cyfrowej, ryzyka ICT i zależności od dostawców dla podmiotów w zakresie regulacji | Uczciwie opisać awarie, dostawców i granice infrastruktury | Obowiązki zależą od konkretnego podmiotu i usługi; sam gateway ich nie realizuje w całości |
| NIST, inicjatywa agentowa 17.02.2026 | Trwają prace nad interoperacyjnością, bezpieczeństwem i tożsamością agentów | Oprzeć projekt na jawnych tożsamościach i sprawdzalnym upoważnieniu | Inicjatywa nie oznacza gotowego obowiązkowego standardu ani zatwierdzenia prototypu |
| OWASP | Zagrożenia agentów i MCP obejmują nadużycia narzędzi, uprawnień, treści i integracji | Wybrać konkretne scenariusze zagrożeń do sprawdzenia | Lista zagrożeń nie dowodzi odporności konkretnego rozwiązania |
| Fed/OCC/FDIC, SR 26-2 z 17.04.2026 | Nowe wytyczne zastępują SR 11-7; **generatywne i agentowe AI są poza zakresem tych wytycznych** | Nie opierać pitchu na twierdzeniu, że SR 11-7 nadal bezpośrednio reguluje wszystkie LLM-y | Wyłączenie z tych wytycznych nie zwalnia z innych obowiązków i kontroli organizacji |

Źródła: [FINRA][finra-ai], [EBA][eba-dora], [NIST][nist-agents], [OWASP][owasp-agentic], [SR 26-2][fed-letter] i [załącznik, przypis 3 na stronie 3][fed-guidance].

Praktyczny wniosek: juror powinien zobaczyć **dowód kontrolowanego działania**, a nie dekoracyjne logotypy regulacji. W prototypie można pokazać mechanizm pomagający organizacji stosować jej zasady; nie należy deklarować pełnej zgodności bankowej na podstawie krótkiego demo.

## 9. Co już istnieje i czym wasz projekt może się wyróżnić

**Sama koncepcja kontroli przed wywołaniem narzędzia już istnieje.** Źródła poniżej opisują dostępne komponenty i podejścia. Nie potwierdzają, że Goldman Sachs używa ich wszystkich.

| Rozwiązanie / podejście | Co daje według źródła lub swojej podstawowej roli | Co trzeba sprawdzić w waszym scenariuszu | Potencjalna rola w projekcie |
|---|---|---|---|
| Open Policy Agent | Ocena reguł dostępu, między innymi dla HTTP API | Czy aplikacja faktycznie egzekwuje odpowiedź i dostarcza zaufane dane do oceny | Silnik reguł zamiast budowy własnego języka |
| Cedar / AWS AgentCore Policy | Reguły autoryzacji poza agentem, sprawdzane przed dostępem do narzędzi przez Gateway | Dokładny zakres gatewaya, integracja tożsamości i obsługa waszej zgody na konkretny dokument | Punkt odniesienia i możliwy komponent |
| NVIDIA NeMo Guardrails | Mechanizmy kontrolowania przebiegu i treści aplikacji LLM | Które kontrole są regułowe, które korzystają z modeli, i gdzie następuje wykonanie | Dodatkowa warstwa dla treści i dialogu |
| MCP i jego mechanizmy autoryzacji | Standard komunikacji z narzędziami i zasady bezpiecznej integracji | Poprawna walidacja tokenów, zakresy, odbiorcy tokenów i prawa systemów docelowych | Opcjonalny adapter narzędzi; protokół nie zastępuje reguł biznesowych |
| Monitoring kosztów, np. AWS Budgets | Śledzenie kosztów i powiadomienia; dokumentacja opisuje opóźnienia danych i alertów | Czy limit jest egzekwowany przed zużyciem zasobu, czy tylko obserwowany po nim | Rozliczanie i obserwacja obok kontroli przed wywołaniem |
| IAM, role i konta techniczne | Identyfikacja i ograniczenie dostępu do infrastruktury i usług | Czy uprawnienia są zawężone również do konkretnego zadania, klienta i parametrów | Podstawa kontroli tożsamości, którą trzeba zachować |
| Logi i tracing | Zapis zdarzeń, błędów i czasów działania | Czy łączą zlecenie, zgodę i faktyczny efekt; czy nie ujawniają nadmiaru danych | Dowód przebiegu i pomiar efektu |

Źródła technologii: [OPA: HTTP API authorization][opa], [AWS AgentCore Policy][aws-agentcore], [AWS: pojęcia Policy i Cedar][aws-concepts], [NVIDIA NeMo Guardrails][nemo], [MCP Security Best Practices][mcp-security], [AWS Budgets][aws-budgets]. Ostatnie dwa wiersze to ogólne role komponentów, a nie recenzja konkretnego produktu.

### Wiarygodny wyróżnik

Możecie wyróżnić się połączeniem czterech rzeczy w jednym małym przepływie:

1. **Konkretny proces:** przygotowanie pakietu nowego klienta.
2. **Precyzyjna zgoda:** widoczny odbiorca i dokładna wersja danych.
3. **Egzekwowanie:** podmiana parametrów i ponowne użycie zgody nie uruchamiają wykonawcy.
4. **Dowód:** przechodzą poprawne przypadki, blokowane są wybrane nadużycia, a rejestr pozwala sprawdzić wynik.

Nie twierdzić, że nikt wcześniej nie rozwiązywał autoryzacji agentów. Pokazać, że wasz projekt dobrze rozwiązuje określony problem i jest prosty do wykorzystania przez programistę oraz osobę zatwierdzającą.

## 10. Jakie funkcje byłyby konkretnie potrzebne

Poniżej **proponowane wymagania produktu**, nie znana lista zakupowa Goldman Sachs.

| Potrzeba | Najprostsza funkcja | Co uznać za dowód |
|---|---|---|
| Wiedzieć, kto działa | Tożsamość użytkownika, agenta i zadania | Agent nie może zmienić swojej roli przez argument narzędzia |
| Ograniczyć dostęp | Zakres klienta i zasobów | Odczyt dokumentu spoza zakresu zostaje zatrzymany |
| Oddzielić czytanie od działania | Reguły per narzędzie i parametry | Prawo do czytania nie umożliwia eksportu |
| Kontrolować odbiorcę | Sprawdzony kontakt powiązany z procesem | Zmiana adresata powoduje odmowę lub nową zgodę |
| Wiedzieć, co zatwierdzono | Zgoda związana z wersją operacji | Inna treść lub parametry nie korzystają ze starej zgody |
| Ograniczyć powtórzenia | Jednorazowa zgoda i identyfikator wykonania | Dwa równoległe żądania nie wykonują dwóch wysyłek |
| Ograniczyć zasoby | Liczba kroków, czas, równoległość, rezerwacje kosztu | Przekroczenie jest blokowane przed następnym wywołaniem |
| Zatrzymać zadanie | Odwołanie mandatu | Następna operacja jest zablokowana po odwołaniu |
| Wyjaśnić odmowę | Krótki powód i bezpieczna ścieżka korekty | Użytkownik potrafi poprawić brakujący parametr |
| Odtworzyć zdarzenie | Rejestr propozycji, decyzji i rezultatu | Widać również odmowy, timeouty i niewykonane działania |
| Chronić sam rejestr | Ograniczony dostęp i minimalizacja danych | Brak sekretów i pełnych dokumentów w zwykłym logu |
| Nie utrudniać integracji | Jeden adapter albo mały SDK | Drugie narzędzie można podłączyć bez przepisywania procesu |

**Ważny warunek techniczny:** identyfikatory i klasyfikacje używane do kontroli muszą pochodzić z zaufanej warstwy. Etykieta „publiczne”, którą model sam dopisze do poufnego dokumentu, nie może zmienić prawa do jego eksportu.

## 11. Siedem potencjalnych rozwiązań, wyjaśnionych prosto

### A. ActionSeal — zgoda na dokładne działanie

**Jedno zdanie:** system pilnuje, żeby agent wykonał dokładnie to, na co pozwoliły reguły i zgodził się człowiek.

**Użytkownik:** programista agenta oraz pracownik zatwierdzający wrażliwe operacje.

**MVP:** trzy narzędzia, reguły dostępu, propozycja eksportu, zgoda powiązana z parametrami i wersją pakietu, jednorazowe wykonanie, rejestr decyzji.

**Demo:** pakiet klienta trafia do zatwierdzonego odbiorcy. Próba zmiany adresata, podmiany załącznika lub ponownego użycia zgody zostaje zatrzymana przed wysyłką.

**Wartość:** szybsza praca przy zachowaniu kontroli operacji. **Ograniczenie:** nie dowodzi poprawności każdego zdania w pakiecie ani ochrony kanałów poza wykonawcą.

### B. AgentSpend — budżet zadania egzekwowany przed wywołaniem

**Jedno zdanie:** agent nie może rozpocząć kolejnej płatnej czynności, jeśli nie ma na nią dostępnego budżetu.

**Użytkownik:** właściciel platformy agentowej i osoba odpowiedzialna za koszty.

**MVP:** dwa narzędzia o znanym maksymalnym koszcie, atomowe rezerwacje, limit prób i równoległości, koszt rozliczony oddzielony od zarezerwowanego.

**Demo:** wiele równoległych żądań bez przekroczenia przyjętego limitu dla chronionych narzędzi.

**Wartość:** przewidywalność i ograniczenie pętli. **Ograniczenie:** nie jest limitem całego rachunku chmurowego. Nieznane lub asynchroniczne koszty wymagają dodatkowych ograniczeń.

### C. ClientBoundary — teczka klienta jako granica dostępu

**Jedno zdanie:** agent pracuje na dokumentach właściwego klienta i nie przenosi ich do niedozwolonego miejsca.

**Użytkownik:** onboarding, operacje, właściciel repozytorium danych.

**MVP:** dwa syntetyczne klienty, dokumenty z metadanymi, ograniczony odczyt i eksport, kontrola tożsamości.

**Demo:** dokument klienta B nigdy nie trafia do kontekstu zadania klienta A; próba eksportu danych poza dozwolony kanał zostaje zatrzymana.

**Wartość:** bardzo czytelna ochrona danych. **Ograniczenie:** klasyfikacja i filtrowanie muszą obejmować wszystkie wejścia. Wykrywanie dowolnej poufnej informacji samym LLM-em będzie niepewne.

### D. DelegationFirewall — pomocnik nie dostaje większych praw

**Jedno zdanie:** agent może zlecić pracę pomocnikowi, ale nie może nadać mu więcej uprawnień niż sam posiada.

**Użytkownik:** zespoły tworzące systemy z wieloma agentami.

**MVP:** dwa–trzy agenty, granty zawężające uprawnienia, wspólny budżet i odwołanie zadania.

**Demo:** agent od dokumentów tworzy podagenta do ekstrakcji pól. Pomocnik nie może wysłać dokumentu ani przywołać dodatkowego klienta.

**Wartość:** kontrola całego łańcucha. **Ograniczenie:** łatwo rozszerzyć zakres ponad 24 godziny; podagenty i adaptery muszą respektować ten sam system uprawnień.

### E. EvidenceDesk — dowód dla każdej ważnej operacji

**Jedno zdanie:** po działaniu agenta można szybko ustalić, kto je zlecił, co sprawdzono i jaki był rezultat.

**Użytkownik:** właściciel procesu, security, compliance i osoba badająca incydent.

**MVP:** oś zdarzeń, identyfikatory źródeł i wersji, decyzja reguły, zatwierdzający, stan wykonania, eksport minimalnego raportu.

**Demo:** porównanie sukcesu, odmowy i timeoutu; każda sytuacja ma inny, prawdziwy stan.

**Wartość:** mniej czasu na odtwarzanie zdarzeń. **Ograniczenie:** obserwacja nie blokuje operacji. To dobry dodatek do ActionSeal, słabszy samodzielny rdzeń zadania kontroli.

### F. ToolRegistry — agent korzysta z zatwierdzonych narzędzi

**Jedno zdanie:** organizacja wie, jakie narzędzia agent może uruchamiać i czy ich definicje nie zmieniły się po przeglądzie.

**Użytkownik:** platform engineering i security.

**MVP:** rejestr dwóch narzędzi, wersje i schematy, właściciel, status dopuszczenia, blokada niezatwierdzonej zmiany.

**Demo:** zmieniony schemat lub opis narzędzia wymaga przeglądu i nie jest automatycznie używany.

**Wartość:** mniejsza powierzchnia integracji i jawna odpowiedzialność. **Ograniczenie:** hash definicji nie dowodzi, że implementacja narzędzia jest bezpieczna. OWASP opisuje zmiany narzędzi i ryzyko łańcucha dostaw. [OWASP: MCP Security][owasp-mcp].

### G. PolicyWorkbench — sprawdzenie reguł przed ich użyciem

**Jedno zdanie:** zanim nowa reguła trafi do agentów, można sprawdzić, jakie legalne i niedozwolone działania dopuści.

**Użytkownik:** autor polityk oraz programista integracji.

**MVP:** zestaw przykładowych operacji, edytowalna reguła, wyniki przed zmianą i po niej, wykrywanie niezamierzonych zezwoleń i blokad.

**Demo:** reguła „każdy może wysyłać do domeny firmy” dopuszcza za dużo; zawężenie do wskazanego odbiorcy usuwa lukę bez blokowania legalnego przebiegu.

**Wartość:** łatwiejsze tworzenie i przegląd polityk. **Ograniczenie:** działa na znanych scenariuszach. Sam symulator bez podłączonego wykonawcy nie dowodzi kontroli rzeczywistych działań.

## 12. Który pomysł wybrać na 24 godziny

Oceny 1–5 są **moją oceną jakościową**, zależną od pełnego briefu i umiejętności zespołu. Przy wykonalności 5 oznacza łatwiejszy zakres; przy pozostałych kryteriach 5 oznacza silniejszy wynik. To nie szacunki szans wygrania.

| Pomysł | Związek z zapowiedzią | Czytelność demo | Wykonalność | Wniosek |
|---|---:|---:|---:|---|
| ActionSeal | 5 | 5 | 4 | Najlepszy rdzeń: precyzyjna zgoda i widoczne egzekwowanie |
| AgentSpend | 5 | 5 | 5 | Dobry węższy projekt albo wariant, gdy brief akcentuje koszty |
| ClientBoundary | 5 | 5 | 4 | Bardzo dobry scenariusz danych; część można połączyć z ActionSeal |
| DelegationFirewall | 5 | 4 | 2 | Wybrać, jeżeli delegacja będzie centralna w briefie i macie czas |
| EvidenceDesk | 4 | 4 | 5 | Dodać jako mały widok wyniku i dowodu |
| ToolRegistry | 4 | 4 | 3 | Sensowny, jeżeli partner akcentuje narzędzia / MCP |
| PolicyWorkbench | 4 | 4 | 4 | Dodatek ułatwiający pokazanie reguł i produktywności |

**Rekomendacja: ActionSeal z prostą granicą danych klienta i rejestrem operacji.** Budżet najpierw jako ograniczenie liczby kroków. Rezerwacje pieniężne dodać tylko wtedy, gdy działający rdzeń już istnieje albo pełny brief wymaga tego wprost.

Wcześniejszy raport proponował wysyłkę faktury. Scenariusz pakietu onboardingowego lepiej nawiązuje do oficjalnie wskazanego kierunku OneGS 3.0. Mechanizm pozostaje ten sam: agent proponuje, reguły ograniczają, człowiek zatwierdza właściwą operację, wykonawca sprawdza zgodność.

## 13. Rekomendowane demo: pakiet dokumentów nowego klienta

### Historia użytkownika

Pracownik ma przygotować dokumenty fikcyjnej firmy **Northbridge Manufacturing** do wewnętrznego przeglądu. Agent może odczytać jej teczkę, znaleźć braki i przygotować pakiet. Eksport pakietu jest osobną operacją wymagającą zgody.

To **scenariusz demonstracyjny**. Nie przedstawia rzeczywistej procedury KYC Goldman Sachs. Prototyp wspomaga przygotowanie materiału; nie podejmuje decyzji, że klient spełnia wszystkie wymagania.

### Trzy narzędzia wystarczą

| Narzędzie | Co robi | Kontrola |
|---|---|---|
| `read_client_documents` | Odczytuje syntetyczne dokumenty wskazanego klienta | Tożsamość, klient i dopuszczony zakres dokumentów |
| `build_review_packet` | Tworzy pakiet z polami, źródłami i brakami | Dozwolone wejścia; zapis nowej, niezmiennej wersji pakietu |
| `export_review_packet` | Przekazuje pakiet do testowej skrzynki / lokalnego odbiornika | Dopuszczony odbiorca, zgodna wersja, ważna jednorazowa zgoda |

**Dane:** dwie fikcyjne firmy, po trzy krótkie dokumenty, kilka pól poufnych i sprawdzone metadane. Druga firma służy do pokazania odmowy odczytu spoza zakresu.

**Minimalny interfejs:** pole zadania; lista kroków agenta; panel zatwierdzenia z dokładnym odbiorcą i zakresem; lista faktycznie wykonanych operacji. Przy odmowie pokazać powód i potwierdzenie, że wykonawca nie został uruchomiony.

### Scenariusz prezentacji w 60 sekund

1. **0–10 s:** pracownik zleca przygotowanie pakietu. Agent czyta właściwą teczkę i pokazuje źródła oraz brakujący dokument.
2. **10–20 s:** pracownik zatwierdza eksport wersji 1 do wskazanego odbiorcy. Działanie dochodzi do testowego odbiornika.
3. **20–35 s:** w alternatywnym przebiegu dokument zawiera instrukcję przekierowania danych. Nawet jeśli agent proponuje inny adres, warstwa kontroli blokuje eksport.
4. **35–50 s:** po zgodzie podmieniamy odbiorcę lub wersję pakietu. Wykonawca odmawia. Ponowne użycie zużytej zgody także nie uruchamia wysyłki.
5. **50–60 s:** ekran dowodu pokazuje legalny eksport, odmowy i liczbę uruchomień wykonawcy.

Scenariusze zagrożeń uruchamiać na osobnych zadaniach, aby stan wcześniejszego demo nie zamaskował przyczyny blokady. Jeżeli wyniki LLM są niestabilne, deterministyczne propozycje operacji mogą stanowić osobny tryb testowy, jawnie oznaczony w prezentacji.

### Co musi być realne w prototypie

- Kontrola po stronie serwera, przed uruchomieniem chronionego narzędzia.
- Rozróżnienie tożsamości pracownika, agenta i zatwierdzającego.
- Sprawdzenie parametrów oraz wersji pakietu przy wykonaniu.
- Atomowe przejście zgody ze stanu dostępnego do wykorzystanego.
- Rejestr, który odróżnia propozycję, zatwierdzenie i wykonanie.

**Co może być symulacją:** bankowa baza dokumentów, system KYC i skrzynka odbiorcza. Informacja o symulacji musi być widoczna. Autentyczna blokada przed adapterem testowej skrzynki nadal jest wartościowym dowodem mechanizmu; nie jest testem integracji z Goldman Sachs.

## 14. Jak ta warstwa działa — krótko dla osób technicznych

```mermaid
flowchart LR
    U[Pracownik zleca zadanie] --> A[Agent proponuje operację]
    A --> P[Kontroler sprawdza reguły]
    P -->|dozwolone| E[Wykonawca sprawdza i wykonuje]
    P -->|wymagana zgoda| H[Człowiek zatwierdza parametry]
    H --> E
    P -->|zakazane| D[Odmowa bez wykonania]
    E --> L[Rejestr rezultatu]
    D --> L
```

**Agent nie decyduje o swoich uprawnieniach.** Dla każdego wywołania kontroler dostaje strukturę opisującą użytkownika, agenta, zadanie, narzędzie, zasób i parametry. Tożsamość bierze z uwierzytelnionej sesji, a zakres danych z metadanych kontrolowanych przez serwer.

### Trzy możliwe decyzje

| Decyzja | Znaczenie | Przykład w fikcyjnej polityce demo |
|---|---|---|
| `ALLOW` | Można wykonać w tym zakresie | Odczyt dokumentu właściwego klienta |
| `REQUIRE_APPROVAL` | Bez odpowiedniej zgody wykonanie jest zatrzymane | Eksport pakietu do dopuszczonego odbiorcy |
| `DENY` | Operacja jest niedopuszczona | Odczyt innego klienta lub eksport do obcego adresu |

Człowiek nie może jednym kliknięciem ominąć zakazu wynikającego z reguły, której nie ma prawa zmienić. Zmiana polityki wymaga osobnego uprawnienia i procesu.

### Co wiąże zgodę z działaniem

W proponowanym modelu zgoda obejmuje: identyfikator zadania i operacji, użytkownika, agenta, narzędzie, istotne parametry, odbiorcę, identyfikator oraz wersję/skrót treści pakietu, termin ważności i zatwierdzającego. Można także zapisać wersję polityki; wykonawca nadal sprawdza jej aktualność i odwołanie uprawnień.

Przed wykonaniem kontrolowany adapter sprawdza komplet warunków. Klucza uprawniającego do eksportu nie przekazuje agentowi. Reguły widoczności, jednorazowości, czasu ważności i kontroli serwerowej mają wcześniejsze odpowiedniki w autoryzacji transakcji. [OWASP: Transaction Authorization][owasp-transaction].

**Istotne szczegóły:** stabilne przedstawienie parametrów do porównania; niezmienna wersja załącznika; atomowość zużycia zgody; jawny stan błędu i timeoutu. Przy rzeczywistym zewnętrznym skutku potrzebna jest również obsługa idempotencji i uzgodnienia statusu.

**Ochrona musi obejmować dostępne drogi działania:** bezpośrednie API, kod wykonywany przez agenta, sieć, pliki i narzędzia. Jeżeli kontrolujemy tylko trzy adaptery, deklaracja bezpieczeństwa dotyczy tych adapterów i przyjętej izolacji. [OWASP: AI Agent Security][owasp-ai-agent].

### Zakres rozwoju po hackathonie

Potencjalne kolejne kroki: integracja z firmowym systemem tożsamości; zarządzanie politykami; trwały magazyn zgód i zdarzeń; odporność na awarie; ograniczenia sieci; polityka retencji danych; adaptery systemów docelowych; przegląd bezpieczeństwa; testy na rzeczywistych procesach. Są to wymagania możliwego wdrożenia, a nie elementy, które trzeba obiecać w 24-godzinnym prototypie.

## 15. Jak sprawdzić, czy rozwiązanie rzeczywiście działa

Poniżej **plan weryfikacji przyszłego prototypu**. Research nie zawiera implementacji ani wyników tych testów.

| Nr | Przypadek | Oczekiwany wynik |
|---:|---|---|
| 1 | Legalny odczyt dokumentu klienta A | Odczyt dopuszczony |
| 2 | Legalna budowa pakietu z właściwych dokumentów | Powstaje wersja ze źródłami i brakami |
| 3 | Eksport do dopuszczonego odbiorcy po ważnej zgodzie | Jeden rezultat w odbiorniku |
| 4 | Odczyt dokumentu klienta B w zadaniu A | Odmowa przed adapterem odczytu |
| 5 | Agent deklaruje rolę administratora w parametrach | Deklaracja nie zmienia tożsamości ani uprawnień |
| 6 | Tekst w dokumencie nakazuje niedopuszczony eksport | Propozycja jest odrzucona przez kontrolę |
| 7 | Eksport bez zgody | Brak wykonania; oczekiwanie na decyzję |
| 8 | Zgoda użytkownika bez prawa zatwierdzania | Odmowa |
| 9 | Zmieniony odbiorca po zatwierdzeniu | Odmowa / nowa propozycja do przeglądu |
| 10 | Zmieniona wersja albo zawartość załącznika po zgodzie | Odmowa |
| 11 | Zmienione inne istotne parametry | Odmowa |
| 12 | Użycie zgody w innym zadaniu lub przez innego agenta | Odmowa |
| 13 | Ponowne użycie zgody | Brak drugiego wykonania |
| 14 | Dwa równoległe żądania z tą samą zgodą | Maksymalnie jedno przejście do wykonawcy |
| 15 | Wygasła zgoda | Odmowa |
| 16 | Odwołany mandat lub zmieniona polityka | Ponowna ocena; stare uprawnienie nie jest bezwarunkowo honorowane |
| 17 | Brak odpowiedzi silnika kontroli | Wrażliwe działanie zatrzymane |
| 18 | Próba ominięcia kontrolera | Brak bezpośrednich uprawnień do chronionego narzędzia |
| 19 | Timeout po rozpoczęciu eksportu | Jawny stan niepewności, sprawdzenie statusu przed ponowieniem |
| 20 | Zestaw legalnych odczytów | Praca przechodzi bez zbędnych zgód |

Jeżeli dodacie AgentSpend: osobne sprawdzenia wielu równoległych rezerwacji, wspólnego budżetu podagentów, limitu prób, timeoutu rozliczenia i nieznanego kosztu. Równoległe żądania muszą konkurować o ten sam trwały limit, a nie o niezależne kopie licznika.

**Mierzyć wywołania wykonawcy i efekty w odbiorniku.** Czerwony komunikat w interfejsie nie dowodzi, że operacja nie została wcześniej wykonana. Dla chronionych odczytów trzeba dodatkowo sprawdzić, że treść nie trafiła do modelu.

Wynik prezentować jako „X/Y określonych scenariuszy zaliczonych w wersji Z, na tych adapterach”. Sformułowania „odporny na wszystkie prompt injection” i „pełne bezpieczeństwo bankowe” wykraczają poza taki dowód.

## 16. Jak pokazać wartość biznesową

| Miernik | Jak go policzyć | Co mówi |
|---|---|---|
| Czas obsługi pakietu | Ten sam zestaw wejść przed zastosowaniem i po zastosowaniu narzędzia | Czy użytkownik rzeczywiście kończy zadanie szybciej |
| Legalne operacje dopuszczone | Liczba dopuszczonych poprawnych przypadków / wszystkie poprawne przypadki | Czy kontrola nie utrudnia zwykłej pracy |
| Niedopuszczone operacje zatrzymane | Liczba zablokowanych przed adapterem / wszystkie wybrane nadużycia | Skuteczność w określonym zestawie scenariuszy |
| Liczba interwencji człowieka | Zatwierdzenia i korekty na jedno zadanie | Koszt obsługi kontroli |
| Opóźnienie kontroli | Czas decyzji i walidacji przy wykonaniu; osobno oczekiwanie na człowieka | Wpływ na szybkość procesu |
| Koszt zaakceptowanego wyniku | Koszt modeli i narzędzi + czas obsługi / poprawnie zakończone zadania | Czy automatyzacja jest opłacalna |
| Czas odtworzenia zdarzenia | Ile czasu potrzebuje druga osoba z rejestrem | Użyteczność dowodu i diagnostyki |
| Wysiłek integracji | Czas dodania kolejnego narzędzia i liczba zmian w jego kodzie | Czy rozwiązanie pomaga programistom |

**Przykład obliczenia, nie dane Goldman Sachs:** 500 pakietów miesięcznie × 3 minuty zaoszczędzone na pakiet = 25 godzin miesięcznie. Przy założeniu 250 zł za godzinę to 6 250 zł wartości czasu, zanim odliczymy koszt AI, integracji i obsługi kontroli. To nie jest automatycznie oszczędność gotówkowa ani prognoza dla banku.

Nie mamy danych o rzeczywistym wolumenie, czasie procesu, kosztach błędów ani gotowości Goldman Sachs do zakupu takiego rozwiązania. Można przygotować arkusz założeń do rozmowy z mentorem; nie można z tego researchu wyliczyć wiarygodnego ROI dla całej firmy.

### Kto mógłby korzystać i decydować o wdrożeniu

To hipoteza organizacyjna:

- **Programista / platform engineering:** integruje agenta i narzędzia; potrzebuje małej liczby zmian i czytelnego debugowania.
- **Security / IAM:** ustala granice dostępu i sprawdza możliwość obejścia.
- **Właściciel procesu:** odpowiada za czas, poprawność i obsługę wyjątków.
- **Compliance / risk / audyt:** potrzebuje reguł, odpowiedzialności i dowodu przebiegu.
- **Pracownik zatwierdzający:** potrzebuje krótkiej, jednoznacznej decyzji z dokładnymi parametrami.

Juror lub mentor może pomóc wskazać właściwą rolę. Nie należy utożsamiać obecności firmy na hackathonie z deklaracją budżetu wdrożeniowego.

## 17. Co ustalić z mentorami Goldman Sachs

Publiczna lista mentorów wymienia **Macieja Machulaka — Executive Director & Tech Fellow** oraz **Adriana Biniewicza — Vice President**. Nie traktuję tego jako potwierdzenia ich roli w jury. [HackYeah: mentorzy][hack-mentors].

### Pytania, które najszybciej rozstrzygną wybór

1. **Jaki konkretny workflow jest najważniejszy w pełnym zadaniu?** Czy pakiet onboardingowy jest właściwym przykładem?
2. **Jaki dowód kontroli najbardziej się liczy?** Dostęp do danych, autoryzacja działania, budżet czy delegacja?
3. **Czy jedna głęboko sprawdzona ścieżka wystarczy?** Czy zadanie wymaga pokrycia wszystkich trzech ryzyk z zapowiedzi?
4. **Jakie integracje są obowiązkowe?** MCP, konkretne SDK, agent, model, hosting lub dane od partnera?
5. **Gdzie ma być człowiek?** Które operacje mogą przechodzić automatycznie, a które wymagają zgody?
6. **Jak oceniacie produktywność?** Mniejsza liczba zgód, prostsza integracja czy czas zakończenia zadania?

### Pytania do dopracowania rozwiązania

7. Czy chcecie ograniczać agenta do uprawnień zleceniodawcy, czy również do osobnego mandatu zadania?
8. Czy zgoda powinna obejmować wersję i zawartość dokumentu oraz dokładnego odbiorcę?
9. Jakie awarie i obejścia warto pokazać? Zmiana uprawnień, replay, równoległość czy dostęp poza gatewayem?
10. Jakie elementy śladu operacji są potrzebne, a jakich danych nie powinno być w logach?
11. Czy syntetyczne dane i testowy odbiornik są akceptowalne, jeśli kontrola wykonania jest rzeczywista?
12. Jakie są zasady punktacji, wymagane pliki oraz warunki praw do projektu?

**Cel rozmowy:** jeden użytkownik, jeden workflow, jedna najważniejsza kontrola i dwa–trzy scenariusze, które partner uważa za istotne. Ogólne pytanie „jakie problemy ma Goldman Sachs?” trudniej przełożyć na konkretną decyzję.

## 18. Krótkie wyjaśnienie do prezentacji

### Po polsku

Agenci AI potrafią przygotować dokumenty, korzystać z firmowych systemów i wykonywać kolejne kroki za pracownika. Problem pojawia się wtedy, gdy źle zrozumieją zadanie, odczytają nieuprawnione dane albo wykonają inną operację niż ta, którą człowiek zatwierdził.

ActionSeal sprawdza działanie przed jego wykonaniem. Na przykładzie pakietu nowego klienta pokazujemy, że legalna praca przechodzi sprawnie, a zmiana odbiorcy, podmiana załącznika i ponowne użycie zgody są blokowane. Każda decyzja ma ślad, który można sprawdzić. To prototyp kontroli wskazanych narzędzi na syntetycznych danych.

### Po angielsku — opis koncepcji, do dopasowania po implementacji

AI agents can read documents, use enterprise tools, and complete workflows on behalf of employees. Organizations need to control whose authority an agent uses, which data it can access, and whether the action it executes matches the action that was approved.

ActionSeal is a proposed control layer for a client onboarding review workflow. It checks tool calls before execution and binds approval to the recipient, parameters, and document version. Our planned demo will show a successful authorized export, blocked parameter changes, and blocked reuse of approval. It will use synthetic documents and a test destination, with visible records of decisions and execution outcomes.

**Po zbudowaniu:** zmienić czas przyszły wyłącznie przy funkcjach, które rzeczywiście działają. Dodać uzyskany wynik scenariuszy, zakres adapterów i faktyczny koszt/opóźnienie. Nie dopisywać niezmierzonych procentów oszczędności.

## 19. Słownik w prostych słowach

| Pojęcie | Znaczenie |
|---|---|
| Agent AI | Program korzystający z modelu, który wybiera kroki i uruchamia narzędzia, aby osiągnąć cel |
| Narzędzie / tool | Funkcja, którą agent może wywołać: odczyt dokumentu, zapis rekordu, eksport |
| API | Sposób, w jaki program zleca czynność innemu systemowi |
| MCP | Protokół łączenia aplikacji AI z narzędziami i danymi |
| Uwierzytelnienie | Sprawdzenie, kto się zgłasza |
| Autoryzacja | Sprawdzenie, czy ten podmiot może wykonać konkretną czynność |
| Mandat zadania | Ograniczony zakres pracy: cel, zasoby, dozwolone działania i limity |
| Policy / polityka | Reguła określająca, kiedy działanie jest dozwolone |
| Prompt injection | Polecenie podsunięte przez niezaufaną treść, które próbuje zmienić działanie AI |
| Replay | Próba ponownego użycia wcześniejszego komunikatu albo upoważnienia |
| Idempotencja | Ponowienie tej samej operacji nie powoduje kolejnego skutku |
| Audit trail | Zapis pozwalający odtworzyć zlecenie, decyzję i rezultat |
| KYC | Poznanie i weryfikacja klienta w wymaganym procesie instytucji finansowej |
| AML | Przeciwdziałanie praniu pieniędzy |
| IAM | Zarządzanie tożsamościami i ich dostępem |
| Fail closed | Brak możliwości potwierdzenia zgody oznacza zatrzymanie chronionej operacji |

## 20. Źródła i granice weryfikacji

Źródła internetowe sprawdzono **2 października 2026**. Poniżej źródła rzeczywiście wykorzystane; data publikacji jest podana tam, gdzie została potwierdzona. Dla dokumentacji istotna jest wersja/strona dostępna podczas researchu, ponieważ może się zmienić.

| Nr | Źródło | Co wykorzystano |
|---:|---|---|
| 1 | [HackYeah: Tasks & Prizes][hack-task] | Aktualna karta GS, język, pula i trzy ryzyka; odczyt na żywo w przeglądarce |
| 2 | [HackYeah: mentorzy][hack-mentors] | Publiczne role dwóch mentorów GS |
| 3 | [Goldman Sachs: Our Businesses][gs-business] | Kontekst usług i użytkowników |
| 4 | [Goldman Sachs: Annual Report 2025, 20.03.2026][gs-letter] | OneGS 3.0 i sześć obszarów modernizacji |
| 5 | [Goldman Sachs: Form 10-K za 2025][gs-10k] | Ryzyka AI i struktura nadzoru; odczyt fragmentów w przeglądarce SEC |
| 6 | [Goldman Sachs: AI Exchanges, 04.02.2025][gs-assistant] | Własny asystent AI i kontekst instytucji regulowanej |
| 7 | [Goldman Sachs: Building AI Systems for Capital Markets, 24.08.2026][gs-capital-ai] | Źródła, środowisko agentów i upoważnienie do działania; nagranie 11.08.2026 |
| 8 | [Goldman Sachs: Consumer Agents, 18.09.2026][gs-consumer] | Analiza rynku agentów; oddzielona od wdrożeń wewnętrznych |
| 9 | [Goldman Sachs: Warsaw Hackathon, 23.12.2025][gs-warsaw] | Lokalny kontekst engineering i wydarzenie z listopada 2025 |
| 10 | [Anthropic: Agents for financial services, 05.05.2026][anthropic-finance] | Istniejące szablony agentów finansowych; komunikat producenta |
| 11 | [Anthropic: enterprise AI services company, 04.05.2026][anthropic-services] | Udział GS w przedsięwzięciu; odróżniony od użycia wewnętrznych agentów |
| 12 | [FINRA: GenAI, raport nadzorczy 2026][finra-ai] | Nadzór, zakres, audytowalność i dane w systemach agentowych |
| 13 | [EBA: zmiany wytycznych w kontekście DORA, 11.02.2025][eba-dora] | Zakres ryzyka ICT i data stosowania DORA |
| 14 | [Federal Reserve: SR 26-2, 17.04.2026][fed-letter] | Zastąpienie SR 11-7 i SR 21-8 |
| 15 | [SR 26-2: załącznik][fed-guidance] | Wyłączenie generatywnego i agentowego AI, przypis 3, strona 3 |
| 16 | [NIST: AI Agent Standards Initiative, 17.02.2026][nist-agents] | Prace nad bezpieczeństwem, interoperacyjnością i tożsamością |
| 17 | [NIST/NCCoE: tożsamość i autoryzacja agentów][nist-identity] | Zakres inicjatywy; nie gotowy certyfikat |
| 18 | [OWASP: Top 10 for Agentic Applications 2026][owasp-agentic] | Kontekst zagrożeń; karta publikacji, nie pełna analiza całego raportu |
| 19 | [OWASP: MCP Security Cheat Sheet][owasp-mcp] | Dostęp, narzędzia, wyprowadzanie danych i integracje |
| 20 | [OWASP: Transaction Authorization][owasp-transaction] | Parametry zgody, kontrola serwerowa, ważność i jednorazowość |
| 21 | [OWASP: AI Agent Security][owasp-ai-agent] | Granice narzędzi i środowiska agenta |
| 22 | [MCP: Security Best Practices, wersja 2025-11-25][mcp-security] | Tożsamość, tokeny, pośrednicy i granice integracji |
| 23 | [OPA: HTTP API authorization][opa] | Istniejący silnik reguł i wzorzec autoryzacji |
| 24 | [AWS: AgentCore Policy][aws-agentcore] | Istniejąca kontrola wywołań poza agentem |
| 25 | [AWS: AgentCore Policy — core concepts][aws-concepts] | Cedar i semantyka reguł |
| 26 | [NVIDIA: NeMo Guardrails][nemo] | Dostępny zestaw mechanizmów guardrails |
| 27 | [AWS: Managing your costs with AWS Budgets][aws-budgets] | Opóźnienia rozliczeń i powiadomień |

### Co zweryfikowano

Opis publicznego zadania oraz jego brak osobnego odnośnika do szczegółów na karcie; kierunek strategii w liście do akcjonariuszy; wskazane fragmenty ryzyk i nadzoru w Form 10-K; publiczne wypowiedzi Goldman Sachs; wymienione komunikaty rynkowe; istotne fragmenty wskazówek regulatorów i dokumentacji.

Odczyt Form 10-K przez narzędzie tekstowego przeglądania początkowo zwracał błąd. Treść została następnie odczytana z oficjalnej strony SEC w przeglądarce. Nie zapisano ani nie analizowano lokalnej kopii PDF pełnego raportu. Karta HackYeah również wymagała przeglądarki z załadowanymi danymi; sama odpowiedź tekstowa strony nie pokazywała zadań.

### Czego ten research nie potwierdza

Wewnętrznej architektury GS, konkretnych luk bezpieczeństwa, wybranego stosu agentowego, produkcyjnego wdrożenia każdego opisanego procesu, rzeczywistych kosztów lub wolumenów, zamiaru zakupu rozwiązania, pełnego briefu i regulaminu zadania ani skuteczności przyszłego prototypu. Materiały firm opisują ich deklaracje; dokumentacja producentów opisuje deklarowane funkcje, których nie testowano w tym researchu.

**Decyzja proponowana zespołowi:** rozpocząć od ActionSeal na syntetycznym pakiecie klienta, a po publikacji pełnego briefu potwierdzić z mentorem, czy priorytetem jest precyzyjna autoryzacja, dane czy budżet. Właściwy kod konkursowy tworzyć w terminie dopuszczonym przez zasady wydarzenia.

[hack-task]: https://hackyeah.pl/tasks-prizes
[hack-mentors]: https://hackyeah.pl/mentors
[gs-business]: https://www.goldmansachs.com/what-we-do/our-businesses
[gs-letter]: https://www.goldmansachs.com/investor-relations/financials/current/annual-reports/2025-annual-report
[gs-10k]: https://www.sec.gov/Archives/edgar/data/886982/000088698226000091/gs-20251231.htm
[gs-assistant]: https://www.goldmansachs.com/insights/goldman-sachs-exchanges/ai-exchanges-will-falling-costs-drive-new-opportunities
[gs-capital-ai]: https://www.goldmansachs.com/insights/goldman-sachs-exchanges/building-ai-systems-for-capital-markets
[gs-consumer]: https://www.goldmansachs.com/insights/articles/consumer-agents-signal-new-phase-for-ai-growth
[gs-warsaw]: https://www.goldmansachs.com/careers/blog/warsaw-hackathon
[anthropic-finance]: https://www.anthropic.com/news/finance-agents
[anthropic-services]: https://www.anthropic.com/news/enterprise-ai-services-company
[finra-ai]: https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai
[eba-dora]: https://www.eba.europa.eu/publications-and-media/press-releases/eba-amends-its-guidelines-ict-and-security-risk-management-measures-context-dora-application
[fed-letter]: https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm
[fed-guidance]: https://www.federalreserve.gov/supervisionreg/srletters/SR2602a1.pdf
[nist-agents]: https://www.nist.gov/news-events/news/2026/02/announcing-ai-agent-standards-initiative-interoperable-and-secure
[nist-identity]: https://www.nccoe.nist.gov/projects/software-and-si-agent-identity-and-authorization
[owasp-agentic]: https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
[owasp-mcp]: https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html
[owasp-transaction]: https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html
[owasp-ai-agent]: https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html
[mcp-security]: https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices
[opa]: https://www.openpolicyagent.org/docs/http-api-authorization
[aws-agentcore]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html
[aws-concepts]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-core-concepts.html
[nemo]: https://docs.nvidia.com/nemo/guardrails/about-nemo-guardrails-library/overview
[aws-budgets]: https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html
