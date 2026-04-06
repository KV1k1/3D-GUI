import time
import os
import math
from typing import Optional, Dict, Any, Union
from collections import deque
import psutil
import statistics


class PerformanceMonitor:
    def __init__(self, framework: str = 'PySide6'):
        self.framework = str(framework)

        self.fps_history: deque = deque(maxlen=300)
        self.display_fps_history: deque = deque(maxlen=300)
        self.last_frame_time: float = time.perf_counter()
        self._last_display_frame_time: float = time.perf_counter()

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
        self._stable_display_fps_value: int = 0
        self._stable_display_fps_next_update_t: float = 0.0
        self._first_frame: bool = True

        self._startup_begin: float = time.perf_counter()
        self.startup_time_ms: Optional[float] = None

        self.texture_load_time_ms: Optional[float] = None

        self.texture_generation_times: deque = deque(maxlen=100)

        self._pending_input_time: Optional[float] = None
        self.input_latencies: deque = deque(maxlen=200)

    def record_startup_time(self, startup_ms: float) -> None:
        self.startup_time_ms = float(startup_ms)

    def record_frame(self, is_pause_frame: bool = False) -> None:
        now = time.perf_counter()
        if self._first_frame:
            self._first_frame = False
        else:
            interval = now - self.last_frame_time
            if not is_pause_frame:
                self._record_interval(interval)
        self.last_frame_time = now

        display_interval = now - self._last_display_frame_time
        if display_interval > 0:
            display_fps = 1.0 / display_interval
            self.display_fps_history.append(display_fps)
        self._last_display_frame_time = now

        self._sample_memory()

    def _record_interval(self, interval: float) -> None:
        fps = 1.0 / interval
        self.fps_history.append(fps)

    def avg_fps(self) -> float:
        if not self.fps_history:
            return 0.0
        return float(sum(self.fps_history) / len(self.fps_history))

    def median_fps(self) -> float:
        if not self.fps_history:
            return 0.0
        sorted_fps = sorted(self.fps_history)
        median_index = len(sorted_fps) // 2
        if len(sorted_fps) % 2 == 1:
            return float(sorted_fps[median_index])
        else:
            return float((sorted_fps[median_index - 1] + sorted_fps[median_index]) / 2.0)

    def current_fps(self) -> float:
        if not self.fps_history:
            return 0.0
        recent_fps = list(self.fps_history)[-10:]
        return float(sum(recent_fps) / len(recent_fps))

    def stable_fps(self, update_interval_s: float = 1) -> int:
        now = time.perf_counter()
        if now < float(self._stable_fps_next_update_t):
            return int(self._stable_fps_value)
        self._stable_fps_value = int(round(self.current_fps()))
        self._stable_fps_next_update_t = now + float(update_interval_s)
        return int(self._stable_fps_value)

    def current_display_fps(self) -> float:
        if not self.display_fps_history:
            return 0.0
        recent_fps = list(self.display_fps_history)[-10:]
        return float(sum(recent_fps) / len(recent_fps))

    def stable_display_fps(self, update_interval_s: float = 1) -> int:
        now = time.perf_counter()
        if now < float(self._stable_display_fps_next_update_t):
            return int(self._stable_display_fps_value)
        self._stable_display_fps_value = int(round(self.current_display_fps()))
        self._stable_display_fps_next_update_t = now + float(update_interval_s)
        return int(self._stable_display_fps_value)

    def record_input_event(self) -> None:
        self._pending_input_time = time.perf_counter()

    def record_input_processed(self) -> None:
        if self._pending_input_time is not None:
            latency = time.perf_counter() - self._pending_input_time
            if 0.0 < latency < 0.5:
                self.input_latencies.append(latency)
            self._pending_input_time = None

    def median_input_latency_ms(self) -> float:
        if not self.input_latencies:
            return 0.0
        return statistics.median(self.input_latencies) * 1000.0

    def record_texture_load_time(self, duration_ms: float) -> None:
        self.texture_load_time_ms = float(duration_ms)

    def record_texture_generation(self, duration_ms: float) -> None:
        self.texture_generation_times.append(float(duration_ms))

    def get_texture_generation_avg(self) -> Optional[float]:
        if not self.texture_generation_times:
            return None
        return statistics.mean(self.texture_generation_times)

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

    def update_scene_data(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if key in self.scene_data:
                self.scene_data[key] = value

    def set_resolution(self, width: int, height: int) -> None:
        self.resolution = (int(width), int(height))

    def end_gameplay(self) -> None:
        self.freeze_stats()

    def freeze_stats(self) -> None:
        if self.frozen_stats is None:
            self.frozen_stats = self.get_performance_summary()

    def get_performance_summary(self) -> Dict[str, Any]:
        avg_fps = self.avg_fps()
        current_fps = self.current_fps()

        if self.fps_history:
            filtered_fps = [fps for fps in self.fps_history if 2 <= fps <= 200]
            if filtered_fps:
                min_fps = min(filtered_fps)
                max_fps = max(filtered_fps)
            else:
                min_fps = max_fps = current_fps
        else:
            avg_fps = min_fps = max_fps = 0.0

        result = {
            'framework': self.framework,
            'resolution': f"{self.resolution[0]}x{self.resolution[1]}",
            'performance': {
                'avg_fps': f"{avg_fps:.1f}",
                'min_fps': f"{min_fps:.1f}",
                'max_fps': f"{max_fps:.1f}",
            },
            'memory': {
                'peak_ram_usage': f"{self.peak_memory:.1f}MB",
            },
            'startup': {
                'startup_time': f"{self.startup_time_ms:.1f}ms" if self.startup_time_ms is not None else "N/A",
            },
            'scene_load': {
                'walls_rendered': str(self.scene_data['walls_rendered']),
                'coins': str(self.scene_data['coins']),
                'ghosts': str(self.scene_data['ghosts']),
                'spike_traps': str(self.scene_data['spike_traps']),
                'moving_platforms': str(self.scene_data['moving_platforms']),
            },
        }

        if self.texture_load_time_ms is not None:
            result['texture_loading'] = {
                'load_time_ms': f"{self.texture_load_time_ms:.2f}",
            }

        tex_avg = self.get_texture_generation_avg()
        if tex_avg is not None:
            result['text_rendering'] = {
                'avg_texture_time_ms': f"{tex_avg:.2f}",
            }

        median_latency = self.median_input_latency_ms()
        if median_latency > 0:
            result['input_latency'] = {
                'median_latency_ms': f"{median_latency:.2f}",
            }

        return result

    def format_summary_text(self) -> str:
        summary = self.frozen_stats if self.frozen_stats else self.get_performance_summary()

        text = "────────────────────────────────────\n"
        text += "        FRAMEWORK TEST SUMMARY\n"
        text += "────────────────────────────────────\n\n"
        text += f"Framework: {summary['framework']}\n"
        text += f"Resolution: {summary['resolution']}\n\n"

        text += "PERFORMANCE\n"
        perf = summary['performance']
        text += f"• Avg FPS: {perf['avg_fps']}\n"
        text += f"• Min FPS: {perf['min_fps']}\n"
        text += f"• Max FPS: {perf['max_fps']}\n\n"

        text += "MEMORY\n"
        text += f"• Peak RAM Usage: {summary['memory']['peak_ram_usage']}\n\n"

        text += "STARTUP\n"
        text += f"• Startup Time: {summary['startup']['startup_time']}\n\n"

        # Input latency — framework event dispatch + loop scheduling
        if 'input_latency' in summary:
            lat = summary['input_latency']
            text += "INPUT LATENCY\n"
            text += f"• Median: {lat['median_latency_ms']}ms\n\n"

        # Text rendering performance — framework-specific
        if 'text_rendering' in summary:
            tex = summary['text_rendering']
            text += "TEXT RENDERING\n"
            text += f"• Avg Texture Time: {tex['avg_texture_time_ms']}ms\n\n"

        # Texture loading time
        if 'texture_loading' in summary:
            tex_load = summary['texture_loading']
            text += "TEXTURE LOADING\n"
            text += f"• Load Time: {tex_load['load_time_ms']}ms\n\n"

        text += "SCENE LOAD\n"
        scene = summary['scene_load']
        text += f"• Walls Rendered: {scene['walls_rendered']}\n"
        text += f"• Coins: {scene['coins']}\n"
        text += f"• Ghosts: {scene['ghosts']}\n"
        text += f"• Spike Traps: {scene['spike_traps']}\n"
        text += f"• Moving Platforms: {scene['moving_platforms']}\n\n"

        return text
