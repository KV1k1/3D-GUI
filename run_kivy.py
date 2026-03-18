import os
from adapters.kivy.kivy_window import run

os.environ['KIVY_GL_PROFILE'] = 'core'
os.environ['KIVY_GRAPHICS'] = 'gl'

if __name__ == '__main__':
    run()