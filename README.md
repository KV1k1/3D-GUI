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


---

## Architektúra riešenia

Kľúčovým architektonickým rozhodnutím je striktné oddelenie herného jadra od renderovacích adaptérov. Tento návrh vychádza z princípu MVC (Model-View-Controller), kde herné jadro predstavuje model, adaptéry frameworkov zastrešujú view a controller. Každý adaptér dostane identické herné jadro a testuje sa iba jeho schopnosť poskytovať vizualizačné a vstupné rozhranie.

Modul `core/game_core.py` neobsahuje žiadny import z GUI frameworkov. Trieda `GameCore` komunikuje s adaptérmi výlučne cez systém udalostí – adaptér zaregistruje funkcie pre udalosti ako `coin_picked`, `gate_opened`, `game_won`, a jadro ich vyvolá v správnom momente.

<img src="https://github.com/KV1k1/3D-GUI/blob/main/docs/package_diagram.png">


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

## FPS kamera
Kamera bola implementovaná ako pohľad z prvej osoby (FPS) s dvoma stupňami voľnosti, kde orientáciu určujú uhly `yaw` (rotácia okolo osi Y) a `pitch` (sklon nahor/nadol). Z týchto uhlov sa vypočíta smer pohľadu a zostaví sa pohľadová matica pomocou konštrukcie look-at:

MVP = P · V · M

kde M je modelová, V pohľadová a P projekčná matica.

Rotácia kamery je riadená pohybom myši aktualizáciou uhlov yaw a pitch:

```
yaw   += −dx × sensitivity
pitch += −dy × sensitivity
```


kde *dx* a *dy* predstavujú zmenu pozície kurzora v pixeloch a sensitivity určuje citlivosť rotácie.

*PySide6* a *wxPython* podporujú *mouse warping*, ktorý umožňuje neobmedzenú rotáciu kamery, zatiaľ čo Kivy používa odlišný súradnicový systém (y rastie nahor), takže sa pri výpočte `pitch` používa opačné znamienko a *mouse warping* nie je dostupný, čo spôsobuje zastavenie rotácie pri okraji okna.

### Načítanie textúr
Každý framework poskytuje iný mechanizmus na prípravu obrazových dát pre OpenGL.

*PySide* poskytuje triedu `QImage` s priamou podporou formátu `RGBA8888`. Po konverzii je pixel buffer dostupný a dá sa priamo odovzdať `glTexImage2D`:

```python
img = QImage(path).convertToFormat(QImage.Format_RGBA8888)
w, h = img.width(), img.height()
ptr = img.bits()
data = bytes(ptr[:w * h * 4])

tex_id = glGenTextures(1)
glBindTexture(GL_TEXTURE_2D, tex_id)
glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0,
             GL_RGBA, GL_UNSIGNED_BYTE, data)
return int(tex_id)
```

**wxPython** ukladá RGB a alpha kanál do dvoch samostatných polí. Ich zlúčenie si vyžadovalo vektorizáciu pomocou NumPy, pretože slučka v čistom Pythone bola príliš pomalá na načítanie textúr pri štarte.

**Kivy** má najjednoduchšie načítanie – `KivyCoreImage` interně nahrá textúru do GPU. Keďže Kivy používa vlastný OpenGL kontext a Core Profile, bolo potrebné vytvoriť samostatný GL handle pre PyOpenGL:

```python
img = KivyCoreImage(path)
pixels = img.texture.pixels  # CPU kópia pixelov z internej Kivy textúry
w, h = img.texture.size

tex = GL.glGenTextures(1)
GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, w, h,
                0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, pixels)
```

### Minimapa

Hráč má kedykoľvek k dispozícii minimapu, ktorú otvorí klávesou `M` alebo kliknutím na ikonu kamery v rohu obrazovky. Minimapa funguje ako 2D prekrytie vykreslené priamo na hernom okne každú snímku. Základom je prevedenie súradníc hernej mriežky na súradnice obrazovky:

```python
# Každá bunka sa zobrazí ako farebný štvorček
for r in range(maze_rows):
    for c in range(maze_cols):
        rx, ry = to_screen(r, c)  # herná bunka → pixely na obrazovke
        if (r, c) in self.core.walls:
            painter.fillRect(rx, ry, ..., QColor(45, 45, 55))    # stena
        elif (r, c) in self.core.floors:
            painter.fillRect(rx, ry, ..., QColor(125, 125, 135)) # chodba

# Poloha hráča
pr, pc = int(self.core.player.z), int(self.core.player.x)
px, py = to_screen(pr + 0.5, pc + 0.5)
painter.drawPolygon(...)  # zelený diamant

# Mince a duchovia
for coin in self.core.coins.values():
    if not coin.taken:
        painter.drawEllipse(...)  # zlatý kruh

for ghost in self.core.ghosts.values():
    painter.drawEllipse(...)  # farebný kruh s očami
```


Keď hráč skončí vo väzení, na stene väzenskej cely sa zobrazí mapa celého labyrintu so sektormi pre orientáciu. Mapa sa generuje raz a uloží ako GPU textúra. Implementácia závisí od frameworku:
Frameworky *PySide6* a *wxPython* ponúkajú plnohodnotný off-screen kresliaci kontext (`QPainter` / `wx.MemoryDC`) umožňuje vykresliť farebné oblasti a písmená sektora do `QImage` / `wx.Bitmap` a následne nahrať do GPU:
```
#PySide QPainter
img = QImage(640, 420, QImage.Format_RGBA8888)
img.fill(QColor(50, 42, 36, 255))
p = QPainter(img)
for r in range(grid_h):
    for c in range(grid_w):
        col = palette.get(sector_id_for_cell((r, c)))
        if col:
            p.fillRect(...)  # bunka vyplnená farbou sektora
p.setFont(QFont('Arial', 52, QFont.Bold))
for sid, centroid in centroids.items():
    p.drawText(..., sid[:1])  # sektorové písmená na centroidoch
p.end()
ptr  = img.constBits()
data = ptr.tobytes()[:size]  # pixel buffer pre GPU
# nahranie do GPU...
```
Kivy natívny 2D kresliaci kontext mimo obrazovky neponúka, avšak disponuje triedou Fbo (Framebuffer Object), ktorá umožňuje off-screen OpenGL renderovanie:
```
fbo = Fbo(size=(640, 420), with_depthbuffer=False)
with fbo:
    ClearColor(0.196, 0.165, 0.141, 1.0)  # pozadie
    ClearBuffers()
    Color(0.314, 0.471, 0.784)  # farba sektora A
    Rectangle(pos=(x, y), size=(cell+1, cell+1))  # bunka s prekrytím aby okraje neboli viditeľné
    # ... sektorové písmená cez CoreLabel ...
pixels = fbo.pixels  # RGBA data
```
### Geometria herného sveta

Spočiatku sa steny vykresľovali v immediate mode. Každú snímku sa geometria posielala z CPU do GPU znova. Na Úrovni 2 s väčším bludiskom to viedlo k 12-18 snímkam za sekundu. Riešením bol prechod na **Vertex Buffer Objects (VBO)**. Celá statická geometria stien a podláh sa nahrala do pamäte GPU jednorazovo pri inicializácii.

Kivy vyžaduje OpenGL ES 2.0 Core Profile, ktorý nepodporuje immediate mode ani `GL_QUADS`, preto každý štvorec musel byť rozdelený na dva trojuholníky a všetka geometria sa zostavuje do streaming bufferov. Tento prístup bol následne aplikovaný aj na PySide6 a wxPython pre dynamické entity, aby porovnanie nebolo zaujaté rozdielom OpenGL profilov.

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

- **3D puzzle** - po zbere fragmentu kľúča; hráč presúva farebné diely šiestimi smermi, kým nezodpovedajú referenčnej zostave. Správnosť sa overuje grafom susednosti:
```
def neighbors_from_positions(positions):
    adj = {i: set() for i in range(len(positions))}
    ipos = [np.round(p).astype(int) for p in positions]
    for i in range(len(ipos)):
        for j in range(i + 1, len(ipos)):
            diff = np.abs(ipos[i] - ipos[j])
            # Susedia = líšia sa presne o 1 v jednej osi
            if (np.sum(diff == 1) == 1) and (np.sum(diff == 0) == 2):
                adj[i].add(j); adj[j].add(i)
    return adj

correct = all(placed_adj[i] == target_adj[i] for i in range(len(target)))[
```
- **Silhouette puzzle** - vo väzení po chytení duchom; hráč kliknutím na mriežku 6×6 reprodukuje referenčný tvar.
```
  def _check(self):
    current = [[1 if self._cells[r][c].isChecked() else 0
                for c in range(self._size)]
               for r in range(self._size)]
    if current == self._target:
        self.accept()[
```

V *PySide* a *wxPython* sú minihry implementované ako natívne modálne dialógy. Kivy natívne modálne okná nepodporuje, preto minihry sú implementované ako `FloatLayout` prekrytia.

### Zvuk

PySide6 a Kivy poskytujú plnohodnotné viackanálové zvukové rozhranie (`QSoundEffect`, `SoundLoader`).

wxPython disponuje iba jednokanálovým `wx.adv.Sound`. Aby sa prioritné zvuky (brána, duch) nevynechali, bol implementovaný systém, ktorý kroky dočasne preruší a po ich skončení ich obnoví na hlavnom vlákne cez `wx.CallLater`:

```python
def _play_priority_sfx(self, snd, *, cooldown_s):
    self._stop_footsteps()
    self._sfx_until = time.perf_counter() + cooldown_s
    snd.Play(wx.adv.SOUND_ASYNC)
    wx.CallLater(int(cooldown_s * 1000), self._resume_footsteps_if_needed)

def _resume_footsteps_if_needed(self):
    if not self._footsteps_requested:
        return
    if time.perf_counter() < self._sfx_until:
        return   # iný zvuk predĺžil okno
    if not self._footsteps_playing:
        self._start_footsteps_loop()
```

Napriek tomuto riešeniu zvuk v wxPython zostal nestabilný – pri niektorých behoch sa zvuky krokov prestali prehrávať bez zjavného dôvodu. `wx.adv.Sound` je tenká vrstva nad systémovým zvukovým rozhraním bez vlastného bufferovania či chybovej obnovy.

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

Pre každý framework bolo vykonaných 5 opakovaní na Úrovni 1 a 5 opakovaní na Úrovni 2. Každé opakovanie predstavovalo kompletné dokončenie úrovne. Pri testovaní bol sledovaný preddefinovaný priebeh, aby sa zabezpečila porovnateľnosť hrania, pričom menšie odchýlky boli nevyhnutné kvôli charakteru hry.
Testovanie prebiehalo na rovnakom hardvéri: AMD Ryzen 5 3600, 16 GB RAM, NVIDIA GeForce GTX 1660 Super, Windows 10.

Výkon meria trieda `PerformanceMonitor`.
Priemerné FPS – aritmetický priemer všetkých platných hodnôt FPS zaznamenaných počas celého behu,
minimálne / maximálne FPS – krajné hodnoty z filtrovanej histórie,
vstupová latencia – medián času medzi doručením udalosti frameworkom a aplikáciou zmeny stavu; filtrované hodnoty nad 500 ms,
využitie pamäte – maximálna hodnota RAM v megabajtoch počas behu,
čas štartu – doba od inicializácie po prvú vykreslenú snímku v milisekundách,
čas načítania textúr – doba inicializácie herných assetov pri štarte,
priemerný čas generovania textových textúr – priemerná doba vytvárania textových nápisov v milisekundách.


### PySide6 — Úroveň 1
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 48,7 | 61,0 | 60,9 | 60,4 | 48,9 | **56,0** |
| Minimálne FPS | 29,9 | 28,0 | 29,7 | 28,8 | 42,8 | **31,8** |
| Maximálne FPS | 71,2 | 91,2 | 84,9 | 91,4 | 87,7 | **85,3** |
| Medián latencie (ms) | 16,59 | 16,53 | 16,59 | 16,55 | 16,51 | **16,6** |
| RAM (MB) | 430,9 | 274,3 | 370,0 | 270,2 | 388,5 | **346,8** |
| Štart (ms) | 534,7 | 557,9 | 565,4 | 585,5 | 568,3 | **562,4** |
| Textúry (ms) | 842,4 | 850,3 | 838,3 | 854,5 | 854,4 | **848,0** |
| Text (ms) | 0,25 | 0,25 | 0,26 | 0,25 | 0,26 | **0,25** |
 
**Poznámka k RAM:** Variabilita 270–431 MB súvisí s interným bufferovaním Qt6.
### PySide6 — Úroveň 2
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 57,8 | 57,8 | 56,6 | 57,5 | 58,1 | **57,6** |
| Minimálne FPS | 28,3 | 29,5 | 43,8 | 41,6 | 31,3 | **34,9** |
| Maximálne FPS | 74,6 | 72,5 | 64,3 | 90,7 | 93,9 | **79,2** |
| Medián latencie (ms) | 16,80 | 28,63 | 19,42 | 21,70 | 29,10 | **23,1** |
| RAM (MB) | 356,7 | 361,6 | 275,6 | 277,8 | 272,5 | **308,8** |
| Štart (ms) | 540,2 | 535,4 | 559,4 | 545,3 | 564,7 | **549,0** |
| Textúry (ms) | 825,1 | 840,5 | 835,1 | 869,3 | 829,1 | **839,8** |
| Text (ms) | 0,23 | 0,23 | 0,24 | 0,23 | 0,22 | **0,23** |
 
**Poznámka k latencii:** Variabilita 16,8–29,1 ms je konzistentná s architektúrou
QTimer(16 ms) — závisí od fázy časovača v momente stlačenia klávesy.
 
---
 
### Kivy — Úroveň 1
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 60,2 | 60,1 | 60,0 | 60,5 | 60,0 | **60,2** |
| Minimálne FPS | 29,8 | 29,6 | 57,7 | 22,2 | 58,3 | **39,5** |
| Maximálne FPS | 77,8 | 91,4 | 62,4 | 83,2 | 61,5 | **75,3** |
| Medián latencie (ms) | 0,11 | 0,08 | 0,10 | 0,11 | 0,10 | **0,10** |
| RAM (MB) | 272,2 | 210,0 | 295,0 | 259,1 | 235,2 | **254,3** |
| Štart (ms) | 19,2 | 76,4 | 71,6 | 80,5 | 75,6 | **64,7** |
| Textúry (ms) | 202,8 | 220,4 | 195,7 | 200,1 | 202,2 | **204,2** |
| Text (ms) | 1,45 | 0,98 | 1,38 | 2,32 | 1,07 | **1,44** |
 
**Poznámka k štartu:** Beh 1 (19,2 ms) je odľahlý — pravdepodobne zahriatá cache
OS. Priemer behov 2–5 je 76 ms.
 
**Poznámka k min FPS:** Variabilita (22–58 FPS) odráža nepravidelnosť streamingových
bufferov pri inicializácii úrovne, nie počas hrania.
 
### Kivy — Úroveň 2
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 55,3 | 51,5 | 56,8 | 50,1 | 52,3 | **53,2** |
| Minimálne FPS | 29,9 | 27,8 | 29,8 | 35,1 | 29,9 | **30,5** |
| Maximálne FPS | 63,8 | 64,5 | 66,3 | 62,8 | 63,6 | **64,2** |
| Medián latencie (ms) | 0,12 | 0,12 | 0,11 | 0,11 | 0,12 | **0,12** |
| RAM (MB) | 236,6 | 218,6 | 218,6 | 218,7 | 214,5 | **221,4** |
| Štart (ms) | 78,9 | 79,2 | 78,3 | 84,0 | 80,0 | **80,1** |
| Textúry (ms) | 228,0 | 194,9 | 203,7 | 198,9 | 197,5 | **204,6** |
| Text (ms) | 1,23 | 0,96 | 1,63 | 6,95 | 1,06 | **2,37** |
 
**Poznámka k textu:** Hodnota 6,95 ms v behu 4 je odľahlý výsledok —
pravdepodobne GC pauza počas generovania textúry. Medián piatich behov je 1,23 ms.
 
---
 
### wxPython — Úroveň 1
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 39,6 | 43,3 | 38,8 | 40,0 | 39,4 | **40,2** |
| Minimálne FPS | 14,0 | 21,7 | 20,1 | 21,3 | 21,6 | **19,7** |
| Maximálne FPS | 80,6 | 72,6 | 82,7 | 79,6 | 79,3 | **79,0** |
| Medián latencie (ms) | 0,53 | 0,75 | 14,73 | 0,46 | 7,43 | **4,78** |
| RAM (MB) | 231,8 | 320,1 | 275,7 | 274,2 | 291,5 | **278,7** |
| Štart (ms) | 2 889 | 3 096 | 2 902 | 2 881 | 2 912 | **2 936** |
| Textúry (ms) | 1 307,7 | 1 317,3 | 1 312,7 | 1 305,1 | 1 299,6 | **1 308,5** |
| Text (ms) | 0,61 | 0,50 | 0,63 | 0,68 | 0,48 | **0,58** |
 
**Poznámka k latencii:** Behy 3 (14,73 ms) a 5 (7,43 ms) sú odľahlé hodnoty
spôsobené prerušením natívnej Win32 udalostnej slučky systémovými udalosťami.
Medián piatich behov je 0,75 ms. Priemer 4,78 ms je zavádzajúci — lepšie
reprezentuje typické správanie medián.
 
**Poznámka k min FPS:** Beh 1 dosiahol minimum 14,0 FPS — výrazne nižšie ako
ostatné behy. Príčina nebola identifikovaná; pravdepodobne systémová záťaž.
 
### wxPython — Úroveň 2
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 41,5 | 41,1 | 40,3 | 42,2 | 40,9 | **41,2** |
| Minimálne FPS | 21,5 | 21,0 | 21,4 | 22,1 | 21,6 | **21,5** |
| Maximálne FPS | 70,7 | 67,8 | 69,1 | 69,4 | 69,6 | **69,3** |
| Medián latencie (ms) | 0,58 | 0,58 | 0,64 | 0,62 | 0,66 | **0,62** |
| RAM (MB) | 299,0 | 326,9 | 296,9 | 285,0 | 285,9 | **298,7** |
| Štart (ms) | 3 270 | 2 945 | 2 913 | 2 913 | 2 976 | **3 003** |
| Textúry (ms) | 1 379,1 | 1 298,4 | 1 280,1 | 1 287,5 | 1 281,5 | **1 305,3** |
| Text (ms) | 0,48 | 0,50 | 0,48 | 0,49 | 0,49 | **0,49** |

**PySide** sa ukázal ako najvhodnejšia voľba pre 3D herné prostredie v Pythone, kombinujúca vysoký výkon, nízky počet výpadkov a stabilnú prácu s komplexným GUI. **Kivy** dokázal, že moderná shaderová architektúra je realizovateľná, pričom výsledok bol funkčne porovnateľný, ale implementácia si vyžadovala podstatne viac úsilia. **wxPython** umožnil vytvoriť funkčnú 3D aplikáciu, avšak jeho obmedzenia vo výkone a stabilite ho robia menej vhodným pre interaktívne aplikácie v reálnom čase.

---

## Inštalácia a spustenie

### Požiadavky

- Python 3.13
- Nainštalované závislosti: `pip install -r requirements.txt`

### Spustenie jednotlivých verzií

```bash
# PySide6 verzia
run_pyside6.py

# wxPython verzia
run_wxpython.py

# Kivy verzia
run_kivy.py
```
---
