import sys
from adapters.wxpython.window import run

if __name__ == '__main__':
    try:
        raise SystemExit(int(run() or 0))
    except Exception:
        import traceback
        print("wxPython crashed:")
        traceback.print_exc()
        sys.exit(1)
