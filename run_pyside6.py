import sys
from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtGui import QSurfaceFormat
from adapters.pyside6.window import run

if __name__ == '__main__':
    try:
        QCoreApplication.setAttribute(Qt.AA_UseDesktopOpenGL)
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)
        fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
        fmt.setSamples(4)
        QSurfaceFormat.setDefaultFormat(fmt)
    except Exception:
        pass
    try:
        raise SystemExit(int(run() or 0))
    except Exception:
        import traceback
        print("PySide6 crashed:")
        traceback.print_exc()
        sys.exit(1)
