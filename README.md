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
-	Aplikácia správne vykresľuje 3D scénu bludiska v reálnom čase, vrátane objektov scény (zbierateľné mince a fragmenty kľúča, nepriatelia, textúry).
-	Pohyb hráča po scéne – bludisku – zabezpečujú klávesy W, A, S, D, pohyb kamery je realizovaný pomocou myši. 
-	Herné mechaniky:
 -	Detekcia kolízií s mincami, ktoré sú po zbere odstránené, aktualizácia skóre hráča.
 -	Aktivácia 3D puzzle minihry pri interakcii hráča s fragmentom kľúča. 
 -	Aktivácia NPC a pohyblivých prekážok po spustení hry -  pohyb NPC po preddefinovaných trasách.
 -	Logika prostredia, ktorá zahŕňa vysúvanie hrotov v stanovených časových intervaloch; platformu s cyklickým pohybom a odomknutie brány po splnení podmienok. 
 -	Detekcia kolízií s nepriateľmi a pascami, po ktorej je zablokovaný pohyb hráča na určitý časový interval. 
 -	 Detekcia interakcie hráča s knihou spustí minihru na kreslenie siluety. Po úspešnom vyriešení minihry sa pohyb hráča opäť aktivuje.
-	HUD zobrazuje počet mincí, fragmentov kľúča, herný čas a minimapu v reálnom čase.
-	Pauzovacie menu musí umožňovať pokračovanie, reštart, výber levelu, uloženie a ukončenie hry.
-	Hra prehráva zvukové efekty pre kroky, zber mince, otváranie brán a kolíziu s duchom v reálnom čase


### Nefunkčné požiadavky
-	Výkon: Pre zabezpečenie plynulosti hry musí aplikácia dosahovať na referenčnom hardvéri minimálne 30 FPS (Frame Per Second).
-	Použiteľnosť: Okamžitá odozva na vstupy z klávesnice a myši, bez výrazného oneskorenia. 
-	Kompatibilita: Aplikácia musí byť spustiteľná na operačných systémoch Windows a Linux bez zmeny zdrojového kódu.
-	Udržateľnosť: Kód musí byť čitateľný, dobre štruktúrovaný a modulárny, herné jadro oddelené od GUI, aby ho bolo možné upravovať a rozširovať.


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

  Implementácia prasovania:
```python
def _parse_maps(self) -> None:
    for r, row in enumerate(self.layout):
        for c, char in enumerate(row):
            if char == '#':
                self.walls.add((r, c))
            elif char in '.SEdJ':
                self.floors.add((r, c))
            if char == 'd':
                self.gate_cells.add((r, c))
            if char == 'S':
                self.start_cells.append((r, c))
            if char == 'E':
                self.exit_cells.append((r, c))

    for r, row in enumerate(self.overlay):
        for c, char in enumerate(row):
            if char in '12345':
                self.ghost_paths.setdefault(int(char), []).append((r, c))
```

### Mince

Systém rozmiestnenia mincí vytvára strategické rozmiestnenie zbierateľných predmetov s týmito prioritami:

1. Umiestnenie mincí do stredových pozícií širokých chodieb
2. Vylúčenie štartovacích/výstupných zón a oblastí brán
3. Zabezpečenie minimálneho rozostupu medzi mincami
4. Vynútenie jednej mince vo väzení

Bunky sú kategorizované podľa geometrie chodby:
```python
total_coins = self.coins_required
center_coins   = min(total_coins // 2, len(center_cells))     # 50% v strede
remaining      = total_coins - center_coins
isolated_coins = min(remaining // 2, len(isolated_cells))     # 25% v izolovaných
edge_coins     = remaining - isolated_coins                    # 25% na okrajoch
```

### FPS kamera
Kamera bola implementovaná ako pohľad z prvej osoby (FPS) s dvoma stupňami voľnosti, kde orientáciu určujú uhly `yaw` (rotácia okolo osi Y) a `pitch` (sklon nahor/nadol). Z týchto uhlov sa vypočíta smer pohľadu a zostaví sa pohľadová matica pomocou konštrukcie look-at:

MVP = P · V · M

kde M je modelová, V pohľadová a P projekčná matica.

Rotácia kamery je riadená pohybom myši aktualizáciou uhlov yaw a pitch:

```python
yaw   += −dx × sensitivity
pitch += −dy × sensitivity
```


kde *dx* a *dy* predstavujú zmenu pozície kurzora v pixeloch a sensitivity určuje citlivosť rotácie.
*PySide6* a *wxPython* podporujú mouse warping, ktorý umožňuje neobmedzenú rotáciu kamery. *Kivy* udáva pozíciu myši so súradnicovým systémom, kde y rastie nahor, takže pri výpočte `pitch` je potrebné invertovať znamienko a *mouse warping* nie je dostupný, čo zastavuje rotáciu pri okraji okna.

### 4.1 Kolízny rádius

Hráč má kolízny rádius **0,30 jednotky**:
```python
def _can_move_to(self, x: float, z: float) -> bool:
    radius = 0.30
    for rr in range(cell_r-1, cell_r+2):
        for cc in range(cell_c-1, cell_c+2):
            if (rr, cc) not in self.walls:
                continue
            minx, maxx = cc, cc+1.0
            minz, maxz = rr, rr+1.0
            dx = max(0.0, minx-x, x-maxx)
            dz = max(0.0, minz-z, z-maxz)
            if dx*dx + dz*dz < radius*radius:
                return False
```

- Efektívna šírka hráča: 0,60 jednotky (2 × 0,30)
- Využiteľná šírka chodby (3 bunky): 3,0 − 0,60 = 2,40 jednotky

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
```python
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
```python
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

| Duch | Veľkosť (jednotky) | Rýchlosť (j./s) | Superschopnosť | Kolízia s hráčom |
|------|--------------|-----------------|----------------|------------------|
| 1 | 2,10 | 2,00 | Obrovský | Hráč je poslaný do väzenia |
| 2 | 1,35 | 3,00 | Prechádza stenami | Hráč je poslaný do väzenia |
| 3 | 1,35 | 1,80 | Základný | Hráč je poslaný späť na štart |
| 4 | 1,35 | 7,00 | Veľmi rýchly | Väzenie + ťažšia minihra |
| 5 | 1,45 | 3,25 | +30 sekúnd k času | Hráč je poslaný do väzenia |

### Minihry

Hra obsahuje dve minihry:

- **3D puzzle** - po zbere fragmentu kľúča; hráč presúva farebné diely šiestimi smermi, kým nezodpovedajú referenčnej zostave. Správnosť sa overuje grafom susednosti:
```python
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
```python
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
| OpenGL profil | Core (po optimalizácii) | Core (po optimalizácii) | Core povinne |
| Načítanie textúr | `QImage` – priamy RGBA buffer | `wx.Image` – 2 samostatné polia, nutná vektorizácia NumPy | `KivyCoreImage` – najjednoduchšie |
| Off-screen kreslenie | `QPainter` na `QImage` | `wx.MemoryDC` na `wx.Bitmap` | `Fbo` – OpenGL framebuffer |
| Modálne dialógy | `QDialog` natívne | `wx.Dialog` natívne | `ModalView` asynchrónne |
| Zvuk | `QSoundEffect` – viackanálový | `wx.adv.Sound` – jednokanálový, nestabilný | `SoundLoader` – plnohodnotný |

---

## Testovanie a výsledky

### Metodika

Pre každý framework bolo vykonaných 5 opakovaní na Úrovni 1 a 5 opakovaní na Úrovni 2. Každé opakovanie predstavovalo kompletné dokončenie úrovne. Pri testovaní bol sledovaný preddefinovaný priebeh, aby sa zabezpečila porovnateľnosť hrania, pričom menšie odchýlky boli nevyhnutné kvôli charakteru hry.
Testovanie prebiehalo na rovnakom hardvéri: AMD Ryzen 5 3600, 16 GB RAM, NVIDIA GeForce GTX 1660 Super, Windows 10.

Výkon meria trieda `PerformanceMonitor`.
Priemerné FPS – aritmetický priemer všetkých platných hodnôt FPS zaznamenaných počas celého behu,
minimálne / maximálne FPS – krajné hodnoty z filtrovanej histórie,
vstupová latencia – medián času medzi doručením udalosti frameworkom a aplikáciou zmeny stavu,
využitie pamäte – maximálna hodnota RAM v megabajtoch počas behu,
čas štartu – doba od inicializácie po prvú vykreslenú snímku v milisekundách,
čas načítania textúr – doba inicializácie herných assetov pri štarte,
priemerný čas generovania textových textúr – priemerná doba vytvárania textových nápisov v milisekundách.


### PySide6 — Úroveň 1
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 48,7 | 61,0 | 60,9 | 60,4 | 48,9 | **55,98** |
| Minimálne FPS | 29,9 | 28,0 | 29,7 | 28,8 | 42,8 | **31,84** |
| Maximálne FPS | 71,2 | 91,2 | 84,9 | 91,4 | 87,7 | **85,28** |
| Medián latencie (ms) | 16,59 | 16,53 | 16,59 | 16,55 | 16,51 | **16,55** |
| RAM (MB) | 430,9 | 274,3 | 370,0 | 270,2 | 388,5 | **346,78** |
| Štart (ms) | 534,7 | 557,9 | 565,4 | 585,5 | 568,3 | **562,36** |
| Textúry (ms) | 842,4 | 850,3 | 838,3 | 854,5 | 854,4 | **847,96** |
| Text (ms) | 0,25 | 0,25 | 0,26 | 0,25 | 0,26 | **0,25** |
 
Priemerné FPS sa pohybovalo medzi 48,7 a 61,0, pričom nižšie hodnoty v behoch 1 a 5 môžu súvisieť s interným bufferovaním Qt6. Variabilita spotreby RAM v rozsahu 270–431 MB naznačuje podobný jav. Medián latencie vstupu bol vo všetkých piatich behoch takmer identický (16,51–16,59 ms), čo zodpovedá architektúre QTimer s intervalom 16 ms.

### PySide6 — Úroveň 2
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 57,8 | 57,8 | 56,6 | 57,5 | 58,1 | **57,56** |
| Minimálne FPS | 28,3 | 29,5 | 43,8 | 41,6 | 31,3 | **34,90** |
| Maximálne FPS | 74,6 | 72,5 | 64,3 | 90,7 | 93,9 | **79,20** |
| Medián latencie (ms) | 16,80 | 28,63 | 19,42 | 21,70 | 29,10 | **23,13** |
| RAM (MB) | 356,7 | 361,6 | 275,6 | 277,8 | 272,5 | **308,84** |
| Štart (ms) | 540,2 | 535,4 | 559,4 | 545,3 | 564,7 | **549,00** |
| Textúry (ms) | 825,1 | 840,5 | 835,1 | 869,3 | 829,1 | **839,83** |
| Text (ms) | 0,23 | 0,23 | 0,24 | 0,23 | 0,22 | **0,23** |
 
Priemerné FPS bolo na druhej úrovni výrazne konzistentnejšie naprieč behmi (56,6–58,1) ako na prvej úrovni. Variabilita latencie vstupu (16,8–29,1 ms) je konzistentná s architektúrou QTimer(16 ms) — odozva závisí od fázy časovača v momente stlačenia klávesy.
 
---
 
### Kivy — Úroveň 1
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 60,2 | 60,1 | 60,0 | 60,5 | 60,0 | **60,16** |
| Minimálne FPS | 29,8 | 29,6 | 57,7 | 22,2 | 58,3 | **39,52** |
| Maximálne FPS | 77,8 | 91,4 | 62,4 | 83,2 | 61,5 | **75,26** |
| Medián latencie (ms) | 0,11 | 0,08 | 0,10 | 0,11 | 0,10 | **0,10** |
| RAM (MB) | 272,2 | 210,0 | 295,0 | 259,1 | 235,2 | **254,30** |
| Štart (ms) | 19,2 | 76,4 | 71,6 | 80,5 | 75,6 | **64,66** |
| Textúry (ms) | 202,8 | 220,4 | 195,7 | 200,1 | 202,2 | **204,24** |
| Text (ms) | 1,45 | 0,98 | 1,38 | 2,32 | 1,07 | **1,44** |
 
Priemerné FPS bolo vo všetkých piatich behoch takmer totožné (60,0–60,5). Minimálne FPS vykazovalo väčšiu variabilitu (22,2–58,3), čo pravdepodobne odráža nepravidelnosť streamingových bufferov pri inicializácii úrovne, nie počas samotného hrania. Čas štartu v behu 1 (19,2 ms) je výrazne nižší ako v ostatných behoch (71–81 ms), čo možno pripísať zahriateju cache operačného systému.
 
### Kivy — Úroveň 2
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 55,3 | 51,5 | 56,8 | 50,1 | 52,3 | **53,20** |
| Minimálne FPS | 29,9 | 27,8 | 29,8 | 35,1 | 29,9 | **30,50** |
| Maximálne FPS | 63,8 | 64,5 | 66,3 | 62,8 | 63,6 | **64,20** |
| Medián latencie (ms) | 0,12 | 0,12 | 0,11 | 0,11 | 0,12 | **0,12** |
| RAM (MB) | 236,6 | 218,6 | 218,6 | 218,7 | 214,5 | **221,40** |
| Štart (ms) | 78,9 | 79,2 | 78,3 | 84,0 | 80,0 | **80,08** |
| Textúry (ms) | 228,0 | 194,9 | 203,7 | 198,9 | 197,5 | **204,60** |
| Text (ms) | 1,23 | 0,96 | 1,63 | 6,95 | 1,06 | **2,37** |

 Priemerné FPS mierne pokleslo oproti prvej úrovni (50,1–56,8), čo zodpovedá väčšej scéne s vyšším počtom entít. Čas generovania textových textúr bol v behu 4 výrazne vyšší (6,95 ms oproti mediánu 1,23 ms), čo pravdepodobne súvisí s pauzou garbage collectora počas generovania textúry.
 
---
 
### wxPython — Úroveň 1
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 39,6 | 43,3 | 38,8 | 40,0 | 39,4 | **40,22** |
| Minimálne FPS | 14,0 | 21,7 | 20,1 | 21,3 | 21,6 | **19,74** |
| Maximálne FPS | 80,6 | 72,6 | 82,7 | 79,6 | 79,3 | **78,96** |
| Medián latencie (ms) | 0,53 | 0,75 | 14,73 | 0,46 | 7,43 | **4,78** |
| RAM (MB) | 231,8 | 320,1 | 275,7 | 274,2 | 291,5 | **278,66** |
| Štart (ms) | 2 889,2 | 3 095,9 | 2 902,1 | 2 880,7 | 2 912 | **2 935,98** |
| Textúry (ms) | 1 307,74 | 1 317,3 | 1 312,7 | 1 305,1 | 1 299,6 | **1 308,47** |
| Text (ms) | 0,61 | 0,50 | 0,63 | 0,68 | 0,48 | **0,58** |
 
Minimálne FPS v behu 1 dosiahlo hodnotu 14,0, čo je výrazne nižšie ako v ostatných behoch (20,1–21,7). Vyššia latencia vstupu v behoch 3 (14,73 ms) a 5 (7,43 ms) pravdepodobne súvisí s dočasným prerušením natívnej Win32 udalostnej slučky systémovými udalosťami. Čas štartu bol vo všetkých behoch výrazne vyšší ako u ostatných frameworkov, pohyboval sa v rozsahu 2 880–3 096 ms.
 
### wxPython — Úroveň 2
 
| Metrika | Beh 1 | Beh 2 | Beh 3 | Beh 4 | Beh 5 | Priemer |
|---|---|---|---|---|---|---|
| Priemerné FPS | 41,5 | 41,1 | 40,3 | 42,2 | 40,9 | **41,20** |
| Minimálne FPS | 21,5 | 21,0 | 21,4 | 22,1 | 21,6 | **21,52** |
| Maximálne FPS | 70,7 | 67,8 | 69,1 | 69,4 | 69,6 | **69,32** |
| Medián latencie (ms) | 0,58 | 0,58 | 0,64 | 0,62 | 0,66 | **0,62** |
| RAM (MB) | 299 | 326,9 | 296,9 | 285 | 285,9 | **298,74** |
| Štart (ms) | 3 270,2 | 2 944,7 | 2 913 | 2 913,4 | 2 975,7 | **3 003,40** |
| Textúry (ms) | 1 379,14 | 1 298,39 | 1 280,13 | 1 287,5 | 1 281,46 | **1 305,32** |
| Text (ms) | 0,48 | 0,50 | 0,48 | 0,49 | 0,49 | **0,49** |

Na druhej úrovni boli výsledky wxPython stabilnejšie ako na prvej — priemerné FPS sa pohybovalo v rozsahu 40,3–42,2 a latencia vstupu bola konzistentná (0,58–0,66 ms). Čas štartu zostal vysoký (2 913–3 270 ms), pričom beh 1 bol mierne odľahlý oproti ostatným.

---

Textúry použité pre brány, minimapu a platformy sú vlastnou tvorbou. Textúry pre podlahu, steny a mince pochádzajú z bezplatných zdrojov dostupných na platforme Freepik. Zvukové efekty použité v projekte boli získané z databázy Freesound.

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
