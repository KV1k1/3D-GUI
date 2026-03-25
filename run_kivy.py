import os
from adapters.kivy.kivy_window import run

os.environ['KIVY_GL_PROFILE'] = 'core'
os.environ['KIVY_GRAPHICS'] = 'gl'
os.environ['KIVY_DEBUG_MODE'] = '0'  # Disable touch markers and red dots

if __name__ == '__main__':
    run()
