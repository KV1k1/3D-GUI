

import os
import time
from datetime import datetime
from typing import Dict, Any, Optional

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

try:
    pdfmetrics.registerFont(TTFont('Arial', 'arial.ttf'))
    DEFAULT_FONT = 'Arial'
except:
    DEFAULT_FONT = 'Helvetica'


class SystemInfoCollector:
    def __init__(self):
        self.system_info = {}

    def record_opengl_info(self, vendor: str = None, renderer: str = None, version: str = None):
        if vendor:
            self.system_info['opengl_vendor'] = str(vendor).strip("b'")
        if renderer:
            self.system_info['opengl_renderer'] = str(renderer).strip("b'")
        if version:
            self.system_info['opengl_version'] = str(version).strip("b'")

    def get_user_friendly_info(self) -> Dict[str, str]:
        friendly_info = {}
        if 'opengl_renderer' in self.system_info:
            friendly_info['Graphics Card'] = self.system_info['opengl_renderer']
        if 'opengl_version' in self.system_info:
            friendly_info['OpenGL Version'] = self.system_info['opengl_version']
        if 'opengl_vendor' in self.system_info:
            friendly_info['Graphics Vendor'] = self.system_info['opengl_vendor']
        return friendly_info


_system_collector = SystemInfoCollector()


def get_system_collector() -> SystemInfoCollector:
    return _system_collector


def export_performance_pdf_improved(
    filepath: str,
    performance_data: Dict[str, Any],
    gameplay_metrics: Optional[Dict[str, Any]] = None,
) -> bool:
    if not REPORTLAB_AVAILABLE:
        return False

    doc = SimpleDocTemplate(filepath, pagesize=letter)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=1,
        textColor=colors.darkblue
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        spaceAfter=12,
        textColor=colors.darkblue
    )

    story.append(Paragraph("Performance Report", title_style))
    story.append(Spacer(1, 12))

    info_data = [
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

    story.append(Paragraph("Performance Metrics", heading_style))

    perf = performance_data.get('performance', {})
    perf_data = [
        ['Average FPS:', perf.get('avg_fps', 'N/A')],
        ['Minimum FPS:', perf.get('min_fps', 'N/A')],
        ['Maximum FPS:', perf.get('max_fps', 'N/A')],
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

    latency = performance_data.get('input_latency', {})
    if latency:
        story.append(Paragraph("Input Latency", heading_style))
        lat_data = [[key.replace('_', ' ').title(), value]
                    for key, value in latency.items()]
        lat_table = Table(lat_data, colWidths=[2*inch, 1.5*inch])
        lat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgreen),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(lat_table)
        story.append(Spacer(1, 20))

    memory = performance_data.get('memory', {})
    if memory:
        story.append(Paragraph("Memory Usage", heading_style))
        mem_data = [[key.replace('_', ' ').title(), value]
                    for key, value in memory.items()]
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

    startup = performance_data.get('startup', {})
    if startup:
        story.append(Paragraph("Startup", heading_style))
        startup_data = [[key.replace('_', ' ').title(), value]
                        for key, value in startup.items()]
        startup_table = Table(startup_data, colWidths=[2*inch, 1.5*inch])
        startup_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgreen),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(startup_table)
        story.append(Spacer(1, 20))

    tex_load = performance_data.get('texture_loading', {})
    if tex_load:
        story.append(Paragraph("Texture Loading", heading_style))
        tex_load_data = [[key.replace('_', ' ').title(), value]
                         for key, value in tex_load.items()]
        tex_load_table = Table(tex_load_data, colWidths=[2*inch, 1.5*inch])
        tex_load_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightcyan),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(tex_load_table)
        story.append(Spacer(1, 20))

    text_render = performance_data.get('text_rendering', {})
    if text_render:
        story.append(Paragraph("Text Rendering", heading_style))
        tex_data = [[key.replace('_', ' ').title(), value]
                    for key, value in text_render.items()]
        tex_table = Table(tex_data, colWidths=[2*inch, 1.5*inch])
        tex_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightcoral),
            ('BACKGROUND', (1, 0), (1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), DEFAULT_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(tex_table)
        story.append(Spacer(1, 20))

    doc.build(story)
    return filepath


def export_performance_pdf(
    *,
    framework: str,
    level_id: str,
    text: Optional[str] = None,
    performance_data: Optional[Dict[str, Any]] = None,
    gameplay_metrics: Optional[Dict[str, Any]] = None,
    out_dir: Optional[str] = None,
) -> str:

    # Requires ReportLab

    if performance_data is None:
        performance_data = {
            'framework': framework,
            'performance': {},
            'responsiveness': {},
            'memory': {},
            'scene_load': {},
        }

    if out_dir is None:
        out_dir = os.path.join(os.getcwd(), 'performance_reports')
    os.makedirs(out_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{framework}_{level_id}_{timestamp}.pdf"
    filepath = os.path.join(out_dir, filename)

    return export_performance_pdf_improved(
        filepath=filepath,
        performance_data=performance_data,
        gameplay_metrics=gameplay_metrics,
    )
