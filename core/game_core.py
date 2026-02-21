import math
import json
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import random

from core.map_data import CELLAR_LAYOUT, CELLAR_OVERLAY, LEVEL_DEFS


@dataclass(frozen=True)
class Vec2:
    x: float
    z: float


@dataclass
class Player:
    x: float
    y: float
    z: float
    yaw: float = 0.0
    pitch: float = 0.0


@dataclass
class Coin:
    cell: Tuple[int, int]
    taken: bool = False


@dataclass
class KeyFragment:
    id: str
    cell: Tuple[int, int]
    taken: bool = False
    kind: str = "K"


@dataclass
class Spike:
    cell: Tuple[int, int]
    active: bool
    timer: float
    period: float


@dataclass
class Ghost:
    id: int
    path_cells: List[Tuple[int, int]]
    speed: float
    x: float
    z: float
    yaw: float
    forward: bool = True
    target_index: int = 0
    size_scale: float = 1.0
    speed_mult: float = 1.0
    collision_radius: float = 0.75
    can_phase_walls: bool = False
    time_penalty_s: float = 0.0


@dataclass
class CheckpointArrow:
    cell: Tuple[int, int]
    visible: bool = False
    bob_offset: float = 0.0
    bob_phase: float = 0.0


@dataclass
class Gate:
    id: str
    cells: List[Tuple[int, int]]
    locked: bool
    y_offset: float = 0.0
    lowering: bool = False
    raising: bool = False
    close_delay_timer: float = 0.0
    opened_from_inside: Optional[bool] = None
    opened_timer: float = 0.0


@dataclass
class SpikeField:
    cells: Set[Tuple[int, int]]
    phase: float = 0.0
    cycle_s: float = 3.2
    rise_s: float = 0.6
    hold_s: float = 0.6
    fall_s: float = 0.6
    down_s: float = 1.4

    def height_factor(self) -> float:
        t = self.phase % self.cycle_s
        if t < self.rise_s:
            return t / self.rise_s
        t -= self.rise_s
        if t < self.hold_s:
            return 1.0
        t -= self.hold_s
        if t < self.fall_s:
            return 1.0 - (t / self.fall_s)
        return 0.0


@dataclass
class Platform:
    cell: Tuple[int, int]
    y_offset: float = 0.0
    target_y: float = 0.0
    speed: float = 0.8
    moving_up: bool = False
    moving_down: bool = False
    wait_timer: float = 0.0
    cycle_time: float = 0.0

    bottom_height: float = 0.0
    top_height: float = 2.5
    wait_at_top: float = 1.0
    wait_at_bottom: float = 1.5

    def update(self, dt: float) -> None:
        """Update platform position based on cycle"""
        self.cycle_time += dt

        total_cycle = self.wait_at_bottom + \
            (self.top_height / self.speed) + \
            self.wait_at_top + (self.top_height / self.speed)
        phase = self.cycle_time % total_cycle

        if phase < self.wait_at_bottom:
            self.target_y = self.bottom_height
            self.moving_up = False
            self.moving_down = False
        elif phase < self.wait_at_bottom + (self.top_height / self.speed):
            self.moving_up = True
            self.moving_down = False
            progress = (phase - self.wait_at_bottom) / \
                (self.top_height / self.speed)
            self.target_y = self.bottom_height + (self.top_height * progress)
        elif phase < self.wait_at_bottom + (self.top_height / self.speed) + self.wait_at_top:
            self.target_y = self.top_height
            self.moving_up = False
            self.moving_down = False
        else:
            self.moving_up = False
            self.moving_down = True
            down_progress = (phase - self.wait_at_bottom - (self.top_height /
                             self.speed) - self.wait_at_top) / (self.top_height / self.speed)
            self.target_y = self.top_height - (self.top_height * down_progress)

        if abs(self.y_offset - self.target_y) > 0.01:
            direction = 1 if self.target_y > self.y_offset else -1
            self.y_offset += direction * self.speed * dt
            ceiling_height = 2.8
            self.y_offset = min(self.y_offset, ceiling_height)
            self.y_offset = max(self.bottom_height, min(
                self.top_height, self.y_offset))


class GameCore:
    def __init__(self, level_id: str = 'level2'):
        self._event_callbacks: Dict[str, List[Callable[[dict], None]]] = {}

        self.level_id = str(level_id or 'level2')
        level_def = LEVEL_DEFS.get(
            self.level_id) or LEVEL_DEFS.get('level2') or {}

        self.layout = level_def.get('layout') or CELLAR_LAYOUT
        self.overlay = level_def.get('overlay') or CELLAR_OVERLAY
        self._sector_grid_level = level_def.get('sectors')
        self.enabled_ghost_ids = list(level_def.get(
            'enabled_ghost_ids') or [1, 2, 3, 4, 5])

        self.height = len(self.layout)
        self.width = max((len(row) for row in self.layout), default=0)

        self.walls: Set[Tuple[int, int]] = set()
        self.floors: Set[Tuple[int, int]] = set()
        self.gate_cells: Set[Tuple[int, int]] = set()
        self.start_cells: List[Tuple[int, int]] = []
        self.exit_cells: List[Tuple[int, int]] = []

        self.ghost_paths: Dict[int, List[Tuple[int, int]]] = {
            i: [] for i in range(1, 6)}
        self._key_cells: Dict[str, Tuple[int, int]] = {}
        self._spike_seed_cells: Set[Tuple[int, int]] = set()

        self.ghost_abilities: Dict[int, dict] = {
            1: {'size_scale': 2.10, 'speed_mult': 1.0, 'collision_radius': 1.35, 'can_phase_walls': False, 'time_penalty_s': 0.0},
            2: {'size_scale': 1.35, 'speed_mult': 1.05, 'collision_radius': 0.95, 'can_phase_walls': True, 'time_penalty_s': 0.0},
            3: {'size_scale': 1.35, 'speed_mult': 1.0, 'collision_radius': 0.95, 'can_phase_walls': False, 'time_penalty_s': 0.0},
            4: {'size_scale': 1.35, 'speed_mult': 1.85, 'collision_radius': 1.00, 'can_phase_walls': False, 'time_penalty_s': 0.0},
            5: {'size_scale': 1.45, 'speed_mult': 1.10, 'collision_radius': 1.05, 'can_phase_walls': False, 'time_penalty_s': 30.0},
        }

        self._parse_maps()

        spawn = self._pick_spawn_cell()
        self.player = Player(x=spawn[1] + 0.5, y=0.5, z=spawn[0] + 0.5)

        self.wall_height = 4.5
        self.ceiling_height = self.wall_height

        self.coins_required = int(level_def.get('coins_required') or 80)
        self.keys_required = int(level_def.get('keys_required') or 3)
        self.coins: Dict[Tuple[int, int], Coin] = {}
        self.key_fragments: Dict[str, KeyFragment] = {}
        self.coins_collected = 0
        self.keys_collected = 0

        self.in_jail = False
        self.paused = False
        self.game_won = False
        self.game_completed = False
        self.screen_closing = False
        self.screen_close_progress = 0.0
        self.elapsed_s = 0.0

        self.jail_spawn_cell: Optional[Tuple[int, int]] = None
        self.jail_book_cell: Optional[Tuple[int, int]] = None
        self.jail_inside_cells: Set[Tuple[int, int]] = set()
        self.jail_outside_cells: Set[Tuple[int, int]] = set()

        self.gates: Dict[str, Gate] = {}

        self.checkpoint_arrow: Optional[CheckpointArrow] = None

        self.jail_entries = 0
        self.coin_collection_times = []
        self.last_coin_time = 0.0

        self.spikes: List[Spike] = []
        self.platforms: List[Platform] = []
        self._spike_phase: float = 0.0
        self._spike_cycle_s: float = 4.0
        self._spike_rise_s: float = 0.6
        self._spike_hold_s: float = 0.6
        self._spike_fall_s: float = 0.6

        self._pending_key_fragment_id: Optional[str] = None
        self._ignored_key_fragment_ids: Set[str] = set()

        self.ghosts: Dict[int, Ghost] = {}
        self._init_runtime_entities()
        self._init_jail_room_points()

        self.sector_cols = 4
        self.sector_rows = 2
        self.sector_signs: Dict[str, Tuple[Tuple[int, int], str]] = {}
        self.exit_sector_id: str = ''
        self._sector_grid: Optional[List[str]] = None
        self._sector_filled: Dict[Tuple[int, int], str] = {}
        self.jail_painting: Optional[Tuple[Tuple[int, int], str]] = None
        self.current_sector_id: str = ''
        self._sector_popup_timer: float = 0.0
        self._sector_popup_id: str = ''
        self._init_sectors()

        if 'start' in self.gates:
            self.open_gate('start')

    def _pick_spawn_cell(self) -> Tuple[int, int]:
        # Prefer a walkable cell adjacent to the start marker.
        if self.start_cells:
            sr, sc = self.start_cells[0]
            for nb in ((sr, sc + 1), (sr, sc - 1), (sr + 1, sc), (sr - 1, sc)):
                if nb in self.floors and nb not in self.walls:
                    return nb
            if (sr, sc) in self.floors and (sr, sc) not in self.walls:
                return (sr, sc)

        # Fallback: first available walkable floor.
        for cell in sorted(self.floors):
            if cell not in self.walls:
                return cell
        return (1, 1)

    def _parse_maps(self) -> None:
        for r, row in enumerate(self.layout):
            for c in range(self.width):
                ch = row[c]
                if ch == '#':
                    self.walls.add((r, c))
                else:
                    self.floors.add((r, c))

                if ch == 'S':
                    self.start_cells.append((r, c))
                elif ch == 'E':
                    self.exit_cells.append((r, c))
                elif ch == 'd':
                    self.gate_cells.add((r, c))

        overlay_width = self.width
        for r, row in enumerate(self.overlay):
            for c in range(overlay_width):
                ch = row[c]
                if ch in '12345':
                    self.ghost_paths[int(ch)].append((r, c))

        for r, row in enumerate(self.overlay):
            c = 0
            while c < overlay_width:
                def chars(n: int) -> str:
                    return row[c:c + n]

                if chars(2) == 'KH':
                    self._key_cells['kh'] = (r, c)
                    self._spike_seed_cells.add((r, c))
                    c += 2
                    continue
                if chars(2) == 'KP':
                    self._key_cells['kp'] = (r, c)
                    c += 2
                    continue
                ch = row[c]
                if ch == 'K':
                    self._key_cells['k'] = (r, c)
                    c += 1
                    continue
                c += 1

    def _init_runtime_entities(self) -> None:
        self._spawn_coins()
        self._spawn_key_fragments()
        self._init_gates()
        self._init_spikes()
        self._init_ghosts()

    def sector_id_for_cell(self, cell: Tuple[int, int]) -> str:
        r, c = cell
        sid = self._sector_filled.get(cell)
        if sid:
            return sid
        if self._sector_grid is not None:
            if 0 <= r < len(self._sector_grid) and 0 <= c < len(self._sector_grid[r]):
                ch = self._sector_grid[r][c]
                if 'A' <= ch <= 'H':
                    return ch
        return ''

    def _init_sectors(self) -> None:
        self._sector_grid = None
        self._sector_filled = {}
        if isinstance(getattr(self, '_sector_grid_level', None), list):
            grid = getattr(self, '_sector_grid_level', None)
            if grid and all(isinstance(r, str) for r in grid):
                self._sector_grid = grid
        if self._sector_grid is None:
            try:
                from core import map_data as _md
                grid = getattr(_md, 'CELLAR_SECTORS', None)
                if isinstance(grid, list) and grid and all(isinstance(r, str) for r in grid):
                    self._sector_grid = grid
            except Exception:
                self._sector_grid = None

        # Fill unlabeled walkable cells (e.g. jail interior spaces) from nearest labeled sector.
        if self._sector_grid is not None:
            from collections import deque

            q = deque()
            seen: Set[Tuple[int, int]] = set()
            for r in range(min(self.height, len(self._sector_grid))):
                row = self._sector_grid[r]
                for c in range(min(self.width, len(row))):
                    ch = row[c]
                    if 'A' <= ch <= 'H':
                        cell = (r, c)
                        if cell in self.floors and cell not in self.walls:
                            q.append(cell)
                            seen.add(cell)

            while q:
                r, c = q.popleft()
                src = self._sector_grid[r][c]
                if 'A' <= src <= 'H':
                    src_sid = src
                else:
                    src_sid = self._sector_filled.get((r, c), '')
                if not src_sid:
                    continue

                for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    cell = (nr, nc)
                    if cell in seen:
                        continue
                    if cell not in self.floors or cell in self.walls:
                        continue
                    ch = ''
                    if 0 <= nr < len(self._sector_grid) and 0 <= nc < len(self._sector_grid[nr]):
                        ch = self._sector_grid[nr][nc]
                    if 'A' <= ch <= 'H':
                        seen.add(cell)
                        q.append(cell)
                        continue
                    self._sector_filled[cell] = src_sid
                    seen.add(cell)
                    q.append(cell)

        if self.exit_cells:
            self.exit_sector_id = self.sector_id_for_cell(
                self.exit_cells[len(self.exit_cells) // 2])
        else:
            self.exit_sector_id = self.sector_id_for_cell(
                (self.height - 1, self.width - 1))

        def facing_for_offset(dr: int, dc: int) -> str:
            if dr == -1:
                return 'N'
            if dr == 1:
                return 'S'
            if dc == -1:
                return 'W'
            return 'E'

        def pick_wall_sign_for_sector(sid: str) -> Optional[Tuple[Tuple[int, int], str]]:
            candidates: List[Tuple[Tuple[int, int], str]] = []
            for (r, c) in self.floors:
                if (r, c) in self.walls:
                    continue
                if self.sector_id_for_cell((r, c)) != sid:
                    continue
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    wr, wc = r + dr, c + dc
                    if (wr, wc) in self.walls:
                        candidates.append(((r, c), facing_for_offset(dr, dc)))
                        break
            if not candidates:
                return None
            candidates.sort(key=lambda x: (x[0][0], x[0][1]))
            return candidates[len(candidates) // 2]

        self.sector_signs = {}
        for sid in 'ABCDEFGH':
            picked = pick_wall_sign_for_sector(sid)
            if picked:
                self.sector_signs[sid] = picked

        # Jail painting: mount inside jail on a wall near the jail book.
        self.jail_painting = None

        def pick_jail_wall_anchor() -> Optional[Tuple[Tuple[int, int], str]]:
            if not self.jail_inside_cells:
                return None
            cr = sum(r for r, _ in self.jail_inside_cells) / \
                len(self.jail_inside_cells)
            cc = sum(c for _, c in self.jail_inside_cells) / \
                len(self.jail_inside_cells)
            best: Optional[Tuple[float, Tuple[int, int], str]] = None

            def wall_run_margins(wr: int, wc: int, facing: str) -> Tuple[int, int]:
                # Returns how many contiguous wall cells exist on each side of (wr,wc)
                # along the wall direction.
                neg = 0
                pos = 0
                if facing in ('N', 'S'):
                    cc2 = wc - 1
                    while (wr, cc2) in self.walls:
                        neg += 1
                        cc2 -= 1
                    cc2 = wc + 1
                    while (wr, cc2) in self.walls:
                        pos += 1
                        cc2 += 1
                else:
                    rr2 = wr - 1
                    while (rr2, wc) in self.walls:
                        neg += 1
                        rr2 -= 1
                    rr2 = wr + 1
                    while (rr2, wc) in self.walls:
                        pos += 1
                        rr2 += 1
                return neg, pos

            for r, c in self.jail_inside_cells:
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    wr, wc = r + dr, c + dc
                    if (wr, wc) not in self.walls:
                        continue
                    facing = facing_for_offset(dr, dc)

                    # Avoid placing the painting near corners by requiring a long enough
                    # continuous wall segment and a little margin from its endpoints.
                    neg, pos = wall_run_margins(wr, wc, facing)
                    run_len = 1 + neg + pos
                    if run_len < 4:
                        continue
                    if min(neg, pos) < 1:
                        continue

                    dist2 = (r - cr) ** 2 + (c - cc) ** 2
                    score = dist2
                    if best is None or score < best[0]:
                        best = (score, (r, c), facing)
            if best is None:
                return None
            return best[1], best[2]

        self.jail_painting = pick_jail_wall_anchor()

        # Initialize current sector from player spawn.
        self.current_sector_id = self.sector_id_for_cell(
            (int(self.player.z), int(self.player.x)))
        self._sector_popup_id = self.current_sector_id
        self._sector_popup_timer = 0.0

    def _spawn_coins(self) -> None:
        """Center-prioritized distribution for 3-block wide paths"""
        # Get all valid floor cells (excluding specific gate areas)
        valid_cells = []

        # Create targeted exclusion zones for specific gate areas only
        exclusion_zones = set()

        # Add exact gate cells and immediate adjacent cells only
        for start_cell in self.start_cells:
            exclusion_zones.add(start_cell)
            # Only add immediate adjacent cells (1-cell radius)
            for dr in range(-1, 2):
                for dc in range(-1, 2):
                    adjacent = (start_cell[0] + dr, start_cell[1] + dc)
                    exclusion_zones.add(adjacent)

        for exit_cell in self.exit_cells:
            exclusion_zones.add(exit_cell)
            # Level 1: exclude a larger area around the exit so coins never spawn near it.
            # ("10 blocks from E" interpreted as a 10-cell Chebyshev radius.)
            radius = 10 if str(getattr(self, 'level_id', '')
                               ) == 'level1' else 1
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    exclusion_zones.add((exit_cell[0] + dr, exit_cell[1] + dc))

        # Add all gate cells to exclusion
        for gate_cell in self.gate_cells:
            exclusion_zones.add(gate_cell)

        # Collect valid cells and categorize by path width
        center_cells = []  # Block 2 (middle) in 3-block wide paths
        edge_cells = []    # Blocks 1 and 3 (edges) in paths

        for cell in self.floors:
            if cell in exclusion_zones:
                continue

            r, c = cell

            # Check if this is a center block in a 3-block wide path
            # A cell is in the center if it has floor cells on both sides in at least one direction
            is_center_horizontal = False
            is_center_vertical = False

            # Check horizontal center (left and right are both floor)
            left_cell = (r, c - 1)
            right_cell = (r, c + 1)
            if left_cell in self.floors and right_cell in self.floors:
                if left_cell not in self.walls and right_cell not in self.walls:
                    # Check if this forms a 3-block wide path
                    left_left = (r, c - 2)
                    right_right = (r, c + 2)
                    if ((left_left in self.floors and left_left not in self.walls) or
                            (right_right in self.floors and right_right not in self.walls)):
                        is_center_horizontal = True

            # Check vertical center (up and down are both floor)
            up_cell = (r - 1, c)
            down_cell = (r + 1, c)
            if up_cell in self.floors and down_cell in self.floors:
                if up_cell not in self.walls and down_cell not in self.walls:
                    # Check if this forms a 3-block wide path
                    up_up = (r - 2, c)
                    down_down = (r + 2, c)
                    if ((up_up in self.floors and up_up not in self.walls) or
                            (down_down in self.floors and down_down not in self.walls)):
                        is_center_vertical = True

            # Categorize cell
            if is_center_horizontal or is_center_vertical:
                center_cells.append(cell)
            else:
                edge_cells.append(cell)

        # Sort cells for systematic distribution
        center_cells.sort()
        edge_cells.sort()

        # Calculate coin allocation - prioritize center cells
        total_coins = self.coins_required
        center_coins = min(total_coins * 2 // 3,
                           len(center_cells))  # ~2/3 in center
        edge_coins = total_coins - center_coins

        # Select coins from center cells first
        selected_coins: List[Tuple[int, int]] = []

        def pick_spaced(candidates: List[Tuple[int, int]], count: int, min_sep: float, rng: random.Random) -> List[Tuple[int, int]]:
            if count <= 0 or not candidates:
                return []
            shuffled = list(candidates)
            rng.shuffle(shuffled)
            picked: List[Tuple[int, int]] = []
            min_sep2 = min_sep * min_sep
            for cell in shuffled:
                if len(picked) >= count:
                    break
                if all(((cell[0] - pr) ** 2 + (cell[1] - pc) ** 2) >= min_sep2 for (pr, pc) in picked):
                    picked.append(cell)
            if len(picked) < count:
                remaining = [c for c in shuffled if c not in picked]
                picked.extend(remaining[: max(0, count - len(picked))])
            return picked

        rng = random.Random(1337)
        if center_cells and center_coins > 0:
            selected_coins.extend(pick_spaced(
                center_cells, center_coins, min_sep=6.0, rng=rng))
        if edge_cells and edge_coins > 0:
            selected_coins.extend(pick_spaced(
                edge_cells, edge_coins, min_sep=5.0, rng=rng))

        # Special handling for jail room - ensure 1-2 coins there
        jail_coins_added = 0
        jail_gate = self.gates.get('jail')
        if jail_gate and self.jail_spawn_cell:
            # Check if jail spawn area already has coins
            jail_area = set()
            for gate_cell in jail_gate.cells:
                for dr in range(-2, 3):  # 5x5 area around jail gate
                    for dc in range(-2, 3):
                        nearby = (gate_cell[0] + dr, gate_cell[1] + dc)
                        if nearby in self.floors and nearby not in exclusion_zones:
                            jail_area.add(nearby)

            # Count existing coins in jail area
            existing_jail_coins = [
                cell for cell in selected_coins if cell in jail_area]

            # If no coins in jail, add 1-2
            if len(existing_jail_coins) == 0 and jail_area:
                # Add jail spawn cell if available
                if self.jail_spawn_cell in jail_area:
                    # Replace a random coin with jail spawn coin
                    if selected_coins:
                        replace_index = rng.randint(0, len(selected_coins) - 1)
                        selected_coins[replace_index] = self.jail_spawn_cell
                        jail_coins_added = 1
                # Add second coin if space allows
                if len(jail_area) > 1 and len(selected_coins) < total_coins:
                    other_jail_cells = list(jail_area - {self.jail_spawn_cell})
                    if other_jail_cells:
                        selected_coins.append(other_jail_cells[0])
                        jail_coins_added = 2

        # Ensure we have exactly the required number of coins
        selected_coins = selected_coins[:total_coins]

        # Create coin objects
        self.coins = {cell: Coin(cell=cell, taken=False)
                      for cell in selected_coins}

    def _spawn_key_fragments(self) -> None:
        regular = self._key_cells.get('k')
        kh = self._key_cells.get('kh')
        kp = self._key_cells.get('kp')

        candidates: List[KeyFragment] = []
        if kh is not None:
            candidates.append(KeyFragment(id='frag_kh', cell=kh, kind='KH'))
        if regular is not None:
            candidates.append(KeyFragment(id='frag_k', cell=regular, kind='K'))
        if kp is not None:
            candidates.append(KeyFragment(id='frag_kp', cell=kp, kind='KP'))

        spawned = 0
        for frag in candidates:
            if spawned >= max(0, int(self.keys_required)):
                break
            self.key_fragments[frag.id] = frag
            if frag.kind == 'KP':
                self.platforms.append(Platform(cell=frag.cell))
            spawned += 1

    def _init_gates(self) -> None:
        # Group contiguous 'd' into gate spans.
        remaining = set(self.gate_cells)
        groups: List[List[Tuple[int, int]]] = []
        while remaining:
            start = next(iter(remaining))
            stack = [start]
            group: List[Tuple[int, int]] = []
            remaining.remove(start)
            while stack:
                cell = stack.pop()
                group.append(cell)
                r, c = cell
                for nb in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                    if nb in remaining:
                        remaining.remove(nb)
                        stack.append(nb)
            groups.append(sorted(group))

        def center_of(cells: List[Tuple[int, int]]) -> Tuple[float, float]:
            r = sum(x for x, _ in cells) / len(cells)
            c = sum(y for _, y in cells) / len(cells)
            return r, c

        # Identify start/exit gates by proximity.
        start_ref = self.start_cells[0] if self.start_cells else (0, 0)
        if self.exit_cells:
            exit_ref = self.exit_cells[len(self.exit_cells) // 2]
        else:
            exit_ref = (self.height - 1, self.width - 1)

        best_start = None
        best_exit = None
        best_start_d = 1e9
        best_exit_d = 1e9

        # Check each gate group for start/exit assignment
        for g in groups:
            gr, gc = center_of(g)
            ds = (gr - start_ref[0]) ** 2 + (gc - start_ref[1]) ** 2
            de = (gr - exit_ref[0]) ** 2 + (gc - exit_ref[1]) ** 2
            if ds < best_start_d:
                best_start_d = ds
                best_start = g
            if de < best_exit_d:
                best_exit_d = de
                best_exit = g

        # Note: previously we tried to aggregate "all gate cells near the exit".
        # That caused the exit gate to be composed of multiple separated parts.
        # For stable layout behavior, pick a single contiguous group as the exit gate.

        # Jail gate is the remaining group with the largest span (ddd at jail corridor).
        jail_group = None
        for g in groups:
            if g is best_start or g is best_exit:
                continue
            if jail_group is None or len(g) > len(jail_group):
                jail_group = g

        if best_start:
            self.gates['start'] = Gate(
                id='start', cells=best_start, locked=False)
        if jail_group:
            self.gates['jail'] = Gate(id='jail', cells=jail_group, locked=True)
        if best_exit:
            # Start locked, drop when requirements met
            self.gates['exit'] = Gate(id='exit', cells=best_exit, locked=True)

    def _init_spikes(self) -> None:
        # test2-style spikes: individual spike tiles with independent timers.
        self.spikes = []
        if not self._spike_seed_cells:
            return
        rng = random.Random(2026)
        for (sr, sc) in self._spike_seed_cells:
            for dr in range(-1, 2):
                for dc in range(-2, 3):
                    r = sr + dr
                    c = sc + dc
                    if (r, c) in self.floors and (r, c) not in self.walls:
                        if (r, c) in self.start_cells:
                            continue
                        self.spikes.append(
                            Spike(cell=(r, c), active=False,
                                  timer=rng.random() * 2.0, period=3.0)
                        )

    def _init_ghosts(self) -> None:
        # Per-ghost speeds (reduced for slower movement)
        # Reduced from 3.0, 3.5, 2.8, 3.2, 3.8
        speeds = {1: 2.0, 2: 2.5, 3: 1.8, 4: 2.2, 5: 2.8}
        for gid, path in self.ghost_paths.items():
            if gid not in set(self.enabled_ghost_ids):
                continue
            if not path:
                continue
            abilities = self.ghost_abilities.get(gid, {})

            # Filter to walkable cells only (prevents routing through walls if overlay is misaligned).
            # If the ghost can phase walls, allow wall cells as waypoints too.
            if bool(abilities.get('can_phase_walls', False)):
                filtered = list(path)
            else:
                filtered = [
                    cell for cell in path if cell in self.floors and cell not in self.walls]
            if len(filtered) < 2:
                continue

            path_sorted = self._order_adjacent_path(filtered, loop=(gid != 5))
            if len(path_sorted) < 2:
                continue
            r0, c0 = path_sorted[0]
            tr, tc = path_sorted[1]
            yaw0 = math.atan2((tc + 0.5 - (c0 + 0.5)), (tr + 0.5 - (r0 + 0.5)))
            self.ghosts[gid] = Ghost(
                id=gid,
                path_cells=path_sorted,
                speed=speeds.get(gid, 1.5),
                x=c0 + 0.5,
                z=r0 + 0.5,
                yaw=yaw0,
                forward=True,
                target_index=1 if len(path_sorted) > 1 else 0,
                size_scale=float(abilities.get('size_scale', 1.0) or 1.0),
                speed_mult=float(abilities.get('speed_mult', 1.0) or 1.0),
                collision_radius=float(abilities.get(
                    'collision_radius', 0.75) or 0.75),
                can_phase_walls=bool(abilities.get('can_phase_walls', False)),
                time_penalty_s=float(abilities.get(
                    'time_penalty_s', 0.0) or 0.0),
            )

    def _init_jail_room_points(self) -> None:
        gate = self.gates.get('jail')
        if not gate:
            return

        outside = self._reachable_from_start_with_locked_gates()
        self.jail_outside_cells = set(outside)

        # Classify "inside jail" as floors that are not reachable from start with gates locked.
        # This is intentionally conservative and only used for gate auto-close behavior.
        self.jail_inside_cells = {
            cell for cell in self.floors if cell not in self.walls and cell not in outside}

        gr = int(round(sum(r for r, _ in gate.cells) / len(gate.cells)))
        gc = int(round(sum(c for _, c in gate.cells) / len(gate.cells)))

        best_inside = None
        for rad in range(1, 30):
            for r in range(gr - rad, gr + rad + 1):
                for c in range(gc - rad, gc + rad + 1):
                    cell = (r, c)
                    if cell in self.floors and cell not in self.walls and cell not in self.gate_cells and cell not in outside:
                        best_inside = cell
                        break
                if best_inside:
                    break
            if best_inside:
                break

        # Fall back if we can't classify: still pick something near gate.
        if best_inside is None:
            for rad in range(1, 30):
                for r in range(gr - rad, gr + rad + 1):
                    for c in range(gc - rad, gc + rad + 1):
                        cell = (r, c)
                        if cell in self.floors and cell not in self.walls and cell not in self.gate_cells:
                            best_inside = cell
                            break
                    if best_inside:
                        break
                if best_inside:
                    break

        self.jail_spawn_cell = best_inside

        if best_inside:
            br, bc = best_inside
            for nb in ((br, bc + 1), (br, bc - 1), (br + 1, bc), (br - 1, bc)):
                if nb in self.floors and nb not in self.walls and nb not in self.gate_cells and nb not in outside:
                    self.jail_book_cell = nb
                    break
            if self.jail_book_cell is None:
                self.jail_book_cell = best_inside

    def _reachable_from_start_with_locked_gates(self) -> Set[Tuple[int, int]]:
        """Cells reachable from the start area assuming currently locked gates are blocked."""
        start = self._pick_spawn_cell()
        if start not in self.floors or start in self.walls:
            return set()
        q = [start]
        seen: Set[Tuple[int, int]] = {start}
        locked_gate_cells: Set[Tuple[int, int]] = set()
        for gate in self.gates.values():
            if gate.locked:
                locked_gate_cells.update(gate.cells)

        while q:
            r, c = q.pop()
            for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                cell = (nr, nc)
                if cell in seen:
                    continue
                if cell in self.walls:
                    continue
                if cell in locked_gate_cells:
                    continue
                if cell not in self.floors:
                    continue
                seen.add(cell)
                q.append(cell)
        return seen

    def _order_adjacent_path(self, cells: List[Tuple[int, int]], loop: bool) -> List[Tuple[int, int]]:
        """Order a set of grid cells into a contiguous path by following 4-neighbor adjacency.

        - For loop paths: start at lexicographically smallest cell and walk until we return.
        - For non-loop paths: start at an endpoint (degree==1) and walk to the other end.
        """
        cell_set = set(cells)
        if not cell_set:
            return []

        def neighbors(cell: Tuple[int, int]) -> List[Tuple[int, int]]:
            r, c = cell
            nbs = [(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
            return [nb for nb in nbs if nb in cell_set]

        degrees: Dict[Tuple[int, int], int] = {
            cell: len(neighbors(cell)) for cell in cell_set}

        start: Tuple[int, int]
        if loop:
            start = min(cell_set)
        else:
            endpoints = [cell for cell, deg in degrees.items() if deg == 1]
            start = min(endpoints) if endpoints else min(cell_set)

        ordered: List[Tuple[int, int]] = [start]
        prev: Optional[Tuple[int, int]] = None
        current = start

        # Walk until we cannot continue or we visited all cells.
        while len(ordered) < len(cell_set):
            nbs = neighbors(current)
            # Prefer continuing forward (not going back to prev)
            candidates = [nb for nb in nbs if nb != prev]
            if not candidates:
                break
            # In rare intersections (degree>2), pick a deterministic next cell
            nxt = min(candidates)
            prev = current
            current = nxt
            ordered.append(current)

        # If loop, ensure path is cyclic by keeping it as-is; movement logic wraps.
        return ordered

    def _init_checkpoint_arrow(self) -> None:
        """Initialize checkpoint arrow - will be spawned when exit gate opens"""
        pass

    def _update_checkpoint_arrow(self, dt: float) -> None:
        """Update checkpoint arrow bobbing animation and check hitbox"""
        if self.checkpoint_arrow and self.checkpoint_arrow.visible:
            # Update bobbing animation
            self.checkpoint_arrow.bob_phase += dt * 2.0  # Bob speed
            self.checkpoint_arrow.bob_offset = math.sin(
                self.checkpoint_arrow.bob_phase) * 0.1

            # Check if player is in arrow hitbox (more forgiving)
            arrow_r, arrow_c = self.checkpoint_arrow.cell
            player_r, player_c = int(self.player.z), int(self.player.x)

            # Check if player is at or near arrow cell (within 1.5 block radius)
            distance = math.sqrt((player_r - arrow_r) **
                                 2 + (player_c - arrow_c)**2)
            if distance <= 1.5:  # Within 1.5 block radius (more forgiving)
                if not self.game_completed and not self.screen_closing:
                    self.game_completed = True
                    self.screen_closing = True
                    self.screen_close_progress = 0.0
                    self._trigger_event('checkpoint_reached', {
                                        'time_s': self.elapsed_s})

    def _update_screen_close(self, dt: float) -> None:
        if not self.screen_closing:
            return
        self.screen_close_progress += dt * 0.5  # 2 seconds to close
        if self.screen_close_progress >= 1.0:
            self.screen_close_progress = 1.0
            self.game_won = True  # End the game after animation

    def update(self, dt: float) -> None:
        if self.game_won:
            return
        if getattr(self, 'paused', False):
            return
        self.elapsed_s += dt

        if self._sector_popup_timer > 0.0:
            self._sector_popup_timer = max(0.0, self._sector_popup_timer - dt)

        self._update_spikes(dt)
        self._update_gates(dt)
        self._update_ghosts(dt)
        self._check_collectibles()
        self._check_hazards()
        self._check_exit_condition()
        # Simple proximity-based jail gate control
        self._check_jail_gate_proximity(dt)
        self._update_platforms(dt)
        self._update_checkpoint_arrow(dt)
        self._update_screen_close(dt)

        sid = self.sector_id_for_cell((int(self.player.z), int(self.player.x)))
        if sid and sid != self.current_sector_id:
            self.current_sector_id = sid
            self._sector_popup_id = sid
            self._sector_popup_timer = 2.0
            self._trigger_event('sector_entered', {'id': sid})

    def get_save_state(self) -> dict:
        coins_taken = [f"{r},{c}" for (
            r, c), coin in self.coins.items() if coin.taken]
        frags_taken = [fid for fid,
                       frag in self.key_fragments.items() if frag.taken]
        gates = {}
        for gid, gate in self.gates.items():
            gates[gid] = {
                'locked': bool(gate.locked),
                'y_offset': float(gate.y_offset),
                'lowering': bool(gate.lowering),
                'raising': bool(gate.raising),
            }
        return {
            'version': 1,
            'player': {
                'x': float(self.player.x),
                'y': float(self.player.y),
                'z': float(self.player.z),
                'yaw': float(self.player.yaw),
                'pitch': float(self.player.pitch),
            },
            'elapsed_s': float(self.elapsed_s),
            'coins_collected': int(self.coins_collected),
            'keys_collected': int(self.keys_collected),
            'coins_taken': coins_taken,
            'key_fragments_taken': frags_taken,
            'in_jail': bool(self.in_jail),
            'jail_entries': int(self.jail_entries),
            'gates': gates,
        }

    def load_save_state(self, state: dict) -> bool:
        if not isinstance(state, dict):
            return False
        player = state.get('player')
        if not isinstance(player, dict):
            return False

        self.player.x = float(player.get('x', self.player.x))
        self.player.y = float(player.get('y', self.player.y))
        self.player.z = float(player.get('z', self.player.z))
        self.player.yaw = float(player.get('yaw', self.player.yaw))
        self.player.pitch = float(player.get('pitch', self.player.pitch))

        self.elapsed_s = float(state.get('elapsed_s', self.elapsed_s))
        self.coins_collected = int(
            state.get('coins_collected', self.coins_collected))
        self.keys_collected = int(
            state.get('keys_collected', self.keys_collected))
        self.in_jail = bool(state.get('in_jail', self.in_jail))
        self.jail_entries = int(state.get('jail_entries', self.jail_entries))

        coins_taken = set(str(x) for x in (state.get('coins_taken') or []))
        for (r, c), coin in self.coins.items():
            coin.taken = f"{r},{c}" in coins_taken

        frags_taken = set(str(x)
                          for x in (state.get('key_fragments_taken') or []))
        for fid, frag in self.key_fragments.items():
            frag.taken = fid in frags_taken

        gates = state.get('gates')
        if isinstance(gates, dict):
            for gid, gstate in gates.items():
                gate = self.gates.get(str(gid))
                if gate is None or not isinstance(gstate, dict):
                    continue
                gate.locked = bool(gstate.get('locked', gate.locked))
                gate.y_offset = float(gstate.get('y_offset', gate.y_offset))
                gate.lowering = bool(gstate.get('lowering', gate.lowering))
                gate.raising = bool(gstate.get('raising', gate.raising))

        self._refresh_sector_state(show_popup=False)
        return True

    def _update_gates(self, dt: float) -> None:
        speed = 1.5  # Reduced from 3.0 for much slower gate movement
        for gate in self.gates.values():
            if gate.lowering:
                gate.y_offset = max(-self.wall_height,
                                    gate.y_offset - speed * dt)
                if gate.y_offset <= -self.wall_height + 1e-3:
                    gate.lowering = False
            elif gate.raising:
                gate.y_offset = min(0.0, gate.y_offset + speed * dt)
                if gate.y_offset >= -1e-3:
                    gate.raising = False

    def _check_jail_gate_proximity(self, dt: float) -> None:
        """Jail gate control.

        Keep the jail gate open until the player has crossed to the other side.
        This prevents soft-locking the player inside the jail area.
        """
        jail_gate = self.gates.get('jail')
        if not jail_gate:
            return

        # Only manage auto-close when gate is fully open (lowered).
        if jail_gate.locked or jail_gate.raising or jail_gate.lowering:
            jail_gate.opened_from_inside = None
            jail_gate.opened_timer = 0.0
            return

        player_cell = (int(self.player.z), int(self.player.x))

        # Determine which side the player started on when the gate opened.
        if jail_gate.opened_from_inside is None:
            jail_gate.opened_from_inside = player_cell in self.jail_inside_cells
            jail_gate.opened_timer = 0.0

        jail_gate.opened_timer += dt

        # If the gate was opened while the player was inside, keep it open until they reach the outside.
        if jail_gate.opened_from_inside:
            if player_cell in self.jail_outside_cells:
                self.close_gate('jail')
                jail_gate.opened_from_inside = None
                jail_gate.opened_timer = 0.0
            return

        # If opened from outside, close it once the player leaves the immediate gate area.
        near_gate = any(
            abs(player_cell[0] - gate_cell[0]
                ) <= 1 and abs(player_cell[1] - gate_cell[1]) <= 1
            for gate_cell in jail_gate.cells
        )
        if not near_gate:
            self.close_gate('jail')
            jail_gate.opened_from_inside = None
            jail_gate.opened_timer = 0.0

    def _update_platforms(self, dt: float) -> None:
        """Update all elevator platforms"""
        player_on_any_platform = False

        for platform in self.platforms:
            platform.update(dt)

            # Check if player is on this platform and move them with it
            player_cell = (int(self.player.z), int(self.player.x))
            if player_cell == platform.cell:
                # Player is on the platform cell, check if they're at the right height
                player_y = self.player.y
                platform_top = platform.y_offset + 0.1  # Small platform thickness

                # Check if player is actually standing on platform surface
                px, pz = self.player.x, self.player.z
                platform_center_x = platform.cell[1] + 0.5
                platform_center_z = platform.cell[0] + 0.5
                platform_radius = 0.4  # Platform radius

                # Only stick to platform if player is within platform bounds
                if (abs(px - platform_center_x) < platform_radius and
                        abs(pz - platform_center_z) < platform_radius):
                    # Player is on platform surface, stick them to it
                    if abs(player_y - platform_top) < 0.3:
                        self.player.y = platform_top
                        player_on_any_platform = True
                else:
                    # Player walked off platform, reset to ground level
                    self.player.y = 0.0

        # If player is not on any platform but has height > 0, reset to ground
        if not player_on_any_platform and self.player.y > 0.1:
            self.player.y = 0.0

    def open_gate(self, gate_id: str) -> None:
        gate = self.gates.get(gate_id)
        if not gate:
            return
        gate.locked = False
        gate.lowering = True
        gate.raising = False
        self._trigger_event('gate_opened', {'gate_id': gate_id})

    def close_gate(self, gate_id: str) -> None:
        gate = self.gates.get(gate_id)
        if not gate:
            return
        gate.locked = True
        gate.lowering = False
        gate.raising = True
        self._trigger_event('gate_closed', {'gate_id': gate_id})

    def _update_ghosts(self, dt: float) -> None:
        for ghost in self.ghosts.values():
            if len(ghost.path_cells) < 2:
                continue
            tr, tc = ghost.path_cells[ghost.target_index]
            tx = tc + 0.5
            tz = tr + 0.5
            dx = tx - ghost.x
            dz = tz - ghost.z
            dist = math.hypot(dx, dz)
            if dist < 1e-6:
                dist = 1e-6
            step = (ghost.speed * ghost.speed_mult) * dt
            if dist <= step:
                ghost.x = tx
                ghost.z = tz
                self._advance_ghost_target(ghost)
            else:
                ghost.x += (dx / dist) * step
                ghost.z += (dz / dist) * step

            # Face actual movement direction (or next waypoint if we snapped)
            ntr, ntc = ghost.path_cells[ghost.target_index]
            ntx = ntc + 0.5
            ntz = ntr + 0.5
            vdx = ntx - ghost.x
            vdz = ntz - ghost.z
            if abs(vdx) < 1e-6 and abs(vdz) < 1e-6:
                vdx = dx
                vdz = dz
            ghost.yaw = math.atan2(vdx, vdz)

            # Collision check
            if self._distance_xz(ghost.x, ghost.z, self.player.x, self.player.z) < float(getattr(ghost, 'collision_radius', 0.75) or 0.75):
                penalty = float(getattr(ghost, 'time_penalty_s', 0.0) or 0.0)
                if penalty > 0.0:
                    self.elapsed_s += penalty
                    self._trigger_event(
                        'time_penalty', {'seconds': int(round(penalty))})
                self._send_to_jail('ghost')

    def _advance_ghost_target(self, ghost: Ghost) -> None:
        n = len(ghost.path_cells)
        if ghost.id == 5:
            # Ping-pong
            if ghost.forward:
                if ghost.target_index >= n - 1:
                    ghost.forward = False
                    ghost.target_index = max(0, n - 2)
                else:
                    ghost.target_index += 1
            else:
                if ghost.target_index <= 0:
                    ghost.forward = True
                    ghost.target_index = 1 if n > 1 else 0
                else:
                    ghost.target_index -= 1
        else:
            ghost.target_index = (ghost.target_index + 1) % n

    def _update_spikes(self, dt: float) -> None:
        if not self.spikes:
            return
        self._spike_phase = (self._spike_phase + dt) % self._spike_cycle_s
        t = self._spike_phase
        if t < self._spike_rise_s:
            active = False
        elif t < (self._spike_rise_s + self._spike_hold_s):
            active = True
        elif t < (self._spike_rise_s + self._spike_hold_s + self._spike_fall_s):
            active = True
        else:
            active = False
        for s in self.spikes:
            s.active = active

    def spike_height_factor(self) -> float:
        t = self._spike_phase
        if t < self._spike_rise_s:
            return t / self._spike_rise_s
        t -= self._spike_rise_s
        if t < self._spike_hold_s:
            return 1.0
        t -= self._spike_hold_s
        if t < self._spike_fall_s:
            return 1.0 - (t / self._spike_fall_s)
        return 0.0

    def _check_collectibles(self) -> None:
        cell = (int(self.player.z), int(self.player.x))
        coin = self.coins.get(cell)
        if coin and not coin.taken:
            coin.taken = True
            self.coins_collected += 1

            # Track coin collection time
            current_time = self.elapsed_s
            if self.last_coin_time > 0:
                collection_time = current_time - self.last_coin_time
                self.coin_collection_times.append(collection_time)
            self.last_coin_time = current_time

            self._trigger_event('coin_picked', {'count': self.coins_collected})

        # Key fragments: auto-trigger minigame on touch (test2-style). The UI decides success.
        if self._pending_key_fragment_id is None:
            for frag in self.key_fragments.values():
                if frag.taken:
                    continue
                if frag.id in self._ignored_key_fragment_ids:
                    r, c = frag.cell
                    fx = c + 0.5
                    fz = r + 0.5
                    if self._distance_xz(self.player.x, self.player.z, fx, fz) > 0.65:
                        self._ignored_key_fragment_ids.discard(frag.id)
                    continue
                r, c = frag.cell
                fx = c + 0.5
                fz = r + 0.5

                # Check distance to fragment
                # KP should only trigger when you're actually near the platform/fragment, not from below.
                pickup_r = 0.50 if frag.kind == 'KP' else 0.55
                if self._distance_xz(self.player.x, self.player.z, fx, fz) < pickup_r:
                    # For KP fragments, only trigger if platform is moving AND player is standing on platform
                    if frag.kind == 'KP':
                        # Find the platform at this location
                        player_on_platform = False
                        platform_near_top = False
                        for platform in self.platforms:
                            if platform.cell == (r, c):
                                # Check if player is standing on platform (within platform bounds)
                                px, pz = self.player.x, self.player.z
                                platform_center_x = c + 0.5
                                platform_center_z = r + 0.5
                                # Platform radius (for pickup comfort)
                                platform_radius = 0.55

                                # Check if player is within platform bounds (standing on it)
                                if (abs(px - platform_center_x) < platform_radius and
                                    abs(pz - platform_center_z) < platform_radius and
                                        abs(self.player.y - platform.y_offset) < 0.75):  # Require being near platform height
                                    player_on_platform = True

                                # Beginner-friendly: the fragment should only trigger when the platform is near its top.
                                # This prevents instant trigger when you first step on (platform is usually at the bottom).
                                platform_near_top = platform.y_offset >= (
                                    platform.top_height - 0.45)
                                break

                        if (not player_on_platform) or (not platform_near_top):
                            continue

                    # Trigger the fragment
                    self._pending_key_fragment_id = frag.id
                    self._trigger_event(
                        'key_fragment_encountered', {'id': frag.id})
                    break

    def defer_key_fragment(self, frag_id: str) -> None:
        self._ignored_key_fragment_ids.add(frag_id)
        if self._pending_key_fragment_id == frag_id:
            self._pending_key_fragment_id = None

    def _check_hazards(self) -> None:
        if not self.spikes:
            return
        cell = (int(self.player.z), int(self.player.x))
        for s in self.spikes:
            if s.active and s.cell == cell:
                self._send_to_jail('spikes')
                return

    def _check_exit_condition(self) -> None:
        if self.gates.get('exit') and self.gates['exit'].locked:
            if self.coins_collected >= self.coins_required and self.keys_collected >= self.keys_required:
                self.open_gate('exit')
                self._trigger_event('exit_unlocked', {})

                # Create checkpoint arrow at exit area when all items collected
                if self.exit_cells:
                    # Place arrow between middle 'd' and 'E' for better visibility
                    # Exit cells are at the end, gate cells are before them
                    # Position arrow halfway between middle gate and first exit cell
                    if len(self.exit_cells) >= 2:
                        # Use middle exit cell
                        middle_exit_idx = len(self.exit_cells) // 2
                        middle_exit_cell = self.exit_cells[middle_exit_idx]
                        # Move arrow one block back from middle exit
                        adjusted_arrow_cell = (
                            middle_exit_cell[0], middle_exit_cell[1] - 1)
                    else:
                        arrow_cell = self.exit_cells[0]
                        adjusted_arrow_cell = (
                            arrow_cell[0], arrow_cell[1] - 1)

                    print(
                        f"DEBUG: Creating checkpoint arrow at {adjusted_arrow_cell} (middle exit cell: {middle_exit_cell if len(self.exit_cells) >= 2 else self.exit_cells[0]})")
                    self.checkpoint_arrow = CheckpointArrow(
                        cell=adjusted_arrow_cell,
                        visible=True,
                        bob_offset=0.0,
                        bob_phase=0.0
                    )
                    self._trigger_event('checkpoint_spawned', {})

        # Win when player reaches exit cell and gate is open
        cell = (int(self.player.z), int(self.player.x))
        if cell in self.exit_cells:
            gate = self.gates.get('exit')
            if gate and not gate.locked and gate.y_offset <= -self.wall_height + 0.25:
                self.game_won = True
                self._trigger_event('game_won', {'time_s': self.elapsed_s})

    def interact(self) -> Optional[str]:
        # Used by adapter for E
        # In jail: interact with book to start puzzle
        if self.in_jail:
            if self.jail_book_cell:
                br, bc = self.jail_book_cell
                if abs(int(self.player.z) - br) <= 1 and abs(int(self.player.x) - bc) <= 1:
                    # Check if jail gate is up before allowing minigame
                    jail_gate = self.gates.get('jail')
                    if jail_gate and jail_gate.y_offset >= -1e-3:  # Gate is up
                        return 'jail_book'
            # Allow interaction with the jail gate to leave (if already unlocked)
            near_gate = self.get_nearby_gate()
            if near_gate and near_gate.id == 'jail':
                return 'gate_jail'
            return None

        # Interact with gates near player
        near_gate = self.get_nearby_gate()
        if near_gate:
            gid = near_gate.id
            if gid == 'exit' and near_gate.locked:
                return 'exit_locked'
            if gid == 'jail' and near_gate.locked:
                return 'jail_locked'
            return f'gate_{gid}'

        frag = self.get_nearby_key_fragment()
        if frag:
            return None
        return None

    def get_nearby_key_fragment(self) -> Optional[KeyFragment]:
        pc = (int(self.player.z), int(self.player.x))
        for frag in self.key_fragments.values():
            if frag.taken:
                continue
            r, c = frag.cell
            if abs(r - pc[0]) <= 1 and abs(c - pc[1]) <= 1:
                return frag
        return None

    def mark_key_fragment_taken(self, frag_id: str) -> bool:
        frag = self.key_fragments.get(frag_id)
        if not frag or frag.taken:
            return False
        frag.taken = True
        self.keys_collected += 1
        self._trigger_event(
            'key_picked', {'id': frag.id, 'count': self.keys_collected})
        if self._pending_key_fragment_id == frag.id:
            self._pending_key_fragment_id = None
        return True

    def clear_pending_key_fragment(self, frag_id: str) -> None:
        if self._pending_key_fragment_id == frag_id:
            self._pending_key_fragment_id = None

    def get_nearby_gate(self) -> Optional[Gate]:
        pc = (int(self.player.z), int(self.player.x))
        for gate in self.gates.values():
            for cell in gate.cells:
                if abs(cell[0] - pc[0]) <= 1 and abs(cell[1] - pc[1]) <= 1:
                    return gate
        return None

    def try_leave_jail(self) -> bool:
        gate = self.gates.get('jail')
        if not gate:
            return False
        if gate.locked:
            return False
        self.in_jail = False
        # Teleport to start area after leaving jail
        spawn = self._pick_spawn_cell()
        self.player.x = spawn[1] + 0.5
        self.player.z = spawn[0] + 0.5
        self._refresh_sector_state(show_popup=True)
        self._trigger_event('left_jail', {})
        self.close_gate('jail')
        return True

    def mark_jail_puzzle_success(self) -> None:
        self.open_gate('jail')
        # Reset jail state so player can be sent to jail again later
        self.in_jail = False

    def _send_to_jail(self, reason: str) -> None:
        # Always allow sending to jail, but check if player is already in jail position
        current_cell = (int(self.player.z), int(self.player.x))
        jail_cell = self.jail_spawn_cell or self._find_jail_cell() or (
            self.start_cells[0] if self.start_cells else (1, 1))

        # Only count as jail entry if not already in jail
        if not self.in_jail:
            self.jail_entries += 1

        self.in_jail = True
        # Only send to jail if not already at jail location
        if current_cell == jail_cell:
            return

        # If jail gate is open or lowering, instantly close it to prevent escape
        jail_gate = self.gates.get('jail')
        if jail_gate and not jail_gate.locked:
            # Instantly close the gate - no animation, immediate lock
            jail_gate.locked = True
            jail_gate.y_offset = 0.0  # Fully up immediately
            jail_gate.lowering = False
            jail_gate.raising = False
            jail_gate.close_delay_timer = 0.0

        self.in_jail = True
        self.player.x = jail_cell[1] + 0.5
        self.player.z = jail_cell[0] + 0.5
        self._refresh_sector_state(show_popup=True)
        self._trigger_event('sent_to_jail', {'reason': reason})

    def _find_jail_cell(self) -> Optional[Tuple[int, int]]:
        # Heuristic: find a large open pocket near center rows.
        for r in range(self.height // 3, self.height * 2 // 3):
            for c in range(self.width // 3, self.width * 2 // 3):
                if (r, c) in self.floors and (r, c) not in self.gate_cells:
                    # Ensure surrounded by walls-ish
                    return (r, c)
        return None

    def _distance_xz(self, ax: float, az: float, bx: float, bz: float) -> float:
        return math.hypot(ax - bx, az - bz)

    @property
    def avg_coin_time(self) -> float:
        """Calculate average time between coin collections"""
        if not self.coin_collection_times:
            return 0.0
        return sum(self.coin_collection_times) / len(self.coin_collection_times)

    def register_event_callback(self, event_name: str, callback: Callable[[dict], None]) -> None:
        if event_name not in self._event_callbacks:
            self._event_callbacks[event_name] = []
        self._event_callbacks[event_name].append(callback)

    def _trigger_event(self, event_name: str, data: Optional[dict] = None) -> None:
        for cb in self._event_callbacks.get(event_name, []):
            cb(data or {})

    def _refresh_sector_state(self, *, show_popup: bool) -> None:
        sid = self.sector_id_for_cell((int(self.player.z), int(self.player.x)))
        if not sid:
            return
        if sid != self.current_sector_id:
            self.current_sector_id = sid
            self._sector_popup_id = sid
            self._sector_popup_timer = 2.0 if show_popup else 0.0
            self._trigger_event('sector_entered', {'id': sid})
            return
        if show_popup:
            self._sector_popup_id = sid
            self._sector_popup_timer = 2.0

    def rotate_player(self, yaw_delta: float) -> None:
        self.player.yaw = (self.player.yaw + yaw_delta) % (2 * math.pi)

    def tilt_camera(self, pitch_delta: float) -> None:
        self.player.pitch = max(-math.pi / 2,
                                min(math.pi / 2, self.player.pitch + pitch_delta))

    def move_player(self, dx: float, dz: float) -> bool:
        forward_x = math.sin(self.player.yaw)
        forward_z = math.cos(self.player.yaw)
        right_x = -math.cos(self.player.yaw)
        right_z = math.sin(self.player.yaw)

        world_dx = dx * right_x + dz * forward_x
        world_dz = dx * right_z + dz * forward_z

        nx = self.player.x + world_dx
        nz = self.player.z + world_dz

        if self._can_move_to(nx, nz):
            self.player.x = nx
            self.player.z = nz
            self._trigger_event('player_move', {'x': nx, 'z': nz})
            self._check_collectibles()
            self._check_hazards()
            return True
        return False

    def _can_move_to(self, x: float, z: float) -> bool:
        # Keep some margin from the outer border.
        if x < 0.25 or z < 0.25 or x > self.width - 0.25 or z > self.height - 0.25:
            return False
        cell_r = int(z)
        cell_c = int(x)
        if (cell_r, cell_c) not in self.floors:
            return False
        # Prevent getting too close to walls. If the camera clips into a wall quad,
        # the near plane will cut it and you'll see "inside" the tile.
        radius = 0.30
        for rr in range(cell_r - 1, cell_r + 2):
            for cc in range(cell_c - 1, cell_c + 2):
                if (rr, cc) not in self.walls:
                    continue
                minx = cc
                maxx = cc + 1.0
                minz = rr
                maxz = rr + 1.0
                dx = 0.0
                if x < minx:
                    dx = minx - x
                elif x > maxx:
                    dx = x - maxx
                dz = 0.0
                if z < minz:
                    dz = minz - z
                elif z > maxz:
                    dz = z - maxz
                if dx * dx + dz * dz < radius * radius:
                    return False

        cell = (cell_r, cell_c)
        # Block closed gates
        for gate in self.gates.values():
            if gate.locked and cell in set(gate.cells):
                return False
        return True

    def iter_visible_tiles(self) -> Iterable[Tuple[int, int, str]]:
        # Return full map tiles (r, c, type)
        for r in range(self.height):
            for c in range(self.width):
                if (r, c) in self.walls:
                    yield r, c, 'wall'
                elif (r, c) in self.floors:
                    yield r, c, 'floor'
