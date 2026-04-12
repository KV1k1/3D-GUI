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
    raise SystemExit(run())
