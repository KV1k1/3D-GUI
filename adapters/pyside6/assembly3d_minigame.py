import math
import time

import numpy as np

from PySide6.QtCore import QPoint, Qt, QTimer

from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget, QSizePolicy

from pyqtgraph.opengl import GLGridItem, GLMeshItem, GLViewWidget, MeshData


class Assembly3DMinigame(QDialog):

    def __init__(self, parent=None, *, kind: str = 'KP'):

        super().__init__(parent)

        self.kind = str(kind or 'KP').upper()

        self._selection_flash_timer = QTimer(self)
        self._selection_flash_timer.setInterval(33)
        self._selection_flash_timer.timeout.connect(self._tick_selection_flash)
        self._selection_flash_timer.start()

        self._init_3d()

    def closeEvent(self, event) -> None:
        try:
            self._clear_gl_views()
        except Exception:
            pass
        super().closeEvent(event)

    def reset(self, *, kind: str) -> None:
        self.kind = str(kind or 'KP').upper()
        self._clear_gl_views()
        self._build_scene_for_kind()
        self._ensure_piece_controls_match_scene()
        self._update_feedback_3d()

    def _clear_gl_views(self) -> None:
        if getattr(self, 'ref_view', None) is not None:
            for item in list(getattr(self.ref_view, 'items', []) or []):
                try:
                    self.ref_view.removeItem(item)
                except Exception:
                    pass
        if getattr(self, 'asm_view', None) is not None:
            for item in list(getattr(self.asm_view, 'items', []) or []):
                try:
                    self.asm_view.removeItem(item)
                except Exception:
                    pass
        self.meshes = []
        self.grid_lines = []

    def _ensure_piece_controls_match_scene(self) -> None:
        if not hasattr(self, 'piece_btns'):
            return
        if len(self.piece_btns) == len(getattr(self, 'pieces', []) or []):
            return
        for btn in list(self.piece_btns):
            try:
                btn.setParent(None)
                btn.deleteLater()
            except Exception:
                pass
        self.piece_btns = []
        layout = getattr(self, '_piece_btn_layout', None)
        if layout is None:
            return
        for i, piece in enumerate(self.pieces):
            btn = QPushButton(f"{piece['type'].capitalize()} {i + 1}")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False,
                                idx=i: self._select_piece_by_button_3d(idx))
            self.piece_btns.append(btn)
            layout.addWidget(btn)

    def _tick_selection_flash(self) -> None:
        if getattr(self, 'selected_piece', None) is None:
            return
        idx = int(self.selected_piece)
        if idx < 0 or idx >= len(getattr(self, 'meshes', []) or []):
            return
        if idx < 0 or idx >= len(getattr(self, 'placed', []) or []):
            return
        if self.placed[idx]:
            return
        self._update_feedback_3d()

    def _init_3d(self) -> None:

        self.setWindowTitle('3D Assembly Minigame')

        self.setModal(True)

        self.setFixedSize(900, 600)

        self.setStyleSheet("""

            QDialog {

                background-color: #4a4a50;

                color: #ffffff;

            }

            QLabel {

                color: #ffffff;

                font-size: 14px;

                font-weight: 500;

            }

            QPushButton {

                background-color: #5a5a60;

                color: #ffffff;

                border: 2px solid #7a7a80;

                border-radius: 8px;

                padding: 8px 16px;

                font-size: 13px;

                font-weight: 600;

            }

            QPushButton:hover {

                background-color: #6a6a70;

                border-color: #ffd700;

            }

            QPushButton:pressed {

                background-color: #4a4a50;

            }

            QPushButton:checked {

                background-color: #ffd700;

                color: #2d2d30;

                border-color: #ffed4e;

            }

            QPushButton:disabled {

                background-color: #3a3a40;

                color: #808080;

                border-color: #5a5a60;

            }

        """)

        self.selected_piece = None
        self.dragging = False
        self.last_mouse_pos = QPoint()

        main_layout = QHBoxLayout(self)

        ref_layout = QVBoxLayout()

        ref_label = QLabel('Reference')

        ref_label.setAlignment(Qt.AlignCenter)

        ref_label.setStyleSheet("""

            QLabel {

                color: #ffffff;

                font-size: 16px;

                font-weight: 700;

                padding: 8px;

                background-color: #5a5a60;

                border-radius: 6px;

                border: 1px solid #7a7a80;

            }

        """)

        ref_layout.addWidget(ref_label)

        self.ref_view = GLViewWidget()

        self.ref_view.setCameraPosition(distance=8, elevation=20, azimuth=30)

        self.ref_view.setBackgroundColor((80, 80, 85, 255))

        ref_layout.addWidget(self.ref_view, stretch=1)

        self.meshes = []
        self.grid_lines = []

        main_layout.addLayout(ref_layout, stretch=2)

        asm_layout = QVBoxLayout()

        asm_label = QLabel('Assembly Area')

        asm_label.setAlignment(Qt.AlignCenter)

        asm_label.setStyleSheet("""

            QLabel {

                color: #ffffff;

                font-size: 16px;

                font-weight: 700;

                padding: 8px;

                background-color: #5a5a60;

                border-radius: 6px;

                border: 1px solid #7a7a80;

            }

        """)

        asm_layout.addWidget(asm_label)

        self.asm_view = GLViewWidget()

        self.asm_view.setCameraPosition(distance=8, elevation=20, azimuth=30)

        self.asm_view.setBackgroundColor((240, 240, 245, 255))

        asm_layout.addWidget(self.asm_view, stretch=1)

        self._build_scene_for_kind()

        controls_layout = QHBoxLayout()

        self.feedback_label = QLabel('')

        self.feedback_label.setAlignment(Qt.AlignCenter)

        self.feedback_label.setFixedHeight(38)

        self.feedback_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.feedback_label.setFixedWidth(420)

        self.feedback_label.setStyleSheet("""

            QLabel {

                color: #ffffff;

                font-size: 14px;

                font-weight: 600;

                padding: 6px;

                background-color: #5a5a60;

                border-radius: 6px;

                border: 1px solid #7a7a80;

            }

        """)

        controls_layout.addWidget(self.feedback_label)

        self.reset_btn = QPushButton('Reset')

        self.reset_btn.clicked.connect(self._reset_pieces_3d)

        controls_layout.addWidget(self.reset_btn)

        self.check_btn = QPushButton('Check')

        self.check_btn.clicked.connect(self._check_assembly_3d)

        self.check_btn.setStyleSheet("""

            QPushButton {

                background-color: #4ade80;

                color: #2d2d30;

                border: 2px solid #22c55e;

            }

            QPushButton:hover {

                background-color: #22c55e;

                border-color: #16a34a;

            }

        """)

        controls_layout.addWidget(self.check_btn)

        self.quit_btn = QPushButton('Quit')

        self.quit_btn.clicked.connect(self.reject)

        self.quit_btn.setStyleSheet("""

            QPushButton {

                background-color: #ef4444;

                color: #ffffff;

                border: 2px solid #dc2626;

            }

            QPushButton:hover {

                background-color: #dc2626;

                border-color: #b91c1c;

            }

        """)

        controls_layout.addWidget(self.quit_btn)

        asm_layout.addLayout(controls_layout)

        self.piece_btns = []

        piece_btn_layout = QHBoxLayout()
        self._piece_btn_layout = piece_btn_layout

        for i, piece in enumerate(self.pieces):

            btn = QPushButton(f"{piece['type'].capitalize()} {i + 1}")

            btn.setCheckable(True)

            btn.clicked.connect(lambda checked=False,
                                idx=i: self._select_piece_by_button_3d(idx))

            self.piece_btns.append(btn)

            piece_btn_layout.addWidget(btn)

        asm_layout.addLayout(piece_btn_layout)

        arrow_grid = QGridLayout()

        arrow_grid.setSpacing(4)

        btn_up = QPushButton('↑')

        btn_up.clicked.connect(lambda: self._move_selected_piece_3d(0, 1, 0))

        btn_up.setFixedSize(40, 40)

        btn_up.setStyleSheet("""

            QPushButton {

                background-color: #5a5a60;

                color: #ffffff;

                border: 2px solid #7a7a80;

            }

            QPushButton:hover {

                background-color: #6a6a70;

                border-color: #ffd700;

            }

            QPushButton:pressed {

                background-color: #ffd700;

                color: #2d2d30;

            }

        """)

        arrow_grid.addWidget(btn_up, 0, 1)

        btn_left = QPushButton('←')

        btn_left.clicked.connect(
            lambda: self._move_selected_piece_3d(-1, 0, 0))

        btn_left.setFixedSize(40, 40)

        btn_left.setStyleSheet("""

            QPushButton {

                background-color: #5a5a60;

                color: #ffffff;

                border: 2px solid #7a7a80;

            }

            QPushButton:hover {

                background-color: #6a6a70;

                border-color: #ffd700;

            }

            QPushButton:pressed {

                background-color: #ffd700;

                color: #2d2d30;

            }

        """)

        arrow_grid.addWidget(btn_left, 1, 0)

        btn_down = QPushButton('↓')

        btn_down.clicked.connect(
            lambda: self._move_selected_piece_3d(0, -1, 0))

        btn_down.setFixedSize(40, 40)

        btn_down.setStyleSheet("""

            QPushButton {

                background-color: #5a5a60;

                color: #ffffff;

                border: 2px solid #7a7a80;

            }

            QPushButton:hover {

                background-color: #6a6a70;

                border-color: #ffd700;

            }

            QPushButton:pressed {

                background-color: #ffd700;

                color: #2d2d30;

            }

        """)

        arrow_grid.addWidget(btn_down, 2, 1)

        btn_right = QPushButton('→')

        btn_right.clicked.connect(
            lambda: self._move_selected_piece_3d(1, 0, 0))

        btn_right.setFixedSize(40, 40)

        btn_right.setStyleSheet("""

            QPushButton {

                background-color: #5a5a60;

                color: #ffffff;

                border: 2px solid #7a7a80;

            }

            QPushButton:hover {

                background-color: #6a6a70;

                border-color: #ffd700;

            }

            QPushButton:pressed {

                background-color: #ffd700;

                color: #2d2d30;

            }

        """)

        arrow_grid.addWidget(btn_right, 1, 2)

        btn_zup = QPushButton('Z+')

        btn_zup.clicked.connect(lambda: self._move_selected_piece_3d(0, 0, 1))

        btn_zup.setFixedSize(40, 40)

        btn_zup.setStyleSheet("""

            QPushButton {

                background-color: #fff8dc;

                color: #2d2d30;

                border: 2px solid #ffd700;

                font-size: 11px;

            }

            QPushButton:hover {

                background-color: #ffed4e;

            }

            QPushButton:pressed {

                background-color: #ffd700;

            }

        """)

        arrow_grid.addWidget(btn_zup, 0, 3)

        btn_zdown = QPushButton('Z-')

        btn_zdown.clicked.connect(
            lambda: self._move_selected_piece_3d(0, 0, -1))

        btn_zdown.setFixedSize(40, 40)

        btn_zdown.setStyleSheet("""

            QPushButton {

                background-color: #fff8dc;

                color: #2d2d30;

                border: 2px solid #ffd700;

                font-size: 11px;

            }

            QPushButton:hover {

                background-color: #ffed4e;

            }

            QPushButton:pressed {

                background-color: #ffd700;

            }

        """)

        arrow_grid.addWidget(btn_zdown, 2, 3)

        arrow_widget = QWidget()

        arrow_widget.setLayout(arrow_grid)

        arrow_widget.setStyleSheet("""

            QWidget {

                background-color: #5a5a60;

                border-radius: 8px;

                border: 1px solid #7a7a80;

                padding: 8px;

            }

        """)

        asm_layout.addWidget(arrow_widget)

        main_layout.addLayout(asm_layout, stretch=1)

        self.setLayout(main_layout)

        self.asm_view.mousePressEvent = self._mousePressEvent3D
        self.asm_view.mouseMoveEvent = self._mouseMoveEvent3D
        self.asm_view.mouseReleaseEvent = self._mouseReleaseEvent3D

        self._update_feedback_3d()

    def _build_scene_for_kind(self) -> None:
        self.pieces = self._generate_pieces_3d(self.kind)
        self.target_structure = self._generate_target_structure_3d(self.kind)
        self.placed = [False] * len(self.pieces)
        self.selected_piece = None
        self.dragging = False

        for i, part in enumerate(self.target_structure):
            mesh = self._create_mesh_3d(
                part['type'], color=self.pieces[i]['color'])
            self._set_mesh_transform_3d(mesh, part['pos'], part['rot'])
            self.ref_view.addItem(mesh)

        self._add_grid_overlay_3d(self.asm_view)

        for piece in self.pieces:
            mesh = self._create_mesh_3d(piece['type'], color=piece['color'])
            self._set_mesh_transform_3d(mesh, piece['pos'], piece['rot'])
            self.asm_view.addItem(mesh)
            self.meshes.append(mesh)

    def _generate_pieces_3d(self, kind: str):

        yellow = (255, 223, 0, 220)

        blue = (0, 149, 255, 220)

        red = (255, 69, 0, 220)

        kind = str(kind or 'KP').upper()

        # KP: 2 cubes + 1 pyramid.

        if kind == 'KP':

            return [

                {'type': 'cube', 'color': yellow, 'pos': np.array(
                    [2, 0, 0], dtype=float), 'rot': [0, 0, 0]},

                {'type': 'cube', 'color': blue, 'pos': np.array(
                    [-2, 0, 0], dtype=float), 'rot': [0, 0, 0]},

                {'type': 'pyramid', 'color': red, 'pos': np.array(
                    [0, 0, 0], dtype=float), 'rot': [0, 0, 0]},

            ]

        # K: 3 base cubes, plus 2 cubes stacked on the first two.

        if kind == 'K':

            colors = [blue, yellow, red, red, blue]

            pieces = []

            for i, col in enumerate(colors):

                pieces.append({'type': 'cube', 'color': col, 'pos': np.array(
                    [-3 + i, 0, 0], dtype=float), 'rot': [0, 0, 0]})

            return pieces

        # KH: simplified (4 pieces): 2 cubes base + 2 pyramids on top.

        colors = [yellow, red, blue, yellow]

        types = ['cube', 'cube', 'pyramid', 'pyramid']

        pieces = []

        for i, (t, col) in enumerate(zip(types, colors)):

            pieces.append({'type': t, 'color': col, 'pos': np.array(
                [-2 + i, 0, 0], dtype=float), 'rot': [0, 0, 0]})

        return pieces

    def _generate_target_structure_3d(self, kind: str):

        kind = str(kind or 'KP').upper()

        if kind == 'KP':

            return [

                {'type': 'cube', 'pos': np.array(
                    [0, 0, 0], dtype=float), 'rot': [0, 0, 0]},

                {'type': 'cube', 'pos': np.array(
                    [0, 1, 0], dtype=float), 'rot': [0, 0, 0]},

                {'type': 'pyramid', 'pos': np.array(
                    [0, 2, 0], dtype=float), 'rot': [0, 0, 0]},

            ]

        if kind == 'K':

            # Simplified per diagram:

            # Base line of 3 cubes at y=0: x = 0..2

            # Stack: cubes at (0,1) and (1,1)

            return [

                {'type': 'cube', 'pos': np.array(
                    [0, 0, 0], dtype=float), 'rot': [0, 0, 0]},

                {'type': 'cube', 'pos': np.array(
                    [1, 0, 0], dtype=float), 'rot': [0, 0, 0]},

                {'type': 'cube', 'pos': np.array(
                    [2, 0, 0], dtype=float), 'rot': [0, 0, 0]},

                {'type': 'cube', 'pos': np.array(
                    [0, 1, 0], dtype=float), 'rot': [0, 0, 0]},

                {'type': 'cube', 'pos': np.array(
                    [1, 1, 0], dtype=float), 'rot': [0, 0, 0]},

            ]

        # KH: simplified per diagram:

        # Two base cubes at y=0 (x=0..1), with two pyramids at y=1.

        return [

            {'type': 'cube', 'pos': np.array(
                [0, 0, 0], dtype=float), 'rot': [0, 0, 0]},

            {'type': 'cube', 'pos': np.array(
                [1, 0, 0], dtype=float), 'rot': [0, 0, 0]},

            {'type': 'pyramid', 'pos': np.array(
                [0, 1, 0], dtype=float), 'rot': [0, 0, 0]},

            {'type': 'pyramid', 'pos': np.array(
                [1, 1, 0], dtype=float), 'rot': [0, 0, 0]},

        ]

    def _create_mesh_3d(self, type, color):

        if type == 'cube':

            verts = np.array(

                [

                    [-0.5, -0.5, -0.5],

                    [0.5, -0.5, -0.5],

                    [0.5, 0.5, -0.5],

                    [-0.5, 0.5, -0.5],

                    [-0.5, -0.5, 0.5],

                    [0.5, -0.5, 0.5],

                    [0.5, 0.5, 0.5],

                    [-0.5, 0.5, 0.5],

                ],

                dtype=float,

            )

            faces = np.array(

                [

                    [0, 1, 2],

                    [0, 2, 3],

                    [4, 5, 6],

                    [4, 6, 7],

                    [0, 1, 5],

                    [0, 5, 4],

                    [2, 3, 7],

                    [2, 7, 6],

                    [1, 2, 6],

                    [1, 6, 5],

                    [0, 3, 7],

                    [0, 7, 4],

                ],

                dtype=int,

            )

            md = MeshData(vertexes=verts, faces=faces)

        elif type == 'pyramid':

            verts = np.array(

                [[0, 0.5, 0], [0.5, -0.5, 0.5], [0.5, -0.5, -0.5],
                    [-0.5, -0.5, -0.5], [-0.5, -0.5, 0.5]],

                dtype=float,

            )

            faces = np.array(

                [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1], [1, 2, 3], [1, 3, 4]],

                dtype=int,

            )

            md = MeshData(vertexes=verts, faces=faces)

        else:

            md = MeshData.sphere(rows=16, cols=16, radius=0.5)

        mesh = GLMeshItem(

            meshdata=md,

            smooth=True,

            color=tuple([c / 255.0 for c in color]),

            drawEdges=False,

        )

        try:
            mesh.setData(edgeColor=(0.0, 0.0, 0.0, 0.0))
        except Exception:
            pass

        if hasattr(mesh, 'opts'):
            mesh.opts['glOptions'] = 'opaque'

        return mesh

    def _set_mesh_transform_3d(self, mesh, pos, rot):

        mesh.resetTransform()

        mesh.translate(*pos)

        mesh.rotate(rot[0], 1, 0, 0)

        mesh.rotate(rot[1], 0, 1, 0)

        mesh.rotate(rot[2], 0, 0, 1)

    def _add_grid_overlay_3d(self, glview):

        from pyqtgraph.opengl import GLLinePlotItem

        grid_lines = []

        for x in range(-4, 5):

            pts = np.array([[x, -1.5, 0], [x, 2.5, 0]])

            color = (1.0, 0.84, 0.0, 0.3) if x == 0 else (0.3, 0.3, 0.3, 0.2)

            width = 2.0 if x == 0 else 1.5

            grid = GLLinePlotItem(pos=pts, color=color,
                                  width=width, antialias=True, mode='lines')

            glview.addItem(grid)

            grid_lines.append(grid)

        for y in range(-1, 4):

            pts = np.array([[-4, y, 0], [4, y, 0]])

            color = (1.0, 0.84, 0.0, 0.3) if y == 0 else (0.3, 0.3, 0.3, 0.2)

            width = 2.0 if y == 0 else 1.5

            grid = GLLinePlotItem(pos=pts, color=color,
                                  width=width, antialias=True, mode='lines')

            glview.addItem(grid)

            grid_lines.append(grid)

        self.grid_lines = grid_lines

    def _update_feedback_3d(self):

        for i, mesh in enumerate(self.meshes):

            if self.placed[i]:

                mesh.setColor((0.0, 0.7, 1.0, 0.8))
                try:
                    mesh.setData(drawEdges=False)
                    if hasattr(mesh, 'opts'):
                        mesh.opts['glOptions'] = 'translucent'
                except Exception:
                    pass

            elif self.selected_piece == i:

                c = self.pieces[i]['color']

                # Smooth flash between original color and green (~1.0s period).
                t = float(time.perf_counter())
                period = 1.0
                phase = (t % period) / period
                w = 0.5 - 0.5 * math.cos(phase * 2.0 * math.pi)

                r0, g0, b0 = (c[0] / 255.0), (c[1] / 255.0), (c[2] / 255.0)
                r = (1.0 - w) * r0 + w * 0.0
                g = (1.0 - w) * g0 + w * 1.0
                b = (1.0 - w) * b0 + w * 0.0
                mesh.setColor((r, g, b, 1.0))

                try:
                    mesh.setData(drawEdges=False)
                    if hasattr(mesh, 'opts'):
                        mesh.opts['glOptions'] = 'opaque'
                except Exception:
                    pass

            else:

                c = self.pieces[i]['color']
                mesh.setColor(tuple([x / 255.0 for x in c]))
                try:
                    mesh.setData(drawEdges=False)
                    if hasattr(mesh, 'opts'):
                        mesh.opts['glOptions'] = 'opaque'
                except Exception:
                    pass

        for i, btn in enumerate(self.piece_btns):

            btn.setChecked(self.selected_piece == i)

        if all(self.placed):

            self.feedback_label.setText("🎉 Perfect Assembly! 🎉")

            self.feedback_label.setStyleSheet("""

                QLabel {

                    color: #ffffff;

                    font-size: 14px;

                    font-weight: 700;

                    padding: 8px;

                    background-color: #2d5a2d;

                    border-radius: 6px;

                    border: 2px solid #4ade80;

                }

            """)

            self._show_congratulations_3d()

        else:

            self.feedback_label.setText(
                "Select piece → Use arrows to move → Z+/- for height")

            self.feedback_label.setStyleSheet("""

                QLabel {

                    color: #ffffff;

                    font-size: 14px;

                    font-weight: 600;

                    padding: 6px;

                    background-color: #5a5a60;

                    border-radius: 6px;

                    border: 1px solid #7a7a80;

                }

            """)

    def _select_piece_by_button_3d(self, idx):

        self.selected_piece = idx

        self._update_feedback_3d()

    GRID_MIN = -4

    GRID_MAX = 4

    Z_MIN = 0

    Z_MAX = 2

    def _move_selected_piece_3d(self, dx, dy, dz):

        if self.selected_piece is None or self.placed[self.selected_piece]:

            return

        pos = self.pieces[self.selected_piece]['pos']

        new_pos = pos.copy()

        new_pos[0] = max(self.GRID_MIN, min(self.GRID_MAX, new_pos[0] + dx))

        new_pos[1] = max(self.GRID_MIN, min(self.GRID_MAX, new_pos[1] + dy))

        new_pos[2] = max(self.Z_MIN, min(self.Z_MAX, new_pos[2] + dz))

        self.pieces[self.selected_piece]['pos'] = new_pos

        self._set_mesh_transform_3d(
            self.meshes[self.selected_piece], new_pos, self.pieces[self.selected_piece]['rot'])

        self._update_feedback_3d()

    def _check_assembly_3d(self):

        def neighbors_from_positions(positions: list[np.ndarray]) -> dict[int, set[int]]:

            adj: dict[int, set[int]] = {i: set()
                                        for i in range(len(positions))}

            ipos = [np.round(p).astype(int) for p in positions]

            for i in range(len(ipos)):

                for j in range(i + 1, len(ipos)):

                    diff = np.abs(ipos[i] - ipos[j])

                    touching = (np.sum(diff == 1) == 1) and (
                        np.sum(diff == 0) == 2)

                    if touching:

                        adj[i].add(j)

                        adj[j].add(i)

            return adj

        # Build a target adjacency graph from the reference structure.

        # We match pieces by index: the i-th piece must be the i-th target's type/color.

        # Placement is considered correct if the touching/connection graph matches, regardless

        # of whether connections are vertical or side-by-side.

        color_type_ok = True

        for i, target in enumerate(self.target_structure):

            if i >= len(self.pieces):

                color_type_ok = False

                break

            if self.pieces[i]['type'] != target['type']:

                color_type_ok = False

                break

        target_adj = neighbors_from_positions(
            [t['pos'] for t in self.target_structure])

        placed_adj = neighbors_from_positions([p['pos'] for p in self.pieces])

        adjacency_ok = True

        for i in range(len(self.target_structure)):

            if placed_adj.get(i, set()) != target_adj.get(i, set()):

                adjacency_ok = False

                break

        if color_type_ok and adjacency_ok:

            self.feedback_label.setText("Perfect Assembly!")

            self.feedback_label.setStyleSheet("""

                QLabel {

                    color: #ffffff;

                    font-size: 14px;

                    font-weight: 700;

                    padding: 8px;

                    background-color: #2d5a2d;

                    border-radius: 6px;

                    border: 2px solid #4ade80;

                }

            """)

            self._show_congratulations_3d()

        else:

            self.feedback_label.setText("❌ Incorrect - Keep Trying!")

            self.feedback_label.setStyleSheet("""

                QLabel {

                    color: #ffffff;

                    font-size: 14px;

                    font-weight: 600;

                    padding: 6px;

                    background-color: #5a2d2d;

                    border-radius: 6px;

                    border: 1px solid #ef4444;

                }

            """)

    def _reset_pieces_3d(self):

        for i, piece in enumerate(self.pieces):

            piece['pos'] = np.array(
                [2 if i == 0 else -2 if i == 1 else 0, 0, 0 if i < 2 else 2], dtype=float)

            piece['rot'] = [0, 0, 0]

            self._set_mesh_transform_3d(
                self.meshes[i], piece['pos'], piece['rot'])

            self.placed[i] = False

        self.selected_piece = None

        self._update_feedback_3d()

    def _mousePressEvent3D(self, event):

        if self.selected_piece is not None and not self.placed[self.selected_piece]:

            self.dragging = True

            self.last_mouse_pos = event.pos()

        else:

            self.dragging = False

    def _mouseMoveEvent3D(self, event):

        if self.dragging and self.selected_piece is not None:

            dx = event.x() - self.last_mouse_pos.x()

            dy = event.y() - self.last_mouse_pos.y()

            pos = self.pieces[self.selected_piece]['pos'].copy()

            pos[0] += dx * 0.02

            pos[1] += -dy * 0.02

            pos[0] = round(pos[0])

            pos[1] = round(pos[1])

            self.pieces[self.selected_piece]['pos'] = pos

            self._set_mesh_transform_3d(
                self.meshes[self.selected_piece], pos, self.pieces[self.selected_piece]['rot'])

            self.last_mouse_pos = event.pos()

            self._update_feedback_3d()

    def _mouseReleaseEvent3D(self, event):

        self.dragging = False

        self._update_feedback_3d()

    def _show_congratulations_3d(self):

        msg = QMessageBox(self)

        msg.setWindowTitle('Success!')

        msg.setText(

            "<div style='font-size:24px; font-weight:bold; color:#4ade80; margin-bottom:12px;'>Congratulations!</div>"

            "<div style='font-size:16px; color:#ffffff; margin-bottom:8px;'>You have successfully assembled the structure!</div>"

            "<div style='font-size:14px; color:#ffd700;'>You collected a key fragment!</div>"

        )

        msg.setStandardButtons(QMessageBox.Ok)

        msg.setStyleSheet(

            """

            QMessageBox {

                background-color: #4a4a50;

                color: #ffffff;

            }

            QLabel {

                font-size: 16px;

                color: #ffffff;

            }

            QPushButton {

                background-color: #4ade80;

                color: #2d2d30;

                border: 2px solid #22c55e;

                border-radius: 8px;

                padding: 8px 20px;

                font-size: 15px;

                font-weight: 600;

            }

            QPushButton:hover {

                background-color: #22c55e;

                border-color: #16a34a;

            }

        """

        )

        msg.exec()

        self.accept()
