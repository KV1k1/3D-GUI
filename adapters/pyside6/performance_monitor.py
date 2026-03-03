import time
import os
from typing import Optional, Dict, Any
from collections import deque
import psutil


class PerformanceMonitor:
    def __init__(self):
        self.frame_times = deque(maxlen=300)
        self.last_frame_time = time.perf_counter()
        self.fps_history = deque(maxlen=300)

        self.input_events = deque(maxlen=100)
        self.input_latencies = deque(maxlen=100)

        self.process = psutil.Process(os.getpid())
        self.peak_memory = 0
        self.memory_samples = deque(maxlen=60)

        self.scene_data = {
            'walls_rendered': 0,
            'coins': 0,
            'ghosts': 0,
            'spike_traps': 0,
            'moving_platforms': 0,
            'particle_systems': False
        }

        self.frozen_stats: Optional[Dict[str, Any]] = None

        self.resolution = (0, 0)

        self._stable_fps_value: int = 0
        self._stable_fps_next_update_t: float = 0.0

    def avg_fps(self) -> float:
        if not self.fps_history:
            return 0.0
        return float(sum(self.fps_history) / len(self.fps_history))

    def current_fps(self) -> float:
        if not self.fps_history:
            return 0.0
        return float(self.fps_history[-1])

    def stable_fps(self, *, update_interval_s: float = 2.5) -> int:
        now = time.perf_counter()
        if now < float(self._stable_fps_next_update_t or 0.0):
            return int(self._stable_fps_value or 0)

        latest = int(round(self.current_fps()))
        if latest != int(self._stable_fps_value or 0):
            self._stable_fps_value = int(latest)

        self._stable_fps_next_update_t = now + float(update_interval_s)
        return int(self._stable_fps_value or 0)

    def avg_input_latency_ms(self) -> float:
        if not self.input_latencies:
            return 0.0
        return float((sum(self.input_latencies) / len(self.input_latencies)) * 1000.0)

    def current_ram_mb(self) -> float:
        try:
            return float(self.process.memory_info().rss / 1024 / 1024)
        except Exception:
            return 0.0

    def start_frame(self):
        self.last_frame_time = time.perf_counter()

    def end_frame(self):
        current_time = time.perf_counter()
        frame_time = current_time - self.last_frame_time
        self.frame_times.append(frame_time)

        if frame_time > 0:
            fps = 1.0 / frame_time
            self.fps_history.append(fps)

        if len(self.frame_times) % 60 == 0:
            self._sample_memory()

    def record_input_event(self, event_time: float):
        self.input_events.append(event_time)

    def record_input_response(self, response_time: float):
        if self.input_events:
            input_time = self.input_events.popleft()
            latency = response_time - input_time
            self.input_latencies.append(latency)

    def update_scene_data(self, **kwargs):
        for key, value in kwargs.items():
            if key in self.scene_data:
                self.scene_data[key] = value

    def set_resolution(self, width: int, height: int):
        self.resolution = (width, height)

    def end_gameplay(self):
        self.frozen_stats = self.get_performance_summary()

    def freeze_stats(self):
        if self.frozen_stats is None:
            self.frozen_stats = self.get_performance_summary()

    def _sample_memory(self):
        current_memory = self.process.memory_info().rss / 1024 / 1024
        self.memory_samples.append(current_memory)
        self.peak_memory = max(self.peak_memory, current_memory)

    def get_performance_summary(self) -> Dict[str, Any]:
        if self.fps_history:
            avg_fps = sum(self.fps_history) / len(self.fps_history)
            min_fps = min(self.fps_history)
            max_fps = max(self.fps_history)
        else:
            avg_fps = min_fps = max_fps = 0

        if self.frame_times:
            avg_frame_time = sum(self.frame_times) / \
                len(self.frame_times) * 1000
            worst_frame = max(self.frame_times) * 1000
        else:
            avg_frame_time = worst_frame = 0

        if self.input_latencies:
            avg_input_latency = sum(self.input_latencies) / \
                len(self.input_latencies) * 1000
        else:
            avg_input_latency = 0

        return {
            'framework': 'PySide6',
            'resolution': f"{self.resolution[0]}x{self.resolution[1]}",
            'performance': {
                'avg_fps': f"{avg_fps:.1f}",
                'min_fps': f"{min_fps:.1f}",
                'max_fps': f"{max_fps:.1f}",
                'avg_frame_time': f"{avg_frame_time:.1f}ms",
                'worst_frame': f"{worst_frame:.1f}ms"
            },
            'responsiveness': {
                'avg_input_latency': f"~{avg_input_latency:.1f}ms"
            },
            'memory': {
                'peak_ram_usage': f"{self.peak_memory:.1f}MB"
            },
            'scene_load': {
                'walls_rendered': str(self.scene_data['walls_rendered']),
                'coins': str(self.scene_data['coins']),
                'ghosts': str(self.scene_data['ghosts']),
                'spike_traps': str(self.scene_data['spike_traps']),
                'moving_platforms': str(self.scene_data['moving_platforms'])
            }
        }

    def format_summary_text(self, gameplay_metrics: Optional[Dict[str, Any]] = None) -> str:
        summary = self.frozen_stats if self.frozen_stats else self.get_performance_summary()

        text = "────────────────────────────────────\n"
        text += "        FRAMEWORK TEST SUMMARY\n"
        text += "────────────────────────────────────\n\n"

        text += f"Framework: {summary['framework']}\n"
        text += f"Resolution: {summary['resolution']}\n"
        text += "\n"

        text += "PERFORMANCE\n"
        perf = summary['performance']
        text += f"• Avg FPS: {perf['avg_fps']}\n"
        text += f"• Min FPS: {perf['min_fps']}\n"
        text += f"• Max FPS: {perf['max_fps']}\n"
        text += f"• Avg Frame Time: {perf['avg_frame_time']}\n"
        text += f"• Worst Frame: {perf['worst_frame']}\n\n"

        text += "RESPONSIVENESS\n"
        resp = summary['responsiveness']
        text += f"• Avg Input Latency: {resp['avg_input_latency']}\n\n"

        text += "MEMORY\n"
        mem = summary['memory']
        text += f"• Peak RAM Usage: {mem['peak_ram_usage']}\n\n"

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
