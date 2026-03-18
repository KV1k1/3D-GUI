"""
Improved PDF Export with ReportLab
==================================
Better PDF export that handles special characters properly and includes system information.
Uses ReportLab for proper Unicode support and professional formatting.
"""

import os
import time
from typing import Optional, Dict, Any
from datetime import datetime

# Try to import ReportLab, fall back to basic version if not available
try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    
    # Try to register a better font if available
    try:
        # Try to use a system font that supports more characters
        pdfmetrics.registerFont(TTFont('Arial', 'arial.ttf'))
        DEFAULT_FONT = 'Arial'
    except:
        DEFAULT_FONT = 'Helvetica'
    
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    print("ReportLab is required for PDF generation. Install with: pip install reportlab>=4.0.0")

# Import the basic PDF export as fallback
try:
    from .pdf_export_basic import export_performance_pdf as basic_export_performance_pdf
except ImportError:
    basic_export_performance_pdf = None


class SystemInfoCollector:
    """Collects system information from all frameworks"""
    
    def __init__(self):
        self.system_info = {}
        self.texture_load_time = None
    
    def record_opengl_info(self, vendor: str = None, renderer: str = None, version: str = None):
        """Record OpenGL information"""
        if vendor:
            self.system_info['opengl_vendor'] = str(vendor).strip("b'")
        if renderer:
            self.system_info['opengl_renderer'] = str(renderer).strip("b'")
        if version:
            self.system_info['opengl_version'] = str(version).strip("b'")
    
    def record_texture_load_time(self, load_time: float):
        """Record texture loading time"""
        self.system_info['texture_load_time'] = f"{load_time:.2f}s"
    
    def get_user_friendly_info(self) -> Dict[str, str]:
        """Convert system info to user-friendly format"""
        friendly_info = {}
        
        # Graphics information
        if 'opengl_renderer' in self.system_info:
            friendly_info['Graphics Card'] = self.system_info['opengl_renderer']
        
        if 'opengl_version' in self.system_info:
            friendly_info['OpenGL Version'] = self.system_info['opengl_version']
        
        if 'opengl_vendor' in self.system_info:
            friendly_info['Graphics Vendor'] = self.system_info['opengl_vendor']
        
        # Performance information
        if 'texture_load_time' in self.system_info:
            friendly_info['Texture Loading Time'] = self.system_info['texture_load_time']
        
        return friendly_info


# Global system info collector
_system_collector = SystemInfoCollector()


def get_system_collector() -> SystemInfoCollector:
    """Get the global system info collector"""
    return _system_collector


def export_performance_pdf_improved(
    *,
    framework: str,
    level_id: str,
    performance_data: Dict[str, Any],
    gameplay_metrics: Optional[Dict[str, Any]] = None,
    out_dir: Optional[str] = None,
) -> str:
    """
    Export performance data to PDF with improved formatting and system info.
    
    Args:
        framework: Framework name (Kivy, PySide6, wxPython, etc.)
        level_id: Level identifier
        performance_data: Performance summary from PerformanceMonitor.get_performance_summary()
        gameplay_metrics: Optional gameplay statistics
        out_dir: Output directory for the PDF
    
    Returns:
        Path to the generated PDF file
    """
    if not REPORTLAB_AVAILABLE:
        print("ReportLab is required for PDF generation. Install with: pip install reportlab>=4.0.0")
        raise ImportError("ReportLab is required for PDF generation")
    
    framework = str(framework or "").strip().lower() or "unknown"
    level_id = str(level_id or "").strip().lower() or "level"
    out_dir = os.path.abspath(out_dir or os.path.join(os.getcwd(), 'performance_reports'))
    os.makedirs(out_dir, exist_ok=True)
    
    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"performance_{level_id}_{framework}_{timestamp}.pdf"
    path = os.path.join(out_dir, filename)
    
    # Create the PDF document
    doc = SimpleDocTemplate(path, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=1,  # Center
        textColor=colors.darkblue
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=12,
        textColor=colors.darkblue
    )
    
    # Title
    story.append(Paragraph("Performance Report", title_style))
    story.append(Spacer(1, 12))
    
    # Framework and level info
    info_data = [
        ['Framework:', framework.capitalize()],
        ['Level:', level_id.upper()],
        ['Generated:', datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    ]
    
    info_table = Table(info_data, colWidths=[1.5*inch, 3*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 20))
    
    # System Information
    system_info = _system_collector.get_user_friendly_info()
    if system_info:
        story.append(Paragraph("System Information", heading_style))
        
        sys_data = [[key, value] for key, value in system_info.items()]
        sys_table = Table(sys_data, colWidths=[2*inch, 3*inch])
        sys_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(sys_table)
        story.append(Spacer(1, 20))
    
    # Performance Metrics
    story.append(Paragraph("Performance Metrics", heading_style))
    
    perf = performance_data.get('performance', {})
    perf_data = [
        ['Average FPS:', perf.get('avg_fps', 'N/A')],
        ['Minimum FPS:', perf.get('min_fps', 'N/A')],
        ['Maximum FPS:', perf.get('max_fps', 'N/A')],
        ['Average Frame Time:', perf.get('avg_frame_time', 'N/A')],
        ['Worst Frame Time:', perf.get('worst_frame', 'N/A')],
        ['FPS Stability:', perf.get('fps_stability', 'N/A')],
        ['Frame Drops (>33ms):', perf.get('frame_drops', 'N/A')],
        ['95th Percentile Frame Time:', perf.get('95th_percentile', 'N/A')],
    ]
    
    perf_table = Table(perf_data, colWidths=[2*inch, 1.5*inch])
    perf_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
        ('BACKGROUND', (1, 0), (1, -1), colors.white),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(perf_table)
    story.append(Spacer(1, 20))
    
    # Responsiveness
    resp = performance_data.get('responsiveness', {})
    if resp:
        story.append(Paragraph("Responsiveness", heading_style))
        resp_data = [[key.replace('_', ' ').title(), value] for key, value in resp.items()]
        resp_table = Table(resp_data, colWidths=[2*inch, 1.5*inch])
        resp_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgreen),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(resp_table)
        story.append(Spacer(1, 20))
    
    # Memory Usage
    memory = performance_data.get('memory', {})
    if memory:
        story.append(Paragraph("Memory Usage", heading_style))
        mem_data = [[key.replace('_', ' ').title(), value] for key, value in memory.items()]
        mem_table = Table(mem_data, colWidths=[2*inch, 1.5*inch])
        mem_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightyellow),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(mem_table)
        story.append(Spacer(1, 20))
    
    # Scene Information
    scene = performance_data.get('scene_load', {})
    if scene:
        story.append(Paragraph("Scene Information", heading_style))
        scene_data = [[key.replace('_', ' ').title(), value] for key, value in scene.items()]
        scene_table = Table(scene_data, colWidths=[2*inch, 1.5*inch])
        scene_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightcoral),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(scene_table)
        story.append(Spacer(1, 20))
    
    # Gameplay Metrics
    gameplay_data = performance_data.get('gameplay', {})
    if gameplay_data:
        story.append(Paragraph("Gameplay Statistics", heading_style))
        game_data = [[key.replace('_', ' ').title(), str(value)] for key, value in gameplay_data.items()]
        game_table = Table(game_data, colWidths=[2*inch, 1.5*inch])
        game_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lavender),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(game_table)
        story.append(Spacer(1, 20))
    
    # Additional Gameplay Metrics (from gameplay_metrics parameter)
    if gameplay_metrics:
        story.append(Paragraph("Additional Gameplay Statistics", heading_style))
        game_data = [[key.replace('_', ' ').title(), str(value)] for key, value in gameplay_metrics.items()]
        game_table = Table(game_data, colWidths=[2*inch, 1.5*inch])
        game_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.orange),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(game_table)
    
    # Build PDF
    doc.build(story)
    return path


# Convenience function that matches the old interface
def export_performance_pdf(
    *,
    framework: str,
    level_id: str,
    text: Optional[str] = None,
    performance_data: Optional[Dict[str, Any]] = None,
    gameplay_metrics: Optional[Dict[str, Any]] = None,
    out_dir: Optional[str] = None,
) -> str:
    """
    Export performance data to PDF.
    
    This function provides backward compatibility while using the improved export.
    """
    if not REPORTLAB_AVAILABLE:
        print("ReportLab is required for PDF generation. Install with: pip install reportlab>=4.0.0")
        raise ImportError("ReportLab is required for PDF generation")
    
    if performance_data is None:
        # Create minimal performance data
        performance_data = {
            'framework': framework,
            'performance': {},
            'responsiveness': {},
            'memory': {},
            'scene_load': {},
        }
    
    return export_performance_pdf_improved(
        framework=framework,
        level_id=level_id,
        performance_data=performance_data,
        gameplay_metrics=gameplay_metrics,
        out_dir=out_dir or os.path.join(os.getcwd(), 'performance_reports')
    )
