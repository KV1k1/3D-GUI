import os
import sys
from adapters.kivy.window import run

os.environ['KIVY_GL_PROFILE'] = 'core'
os.environ['KIVY_GRAPHICS'] = 'gl'
os.environ['KIVY_DEBUG_MODE'] = '0'
os.environ['KIVY_MULTITOUCH'] = '0'
os.environ['KIVY_LOG_MODE'] = '0'

if __name__ == '__main__':
    try:
        raise SystemExit(int(run() or 0))
    except Exception:
        import traceback
        print("Kivy crashed:")
        traceback.print_exc()
        sys.exit(1)
