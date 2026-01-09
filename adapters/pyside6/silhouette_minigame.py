from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SilhouetteMatchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Silhouette Matching')
        self.setModal(True)
        self.setMinimumSize(720, 420)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #2d2d30;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
                font-weight: 500;
            }
            QPushButton {
                background-color: #404040;
                color: #ffffff;
                border: 2px solid #555555;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border-color: #ffd700;
            }
            QPushButton:pressed {
                background-color: #353535;
            }
            QPushButton:disabled {
                background-color: #353535;
                color: #808080;
                border-color: #404040;
            }
        """)

        self._size = 6
        self._patterns = self._build_patterns(self._size)
        self._target = random.choice(self._patterns)

        root = QVBoxLayout(self)

        title = QLabel('Match the silhouette to unlock the jail gate')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            QLabel {
                color: #ffd700;
                font-size: 18px;
                font-weight: 700;
                padding: 8px;
                background-color: #404040;
                border-radius: 6px;
                border: 1px solid #555555;
                margin: 8px;
            }
        """)
        root.addWidget(title)

        mid = QHBoxLayout()
        root.addLayout(mid, stretch=1)

        left = QVBoxLayout()
        mid.addLayout(left, stretch=1)

        self._target_img = QLabel()
        self._target_img.setAlignment(Qt.AlignCenter)
        self._target_img.setPixmap(self._render_pattern(self._target, cell_px=26, pad=10))
        left.addWidget(self._target_img, stretch=1)

        right = QVBoxLayout()
        mid.addLayout(right, stretch=2)

        self._grid = QGridLayout()
        self._grid.setSpacing(6)

        grid_host = QWidget()
        grid_host.setLayout(self._grid)
        grid_host.setStyleSheet('background: #404040; border-radius: 10px; border: 2px solid #555555; padding: 12px;')
        right.addWidget(grid_host, stretch=1)

        self._cells: list[list[QPushButton]] = []
        for r in range(self._size):
            row: list[QPushButton] = []
            for c in range(self._size):
                b = QPushButton('')
                b.setCheckable(True)
                b.setFixedSize(46, 46)
                b.setStyleSheet(self._cell_style(False))
                b.toggled.connect(lambda checked=False, rr=r, cc=c: self._on_toggle(rr, cc, checked))
                self._grid.addWidget(b, r, c)
                row.append(b)
            self._cells.append(row)

        self._status = QLabel('')
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("""
            QLabel {
                color: #ffd700;
                font-size: 14px;
                font-weight: 600;
                padding: 6px;
                background-color: #404040;
                border-radius: 6px;
                border: 1px solid #555555;
                margin: 4px;
            }
        """)
        root.addWidget(self._status)

        buttons = QHBoxLayout()
        root.addLayout(buttons)

        self._btn_reset = QPushButton('Reset')
        self._btn_reset.clicked.connect(self._reset)
        buttons.addWidget(self._btn_reset)

        buttons.addStretch(1)

        self._btn_check = QPushButton('Unlock')
        self._btn_check.setDefault(True)
        self._btn_check.clicked.connect(self._check)
        self._btn_check.setStyleSheet("""
            QPushButton {
                background-color: #4ade80;
                color: #2d2d30;
                border: 2px solid #22c55e;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #22c55e;
                border-color: #16a34a;
            }
        """)
        buttons.addWidget(self._btn_check)

        self._btn_quit = QPushButton('Quit')
        self._btn_quit.clicked.connect(self.reject)
        self._btn_quit.setStyleSheet("""
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
        buttons.addWidget(self._btn_quit)

        self._reset()

    def _cell_style(self, on: bool) -> str:
        if on:
            return (
                'QPushButton { background:#ffd700; border:2px solid #ffed4e; border-radius:8px; }'
                'QPushButton:hover { background:#ffed4e; }'
                'QPushButton:pressed { background:#e6c200; }'
            )
        return (
            'QPushButton { background:#404040; border:2px solid #555555; border-radius:8px; }'
            'QPushButton:hover { background:#4a4a4a; border-color: #ffd700; }'
            'QPushButton:pressed { background:#353535; }'
        )

    def _on_toggle(self, r: int, c: int, checked: bool) -> None:
        self._cells[r][c].setStyleSheet(self._cell_style(checked))

    def _read_grid(self) -> list[list[int]]:
        out: list[list[int]] = []
        for r in range(self._size):
            row: list[int] = []
            for c in range(self._size):
                row.append(1 if self._cells[r][c].isChecked() else 0)
            out.append(row)
        return out

    def _reset(self) -> None:
        for r in range(self._size):
            for c in range(self._size):
                self._cells[r][c].setChecked(False)
                self._cells[r][c].setStyleSheet(self._cell_style(False))
        self._status.setText('Click the squares to draw the silhouette')
        self._status.setStyleSheet("""
            QLabel {
                color: #ffd700;
                font-size: 14px;
                font-weight: 600;
                padding: 6px;
                background-color: #404040;
                border-radius: 6px;
                border: 1px solid #555555;
                margin: 4px;
            }
        """)

    def _check(self) -> None:
        current = self._read_grid()
        if current == self._target:
            self.accept()
            return
        self._status.setText('❌ Incorrect. Keep trying!')
        self._status.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 14px;
                font-weight: 600;
                padding: 6px;
                background-color: #404040;
                border-radius: 6px;
                border: 1px solid #555555;
                margin: 4px;
            }
        """)

    def _render_pattern(self, pattern: list[list[int]], cell_px: int, pad: int) -> QPixmap:
        w = pad * 2 + self._size * cell_px
        h = pad * 2 + self._size * cell_px
        pm = QPixmap(w, h)
        pm.fill(QColor(45, 45, 48, 255))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)

        bg = QColor(64, 64, 68, 255)
        on = QColor(255, 215, 0, 255)
        off = QColor(96, 96, 96, 255)

        for r in range(self._size):
            for c in range(self._size):
                x = pad + c * cell_px
                y = pad + r * cell_px
                p.fillRect(x, y, cell_px - 2, cell_px - 2, on if pattern[r][c] else off)

        p.setPen(QColor(255, 215, 0, 128))
        p.drawRect(1, 1, w - 2, h - 2)
        p.end()
        return pm

    def _build_patterns(self, n: int) -> list[list[list[int]]]:
        def empty() -> list[list[int]]:
            return [[0 for _ in range(n)] for _ in range(n)]

        def add_rect(p: list[list[int]], r0: int, c0: int, r1: int, c1: int) -> None:
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    if 0 <= r < n and 0 <= c < n:
                        p[r][c] = 1

        patterns: list[list[list[int]]] = []

        # Key silhouette
        p = empty()
        add_rect(p, 1, 1, 1, 4)
        add_rect(p, 2, 3, 4, 3)
        add_rect(p, 4, 1, 4, 2)
        patterns.append(p)

        # Door silhouette
        p = empty()
        add_rect(p, 1, 2, 4, 3)
        add_rect(p, 1, 1, 1, 4)
        patterns.append(p)

        # Ghost silhouette
        p = empty()
        add_rect(p, 1, 2, 4, 3)
        add_rect(p, 0, 2, 1, 3)
        add_rect(p, 4, 1, 4, 4)
        patterns.append(p)

        # Cross
        p = empty()
        add_rect(p, 2, 1, 3, 4)
        add_rect(p, 1, 2, 4, 3)
        patterns.append(p)

        # Spiral-ish
        p = empty()
        add_rect(p, 1, 1, 1, 4)
        add_rect(p, 1, 1, 4, 1)
        add_rect(p, 4, 1, 4, 4)
        add_rect(p, 2, 4, 4, 4)
        add_rect(p, 2, 2, 2, 3)
        patterns.append(p)

        return patterns
