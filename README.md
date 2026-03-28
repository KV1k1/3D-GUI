# **Vizualizácia 3D objektov pomocou GUI frameworkov v jazyku Python**



## Obsah
- [O projekte](#o-projekte)
- [Ciele práce](#ciele-práce)
- [Návrh systému](#návrh-systému)
- [Architektúra riešenia](#architektúra-riešenia)
- [Implementácia](#implementácia)
- [Testovanie a výsledky](#testovanie-a-výsledky)
- [Inštalácia a spustenie](#inštalácia-a-spustenie)


## Ciele práce

Hlavným cieľom tejto bakalárskej práce je praktické porovnanie a vyhodnotenie vybraných GUI frameworkov v programovacom jazyku Python pre vizualizáciu 3D objektov, so zameraním na ich využitie v hernom vývoji. Čiastkové ciele:

1. **Analýza a výber frameworkov** – preskúmať aktuálny stav využívania 3D vizualizácie v rámci Python GUI frameworkov a na základe komparatívnej analýzy vybrať tri, ktoré najlepšie reprezentujú rôzne úrovne funkcionality.
2. **Návrh a implementácia herného prototypu** – navrhnúť architektúru jednoduchej desktopovej hry s integrovanou 3D vizualizáciou, ktorá využíva princípy objektovo-orientovaného programovania a modulárny dizajn.
3. **Implementácia prototypu v jednotlivých frameworkoch** – vytvoriť tri implementácie rovnakého herného prototypu vo vybraných frameworkoch so zachovaním zhodnej funkcionality, mechaník a 3D scény.
4. **Testovanie a vyhodnotenie** – vykonať sadu kvantitatívnych a kvalitatívnych metrík na všetkých troch verziách herného prototypu.
5. **Formulovanie záverov a odporúčaní** – na základe výsledkov zhodnotiť efektivitu jednotlivých frameworkov a vytvoriť odporúčanie pre výber vhodnej technológie.

---

## Návrh systému

### Herný prototyp

Prototypom, ktorý slúži ako testovacie prostredie, je 3D hra typu bludisko s názvom **Within the Walls** s pohľadom z prvej osoby. Hráč sa pohybuje v trojrozmernom priestore, zbiera mince, aktivuje minihry a vyhýba sa nepriateľom a pasciam. Kombinácia kontinuálneho 3D vykresľovania s perspektívnou kamerou, real-time hernej logiky, komplexného GUI a správy vstupov umožňuje merať výkon frameworkov v realistickom scenári.

### Výber frameworkov

Táto trojica frameworkov pokrýva široké spektrum – od tradičného natívneho prístupu, cez profesionálny a výkonnostne orientovaný ekosystém, až po moderný GPU-first prístup zameraný na multiplatformovú konzistentnosť:

### Funkčné požiadavky
-	Vizualizácia 3D priestoru: Aplikácia musí vedieť vykresliť 3D bludisko, zbierateľné mince a fragmenty kľúča, nepriatelia, textúry.
-	Ovládanie: Hráč musí mať možnosť pohybovať pomocou klávesov WASD a ovládať pohľad kamery pomocou myši.
- Detekcia kolízií s mincami, ktoré sú po zbere odstránené a zvýšia skóre.
- Aktivácia 3D puzzle minihry po zbere fragmentu kľúča.
-  Implementácia pohyblivých prekážok: 5 typov duchovia s unikátnymi superschopnosťami a pohyb po preddefinovaných trasách, hroty sa vysúvajú v časových intervaloch, platforma s cyklickým pohybom, brány sa odomykajú po splnení podmienok.
-	Detekcia kolízií s nepriateľmi a pascami, po ktorom je hráč presunutý do väzenia.
-	 Možnosť oslobodiť sa z väzenia interakciou s knihou, ktorá spustí minihru na kreslenie siluety.
-	HUD musí zobrazovať počet mincí, fragmentov kľúča, herný čas a minimapu.
-	Pauzovacie menu musí umožňovať pokračovanie, reštart, výber levelu, uloženie a ukončenie hry.
-	Hra musí prehrávať zvukové efekty pre kroky, zber mince, otváranie brán a kolíziu s duchom.

### Nefunkčné požiadavky
-	Výkon: Aplikácia musí dosahovať priemerný počet snímok za sekundu (FPS) aspoň 30 na referenčnom hardvéri pre plynulý zážitok.
-	Použiteľnosť: Odozva na vstupy z klávesa a z myša musí byť okamžitá, bez citeľného oneskorenia.
-	Kompatibilita: Aplikácia musí byť spustiteľná na operačných systémoch Windows a Linux bez zmeny zdrojového kódu.
-	Udržateľnosť: Kód musí byť čitateľný, dobre štruktúrovaný a modulárny, herné jadro oddelené od GUI, aby umožňoval ľahké úpravy a rozširovanie.


### Diagram prípadov použitia

<img src="https://github.com/KV1k1/3D-GUI/blob/main/docs/use_case.png">

*Obrázok 1 – Interakcia hráča s herným systémom*

---

## Architektúra riešenia

Kľúčovým architektonickým rozhodnutím je striktné oddelenie herného jadra od renderovacích adaptérov. Tento návrh vychádza z princípu MVC (Model-View-Controller), kde herné jadro predstavuje model, adaptéry frameworkov zastrešujú view a controller. Každý adaptér dostane identické herné jadro a testuje sa iba jeho schopnosť poskytovať vizualizačné a vstupné rozhranie.

Modul `core/game_core.py` neobsahuje žiadny import z GUI frameworkov. Trieda `GameCore` komunikuje s adaptérmi výlučne cez systém udalostí – adaptér zaregistruje funkcie pre udalosti ako `coin_picked`, `gate_opened`, `game_won`, a jadro ich vyvolá v správnom momente.

<img src="https://github.com/KV1k1/3D-GUI/blob/main/docs/package_diagram.png">

*Obrázok 2 – Štruktúra herných balíkov*

### Závislosti

```
PyOpenGL
PyOpenGL_accelerate
numpy
psutil
pyqtgraph          # len PySide6 adaptér
reportlab
PySide6
wxPython
Kivy         
```

---

## Implementácia

### Mapa a herný svet

Celý herný svet vychádza z textových definícií máp uložených v súbore `map_data.py`. Systém využíva tri nezávislé vrstvy:

- **Layout** – základná štruktúra sveta (`#` stena, `.` podlaha, `S` štart, `E` výstup)
- **Overlay** – pozície dynamických entít (číslice `1–5` trasy duchov, `K/KH/KP` fragmenty kľúča)
- **Sektorové rozdelenie** – každej bunke priradené písmeno oblasti `A–H` pre vyhľadávanie v O(1)

### Geometria stien: od immediate mode k VBO

Spočiatku sa steny vykresľovali v immediate mode – každú snímku sa geometria posielala z CPU do GPU znova. Na Úrovni 2 s väčším bludiskom to viedlo k 12–18 snímkam za sekundu. Riešením bol prechod na **Vertex Buffer Objects (VBO)**: celá statická geometria stien a podláh sa nahrala do pamäte GPU jednorazovo pri inicializácii. Svet bol rozdelený na chunky 12×12 buniek a každú snímku sa vykresľujú iba chunky v dosahu viditeľnosti hráča.

Kivy vyžaduje OpenGL ES 2.0 Core Profile, ktorý nepodporuje immediate mode ani `GL_QUADS` – každý štvorec musel byť rozdelený na dva trojuholníky a všetka geometria sa zostavuje do streaming bufferov. Tento prístup bol následne aplikovaný aj na PySide6 a wxPython pre dynamické entity, aby porovnanie nebolo zaujaté rozdielom OpenGL profilov.

### Duchovia a ich superschopnosti

| Duch | Veľkosť | Rýchlosť | Superschopnosť |
|------|---------|----------|----------------|
| 1 | 2.10 | 1.0 | Obrovský |
| 2 | 1.35 | 1.05 | Prechádza stenami |
| 3 | 1.35 | 1.0 | Základný |
| 4 | 1.35 | 1.85 | Veľmi rýchly |
| 5 | 1.45 | 1.10 | +30 sekúnd k času |

### Minihry

Hra obsahuje dve minihry:

- **3D puzzle** – po zbere fragmentu kľúča; hráč presúva farebné diely šiestimi smermi, kým nezodpovedajú referenčnej zostave. Správnosť sa overuje grafom susednosti.
- **Silhouette puzzle** – vo väzení po chytení duchom; hráč kliknutím na mriežku 6×6 reprodukuje referenčný tvar.

V PySide a wxPython sú minihry implementované ako natívne modálne dialógy. Kivy natívne modálne okná nepodporuje – minihry sú implementované ako `FloatLayout` prekrytia.

### Rozdiely medzi frameworkmi v implementácii

| Aspekt | PySide | wxPython | Kivy |
|--------|---------|----------|------|
| OpenGL widget | `QOpenGLWidget` | `wx.glcanvas.GLCanvas` | `Callback` v canvase |
| OpenGL profil | Core (po optimalizácii) | Compatibility | Core povinne |
| Načítanie textúr | `QImage` – priamy RGBA buffer | `wx.Image` – 2 samostatné polia, nutná vektorizácia NumPy | `KivyCoreImage` – najjednoduchšie |
| Off-screen kreslenie | `QPainter` na `QImage` | `wx.MemoryDC` na `wx.Bitmap` | Neexistuje – manuálne pixel po pixeli |
| Modálne dialógy | `QDialog` natívne | `wx.Dialog` natívne | `FloatLayout` prekrytie |
| Zvuk | `QSoundEffect` – viackanálový | `wx.adv.Sound` – jednokanálový, nestabilný | `SoundLoader` – plnohodnotný |

---

## Testovanie a výsledky

### Metodika

Pre každý framework bolo vykonaných **5 behov na Úrovni 1** a **5 behov na Úrovni 2**. Každý beh predstavoval kompletné dokončenie úrovne. Testovanie prebiehalo na rovnakom hardvéri: AMD Ryzen 5 3600, 16 GB RAM, NVIDIA GeForce GTX 1660 Super, Windows 10.

Výkon meria trieda `PerformanceMonitor` pomocou `time.perf_counter()`. Záznamy kratšie ako 8 ms alebo dlhšie ako 500 ms boli filtrované ako artefakty.

### Výsledky meraní

| Metrika | PySide6 | wxPython | Kivy |
|---------|---------|----------|------|
| Priemerné FPS – Úroveň 1 | **59.94** | 42.44 | 59.08 |
| Priemerné FPS – Úroveň 2 | **57.86** | 43.08 | 52.42 |
| FPS stabilita – Úroveň 1 | **0.96** | 0.30 | 0.90 |
| FPS stabilita – Úroveň 2 | **0.96** | 0.16 | 0.46 |
| Výpadky snímok – Úroveň 1 | **1.20** | 43.00 | 6.60 |
| Výpadky snímok – Úroveň 2 | **1.60** | 16.40 | 2.20 |
| Latencia vstupu – Úroveň 1 | 29.78 ms | 7.38 ms | **8.14 ms** |
| Latencia vstupu – Úroveň 2 | 53.44 ms | 53.48 ms | **13.52 ms** |
| Spotreba RAM – Úroveň 1 | 367 MB | 345 MB | **329 MB** |
| Spotreba RAM – Úroveň 2 | 409 MB | 380 MB | **300 MB** |

### Porovnanie priemerného FPS

<img src="https://github.com/KV1k1/3D-GUI/blob/main/docs/fps.png">

PySide dosiahol takmer totožné priemerné FPS na oboch úrovniach, čo naznačuje, že framework zvládol záťaž bez degradácie. Kivy zaznamenal na Úrovni 2 výraznejší pokles, čo je konzistentné s vyšším počtom entít. wxPython dosiahol takmer rovnaké priemerné FPS na oboch úrovniach, ale na podstatne nižšej hodnote. 
### Distribúcia FPS (boxplot)

<img src="https://github.com/KV1k1/3D-GUI/blob/main/docs/boxplot.png">

Box plot odhaľuje rozptyl FPS medzi behmi. PySide má úzke boxy na oboch úrovniach, variabilita medzi behmi bola minimálna. Kivy vykazuje väčší rozptyl, čo zodpovedá vyššej štandardnej odchýlke na úrovni 2. WxPython má konzistentne nízky rozptyl FPS, čo by mohlo naznačovať stabilitu, ale v skutočnosti odráža to, že výkon je limitovaný stropom frameworku.
### Výpadky snímok

<img src="https://github.com/KV1k1/3D-GUI/blob/main/docs/vypadok.png">

PySide a Kivy mali na úrovni 2 len pár výpadkov snímok. Naopak, Kivy a najmä wxPython vykazovali na úrovni 1 viac výpadkov, čo je prekvapujúce vzhľadom na to, že ide o jednoduchšiu úroveň s menej entitami. Pravdepodobné vysvetlenie je, že úroveň 1 sa hrala rýchlejšie, s kratším hracím časom, čo spôsobovalo intenzívnejšie záťažové špičky. Na úrovni 2 bol pohyb pomalší a rozložený na dlhší čas, takže výpadkov bolo menej.
### Latencia vstupu

<img src="https://github.com/KV1k1/3D-GUI/blob/main/docs/latencia.png">

Kivy vykazuje najnižšiu a stabilnú latenciu, čo zodpovedá jeho asynchrónnemu spracovaniu vstupov. V PySide sa objavili výnimočne vysoké latencie pravdepodobne v situáciách so súbežne vysokou záťažou. WxPython na ťažšej úrovni má výrazné výkyvy, čo naznačuje, že event loop sa pri záťaži pravidelne preťažuje.

### Spotreba pamäte RAM

<img src="https://github.com/KV1k1/3D-GUI/blob/main/docs/ram">

Kivy má najnižšiu priemernú spotrebu RAM, čo vyplýva z jeho jednoduchej architektúry. PySide a wxPython sú z hľadiska RAM porovnateľné.

### Kvalitatívne hodnotenie

| Metrika | PySide | wxPython | Kivy |
|---------|---------|----------|------|
| Jednoduchosť implementácie | 4/5 | 3/5 | 3/5 |
| Dokumentácia a komunita | 4/5 | 2.5/5 | 3.25/5 |
| Plynulosť animácií a odozva | 5/5 | 3/5 | 4/5 |
| Vizuálny / herný dojem | 5/5 | 3/5 | 4/5 |
| Flexibilita práce s 3D | 5/5 | 3.5/5 | 4/5 |
| **Spolu** | **23/25** | **15/25** | **18.25/25** |

### Celkové hodnotenie

<img src="https://github.com/KV1k1/3D-GUI/blob/main/docs/radar.png">

PySide je dominantný vo výkonnostných metrikách a praktickej použiteľnosti. Kivy drží náskok v RAM efektivite a latencii, ale zaostáva v implementačnej náročnosti. WxPython zaostáva konzistentne naprieč väčšinou osí s výnimkou RAM efektivity.

### Súhrnné bodové hodnotenie

| Metrika | PySide | wxPython | Kivy |
|---------|---------|----------|------|
| Priemerné FPS | 5 | 3 | 4 |
| Stabilita | 5 | 2 | 4 |
| Latencia vstupu | 3 | 2 | 5 |
| RAM efektivita | 3 | 4 | 5 |
| Jednoduchosť implementácie | 4 | 3 | 3 |
| Dokumentácia a komunita | 4 | 2.5 | 3.25 |
| Plynulosť animácií | 5 | 3 | 4 |
| Vizuálny / herný dojem | 5 | 3 | 4 |
| Flexibilita práce s 3D | 5 | 3.5 | 4 |
| **Spolu** | **39** | **26** | **36.25** |

**PySide** sa ukázal ako najvhodnejšia voľba pre 3D herné prostredie v Pythone, kombinujúca vysoký výkon, nízky počet výpadkov a stabilnú prácu s komplexným GUI. **Kivy** dokázal, že moderná shaderová architektúra je realizovateľná, pričom výsledok bol funkčne porovnateľný, ale implementácia si vyžadovala podstatne viac úsilia. **wxPython** umožnil vytvoriť funkčnú 3D aplikáciu, avšak jeho obmedzenia vo výkone a stabilite ho robia menej vhodným pre interaktívne aplikácie v reálnom čase.

---

## Inštalácia a spustenie

### Požiadavky

- Python 3.13
- Nainštalované závislosti: `pip install -r requirements.txt`

### Spustenie jednotlivých verzií

```bash
# PySide6 verzia
python src/pyside/main.py

# wxPython verzia
python src/wxpython/main.py

# Kivy verzia
python src/kivy/main.py
```
---
