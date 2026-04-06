"""FPS camera controller with mouse warping."""
from typing import Tuple, Optional, Callable

class FPSCameraController:
    
    def __init__(
        self,
        sensitivity: float = 0.002,
        invert_y: bool = False,
        min_pitch_deg: float = -89.0,
        max_pitch_deg: float = 89.0,
    ):
        self.sensitivity = sensitivity
        self.invert_y = invert_y
        self.min_pitch = min_pitch_deg * 3.14159 / 180.0
        self.max_pitch = max_pitch_deg * 3.14159 / 180.0
        
        self._captured = False
        self._center: Optional[Tuple[int, int]] = None
        self._last_pos: Optional[Tuple[float, float]] = None
        
        self.on_rotate: Optional[Callable[[float, float], None]] = None
        self.on_capture: Optional[Callable[[], None]] = None
        self.on_release: Optional[Callable[[], None]] = None
    
    @property
    def is_captured(self) -> bool:
        return self._captured
    
    def start_capture(self, screen_center: Tuple[int, int]) -> None:
        self._captured = True
        self._center = screen_center
        self._last_pos = None
        if self.on_capture:
            self.on_capture()
    
    def end_capture(self) -> None:
        self._captured = False
        self._center = None
        self._last_pos = None
        if self.on_release:
            self.on_release()
    
    def process_mouse_move(self, current_pos: Tuple[float, float]) -> Tuple[float, float]:
        if not self._captured or not self._center:
            self._last_pos = current_pos
            return (0.0, 0.0)
        
        cx, cy = self._center
        mx, my = current_pos
        
        dx = mx - cx
        dy = my - cy
        
        if abs(dx) > 1.0 or abs(dy) > 1.0:
            return (dx * self.sensitivity, dy * self.sensitivity)
        
        return (0.0, 0.0)
    
    def calculate_rotation(self, dx_pixels: float, dy_pixels: float) -> Tuple[float, float]:
        yaw_delta = -dx_pixels * self.sensitivity
        
        pitch_factor = -1.0 if self.invert_y else 1.0
        pitch_delta = dy_pixels * self.sensitivity * pitch_factor
        
        return (yaw_delta, pitch_delta)
    
    def get_warp_position(self) -> Optional[Tuple[int, int]]:
        return self._center if self._captured else None


def create_wx_camera_controller(
    canvas,
    core,
    sensitivity: float = 0.002,
) -> FPSCameraController:
    """Create FPS camera controller for wxPython."""
    controller = FPSCameraController(sensitivity=sensitivity)
    
    def on_rotate(yaw_delta: float, pitch_delta: float) -> None:
        if core and hasattr(core, 'rotate_player'):
            core.rotate_player(yaw_delta)
        if core and hasattr(core, 'tilt_camera'):
            core.tilt_camera(pitch_delta)
    
    def on_capture() -> None:
        try:
            canvas.SetCursor(wx.Cursor(wx.CURSOR_BLANK))
            if not canvas.HasCapture():
                canvas.CaptureMouse()
        except Exception:
            pass
    
    def on_release() -> None:
        try:
            canvas.SetCursor(wx.Cursor(wx.CURSOR_ARROW))
            if canvas.HasCapture():
                canvas.ReleaseMouse()
        except Exception:
            pass
    
    controller.on_rotate = on_rotate
    controller.on_capture = on_capture
    controller.on_release = on_release
    return controller


def create_qt_camera_controller(
    widget,
    core,
    sensitivity: float = 0.002,
) -> FPSCameraController:
    controller = FPSCameraController(sensitivity=sensitivity)
    from PySide6.QtGui import Qt
    
    def on_rotate(yaw_delta: float, pitch_delta: float) -> None:
        if core and hasattr(core, 'rotate_player'):
            core.rotate_player(yaw_delta)
        if core and hasattr(core, 'tilt_camera'):
            core.tilt_camera(pitch_delta)
    
    def on_capture() -> None:
        try:
            widget.setCursor(Qt.BlankCursor)
        except Exception:
            pass
    
    def on_release() -> None:
        try:
            widget.setCursor(Qt.ArrowCursor)
        except Exception:
            pass
    
    controller.on_rotate = on_rotate
    controller.on_capture = on_capture
    controller.on_release = on_release
    return controller


def create_kivy_camera_controller(
    window,
    core,
    sensitivity: float = 0.002,
) -> FPSCameraController:
    controller = FPSCameraController(sensitivity=sensitivity)
    from kivy.core.window import Window
    
    def on_rotate(yaw_delta: float, pitch_delta: float) -> None:
        if core and hasattr(core, 'rotate_player'):
            core.rotate_player(yaw_delta)
        if core and hasattr(core, 'tilt_camera'):
            core.tilt_camera(pitch_delta)
    
    def on_capture() -> None:
        try:
            Window.show_cursor = False
        except Exception:
            pass
    
    def on_release() -> None:
        try:
            Window.show_cursor = True
        except Exception:
            pass
    
    controller.on_rotate = on_rotate
    controller.on_capture = on_capture
    controller.on_release = on_release
    return controller
