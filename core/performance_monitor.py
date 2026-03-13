import time
import os
from typing import Optional, Dict, Any, Union
from collections import deque
import psutil


class PerformanceMonitor:
    """
    Unified performance monitor compatible with both PySide6 and wxPython frontends.

    Usage difference between frameworks:

    PySide6:
        - Call start_frame() before rendering, end_frame() after rendering.
        - record_input_event(event_time: float)        — single float, no key code
        - record_input_response(response_time: float)  — single float, no key code

    wxPython:
        - Call tick() once per wx.Timer callback instead of start_frame/end_frame.
        - record_input_event(key_code: int, event_time: float)
        - record_input_response(key_code: int, response_time: float)

    Both frameworks share all other methods identically.
    """

    def __init__(self, framework: str = 'PySide6'):
        self.framework = str(framework)

        self.frame_times: deque = deque(maxlen=300)
        self.last_frame_time: float = time.perf_counter()
        self.fps_history: deque = deque(maxlen=300)

        # Input latency tracking.
        # PySide6: stores plain float timestamps.
        # wxPython: stores (key_code, timestamp) tuples.
        self.input_events: deque = deque(maxlen=100)
        self.input_latencies: deque = deque(maxlen=100)

        self.process = psutil.Process(os.getpid())
        self.peak_memory: float = 0.0
        self.memory_samples: deque = deque(maxlen=60)

        self.scene_data: Dict[str, Any] = {
            'walls_rendered': 0,
            'coins': 0,
            'ghosts': 0,
            'spike_traps': 0,
            'moving_platforms': 0,
            'particle_systems': False,
        }

        self.frozen_stats: Optional[Dict[str, Any]] = None
        self.resolution: tuple = (0, 0)

        self._stable_fps_value: int = 0
        self._stable_fps_next_update_t: float = 0.0

    # ------------------------------------------------------------------
    # Frame timing — PySide6 path
    # ------------------------------------------------------------------

    def start_frame(self) -> None:
        """PySide6: call at the start of paintGL before rendering."""
        self.last_frame_time = time.perf_counter()

    def end_frame(self) -> None:
        """PySide6: call at the end of paintGL after rendering."""
        now = time.perf_counter()
        self._record_interval(now - self.last_frame_time)
        if len(self.frame_times) % 60 == 0:
            self._sample_memory()

    # ------------------------------------------------------------------
    # Frame timing — wxPython path
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """wxPython: call once per wx.Timer callback (game tick).
        Measures tick-to-tick wall time as the true frame interval."""
        now = time.perf_counter()
        self._record_interval(now - self.last_frame_time)
        self.last_frame_time = now
        self._sample_memory()

    # ------------------------------------------------------------------
    # Shared interval recording
    # ------------------------------------------------------------------

    def _record_interval(self, interval: float) -> None:
        # Ignore the very first call (large interval since __init__)
        # and any stalls longer than 1 s (minimised window, debugger, etc.)
        if 0.001 < interval < 1.0:
            self.frame_times.append(interval)
            self.fps_history.append(max(0.1, min(1000.0, 1.0 / interval)))

    # ------------------------------------------------------------------
    # FPS helpers
    # ------------------------------------------------------------------

    def avg_fps(self) -> float:
        if not self.fps_history:
            return 0.0
        return float(sum(self.fps_history) / len(self.fps_history))

    def current_fps(self) -> float:
        if not self.fps_history:
            return 0.0
        return float(self.fps_history[-1])

    def stable_fps(self, *, update_interval_s: float = 2.5) -> int:
        """Returns a smoothed FPS value that only updates every update_interval_s seconds."""
        now = time.perf_counter()
        if now < float(self._stable_fps_next_update_t):
            return int(self._stable_fps_value)
        self._stable_fps_value = int(round(self.current_fps()))
        self._stable_fps_next_update_t = now + float(update_interval_s)
        return int(self._stable_fps_value)

    # ------------------------------------------------------------------
    # Input latency — overloaded for both frameworks
    # ------------------------------------------------------------------

    def record_input_event(self, event_time_or_key: Union[float, int],
                           event_time: Optional[float] = None) -> None:
        """Record a key-press event.

        PySide6: record_input_event(event_time: float)
        wxPython: record_input_event(key_code: int, event_time: float)
        """
        if event_time is None:
            # PySide6: single float timestamp
            self.input_events.append(float(event_time_or_key))
        else:
            # wxPython: (key_code, timestamp) tuple
            self.input_events.append((int(event_time_or_key), float(event_time)))

    def record_input_response(self, response_time_or_key: Union[float, int],
                              response_time: Optional[float] = None) -> None:
        """Record that input was processed this frame.

        PySide6: record_input_response(response_time: float)
        wxPython: record_input_response(key_code: int, response_time: float)
        """
        if response_time is None:
            # PySide6: pair with oldest plain-float event entry
            resp_t = float(response_time_or_key)
            for i in range(len(self.input_events)):
                entry = self.input_events[i]
                if isinstance(entry, float):
                    latency = resp_t - entry
                    if 0.0 <= latency < 2.0:
                        self.input_latencies.append(latency)
                    try:
                        del self.input_events[i]
                    except Exception:
                        pass
                    return
        else:
            # wxPython: find most recent matching (key_code, timestamp) tuple
            key_code = int(response_time_or_key)
            resp_t = float(response_time)
            for i in range(len(self.input_events) - 1, -1, -1):
                entry = self.input_events[i]
                if isinstance(entry, tuple) and entry[0] == key_code:
                    latency = resp_t - float(entry[1])
                    if 0.0 <= latency < 2.0:
                        self.input_latencies.append(latency)
                    try:
                        del self.input_events[i]
                    except Exception:
                        pass
                    return

    def avg_input_latency_ms(self) -> float:
        if not self.input_latencies:
            return 0.0
        return float(sum(self.input_latencies) / len(self.input_latencies)) * 1000.0

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def current_ram_mb(self) -> float:
        try:
            return float(self.process.memory_info().rss) / (1024.0 * 1024.0)
        except Exception:
            return 0.0

    def _sample_memory(self) -> None:
        try:
            mb = float(self.process.memory_info().rss) / (1024.0 * 1024.0)
            self.memory_samples.append(mb)
            if mb > self.peak_memory:
                self.peak_memory = mb
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Scene / resolution metadata
    # ------------------------------------------------------------------

    def update_scene_data(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if key in self.scene_data:
                self.scene_data[key] = value

    def set_resolution(self, width: int, height: int) -> None:
        self.resolution = (int(width), int(height))

    # ------------------------------------------------------------------
    # Stats freeze / summary
    # ------------------------------------------------------------------

    def end_gameplay(self) -> None:
        """Alias for freeze_stats — kept for PySide6 compatibility."""
        self.freeze_stats()

    def freeze_stats(self) -> None:
        if self.frozen_stats is None:
            self.frozen_stats = self.get_performance_summary()

    def get_performance_summary(self) -> Dict[str, Any]:
        if self.fps_history:
            avg_fps = sum(self.fps_history) / len(self.fps_history)
            min_fps = min(self.fps_history)
            max_fps = max(self.fps_history)
        else:
            avg_fps = min_fps = max_fps = 0.0

        if self.frame_times:
            avg_frame_time = sum(self.frame_times) / len(self.frame_times) * 1000.0
            worst_frame = max(self.frame_times) * 1000.0
        else:
            avg_frame_time = worst_frame = 0.0

        avg_input_latency = (
            sum(self.input_latencies) / len(self.input_latencies) * 1000.0
            if self.input_latencies else 0.0
        )

        return {
            'framework': self.framework,
            'resolution': f"{self.resolution[0]}x{self.resolution[1]}",
            'performance': {
                'avg_fps': f"{avg_fps:.1f}",
                'min_fps': f"{min_fps:.1f}",
                'max_fps': f"{max_fps:.1f}",
                'avg_frame_time': f"{avg_frame_time:.1f}ms",
                'worst_frame': f"{worst_frame:.1f}ms",
            },
            'responsiveness': {
                'avg_input_latency': f"~{avg_input_latency:.1f}ms",
            },
            'memory': {
                'peak_ram_usage': f"{self.peak_memory:.1f}MB",
            },
            'scene_load': {
                'walls_rendered': str(self.scene_data['walls_rendered']),
                'coins': str(self.scene_data['coins']),
                'ghosts': str(self.scene_data['ghosts']),
                'spike_traps': str(self.scene_data['spike_traps']),
                'moving_platforms': str(self.scene_data['moving_platforms']),
            },
        }

    def format_summary_text(self, gameplay_metrics: Optional[Dict[str, Any]] = None) -> str:
        summary = self.frozen_stats if self.frozen_stats else self.get_performance_summary()

        text  = "────────────────────────────────────\n"
        text += "        FRAMEWORK TEST SUMMARY\n"
        text += "────────────────────────────────────\n\n"
        text += f"Framework: {summary['framework']}\n"
        text += f"Resolution: {summary['resolution']}\n\n"

        text += "PERFORMANCE\n"
        perf = summary['performance']
        text += f"• Avg FPS: {perf['avg_fps']}\n"
        text += f"• Min FPS: {perf['min_fps']}\n"
        text += f"• Max FPS: {perf['max_fps']}\n"
        text += f"• Avg Frame Time: {perf['avg_frame_time']}\n"
        text += f"• Worst Frame: {perf['worst_frame']}\n\n"

        text += "RESPONSIVENESS\n"
        text += f"• Avg Input Latency: {summary['responsiveness']['avg_input_latency']}\n\n"

        text += "MEMORY\n"
        text += f"• Peak RAM Usage: {summary['memory']['peak_ram_usage']}\n\n"

        text += "SCENE LOAD\n"
        scene = summary['scene_load']
        text += f"• Walls Rendered: {scene['walls_rendered']}\n"
        text += f"• Coins: {scene['coins']}\n"
        text += f"• Ghosts: {scene['ghosts']}\n"
        text += f"• Spike Traps: {scene['spike_traps']}\n"
        text += f"• Moving Platforms: {scene['moving_platforms']}\n\n"

        if gameplay_metrics:
            text += "GAMEPLAY\n"
            for key, value in gameplay_metrics.items():
                text += f"• {key}: {value}\n"
            text += "\n"

        text += "────────────────────────────────────\n"
        text += "Press ESC to exit\n"
        text += "────────────────────────────────────"

        return text