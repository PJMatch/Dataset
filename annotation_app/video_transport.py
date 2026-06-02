from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QWidget

SEGMENT_COLORS = [
    "#E57373",
    "#64B5F6",
    "#81C784",
    "#FFB74D",
    "#BA68C8",
    "#4DD0E1",
    "#FFD54F",
    "#F06292",
    "#7986CB",
    "#AED581",
]

SEGMENT_ALPHA = 72


class VideoTransport(QWidget):
    """Gloss track + thin scrub line + vertical playhead (editor-style)."""

    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(42)
        self.setMaximumHeight(42)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._margin = 6
        self._min = 0
        self._max = 0
        self._value = 0
        self._total_frames = 1
        self._segments = []
        self._dragging = False

    def setMinimum(self, value):
        self._min = value
        self._value = max(self._min, self._value)

    def setMaximum(self, value):
        self._max = value
        self._total_frames = max(1, value - self._min + 1)

    def minimum(self):
        return self._min

    def maximum(self):
        return self._max

    def setValue(self, value):
        value = max(self._min, min(self._max, value))
        if value != self._value:
            self._value = value
            self.update()

    def value(self):
        return self._value

    def set_total_frames(self, total):
        self._total_frames = max(1, total)

    def set_segments(self, segments):
        self._segments = list(segments)
        self.update()

    def _inner_width(self):
        return max(1, self.width() - 2 * self._margin)

    def _frame_to_x(self, frame):
        ratio = (frame - self._min) / max(1, self._max - self._min)
        return self._margin + int(ratio * self._inner_width())

    def _x_to_frame(self, x):
        inner = self._inner_width()
        ratio = max(0.0, min(1.0, (x - self._margin) / inner))
        return int(round(self._min + ratio * (self._max - self._min)))

    def _layout_metrics(self):
        h = self.height()
        scrub_y = h - 7
        bar_bottom = scrub_y - 1
        bar_top = 15
        return scrub_y, bar_top, bar_bottom

    def _draw_segment_label(self, painter, gloss, x1, x2, canvas_w):
        avail = x2 - x1 - 4
        if avail < 6:
            return

        for pt in (8, 7, 6):
            font = QFont()
            font.setPointSize(pt)
            font.setBold(True)
            fm = QFontMetrics(font)
            display = gloss
            while fm.horizontalAdvance(display) > avail and len(display) > 1:
                if len(display) <= 4:
                    display = "…"
                    break
                display = display[:-2] + "…"

            if fm.horizontalAdvance(display) <= avail:
                painter.setFont(font)
                painter.setPen(QPen(QColor(255, 255, 255, 160)))
                text_w = fm.horizontalAdvance(display)
                lx = max(
                    self._margin,
                    min(
                        x1 + (x2 - x1 - text_w) // 2,
                        canvas_w - self._margin - text_w,
                    ),
                )
                painter.drawText(lx, 11, display)
                return

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        scrub_y, bar_top, bar_bottom = self._layout_metrics()

        painter.fillRect(0, 0, w, self.height(), QColor("#252525"))

        for i, (gloss, start, end) in enumerate(self._segments):
            if end <= start:
                continue
            x1 = self._frame_to_x(start)
            x2 = self._frame_to_x(end)
            if x2 <= x1:
                x2 = x1 + 1

            color = QColor(SEGMENT_COLORS[i % len(SEGMENT_COLORS)])
            color.setAlpha(SEGMENT_ALPHA)
            painter.fillRect(x1, bar_top, x2 - x1, bar_bottom - bar_top, color)
            self._draw_segment_label(painter, gloss, x1, x2, w)

        painter.setPen(QPen(QColor("#5a5a5a"), 1))
        painter.drawLine(self._margin, scrub_y, w - self._margin, scrub_y)

        if self._max > self._min:
            px = self._frame_to_x(self._value)
            painter.setPen(QPen(QColor("#f5f5f5"), 2))
            painter.drawLine(px, bar_top - 2, px, scrub_y + 2)

        painter.end()

    def _seek(self, x):
        frame = self._x_to_frame(int(x))
        if frame != self._value:
            self._value = frame
            self.update()
            self.valueChanged.emit(frame)

    def mousePressEvent(self, event):
        if not self.isEnabled() or event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        self._seek(event.position().x())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._seek(event.position().x())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()
