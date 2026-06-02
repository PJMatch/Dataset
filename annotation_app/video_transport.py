from PyQt6.QtCore import QPoint, Qt, pyqtSignal
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

SEGMENT_ALPHA = 68
SEGMENT_ALPHA_ACTIVE = 118
SEGMENT_RADIUS = 4
LIFT_OFFSET_Y = 7
BOUNDARY_HIT_PX = 8
EDGE_HIT_PX = 7
SWAP_DRAG_THRESHOLD_PX = 28


class VideoTransport(QWidget):
    """Gloss track + scrub line; drag boundaries; RMB select block, drag to swap gloss order."""

    valueChanged = pyqtSignal(int)
    boundaryChanged = pyqtSignal(int, int)
    glossesSwapped = pyqtSignal(int, int)
    segmentContextMenuRequested = pyqtSignal(int, int, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(42)
        self.setMaximumHeight(42)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self._margin = 6
        self._min = 0
        self._max = 0
        self._value = 0
        self._total_frames = 1
        self._segments = []
        self._gloss_colors = {}
        self._boundaries = []
        self._dragging_scrub = False
        self._selected_segment = None
        self._segment_swap_drag = False
        self._segment_swap_index = None
        self._segment_swap_start_x = 0.0
        self._segment_swap_dx = 0.0
        self._dragging_stamp_index = None

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
        if self._selected_segment is not None and self._selected_segment >= len(
            self._segments
        ):
            self._selected_segment = None
        self.update()

    def set_gloss_colors(self, gloss_to_index):
        self._gloss_colors = dict(gloss_to_index)
        self.update()

    def _color_index_for_gloss(self, gloss):
        return self._gloss_colors.get(gloss, 0) % len(SEGMENT_COLORS)

    def set_boundaries(self, frames):
        self._boundaries = list(frames)
        self.update()

    def clear_segment_selection(self):
        self._selected_segment = None
        self.update()

    def set_selected_segment(self, index):
        self._selected_segment = index
        self.update()

    def selected_segment(self):
        return self._selected_segment

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

    def _segment_index_at(self, x):
        if not self._segments:
            return None
        frame = self._x_to_frame(x)
        for i, (_gloss, start, end) in enumerate(self._segments):
            if end <= start:
                continue
            if i == len(self._segments) - 1:
                if start <= frame <= end:
                    return i
            elif start <= frame < end:
                return i
        return None

    def _segment_hit_zone(self, x):
        seg = self._segment_index_at(x)
        if seg is None:
            return None, None
        _gloss, start, end = self._segments[seg]
        x1 = self._frame_to_x(start)
        x2 = self._frame_to_x(end)
        mx = int(x)
        if abs(mx - x1) <= EDGE_HIT_PX:
            return seg, "left"
        if seg + 1 < len(self._boundaries) and abs(mx - x2) <= EDGE_HIT_PX:
            return seg, "right"
        return seg, "center"

    def _stamp_index_for_zone(self, seg, zone):
        if zone == "left":
            return seg
        if zone == "right":
            return seg + 1
        return None

    def _is_selected(self, seg):
        return seg is not None and seg == self._selected_segment

    def _clamp_stamp_frame(self, index, frame):
        if index <= 0:
            lo = self._min
        else:
            lo = self._boundaries[index - 1] + 1
        if index + 1 < len(self._boundaries):
            hi = self._boundaries[index + 1] - 1
        else:
            hi = self._max
        return max(lo, min(hi, frame))

    def _update_hover_cursor(self, x):
        if self._dragging_stamp_index is not None or self._segment_swap_drag:
            return

        seg, zone = self._segment_hit_zone(x)
        if self._is_selected(seg) and zone in ("left", "right"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif self._is_selected(seg) and zone == "center" and len(self._segments) >= 2:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def _segment_geometry(self, start, end, bar_top, bar_bottom, offset_x=0, lift_y=0):
        x1 = self._frame_to_x(start) + offset_x
        x2 = self._frame_to_x(end) + offset_x
        if x2 <= x1:
            x2 = x1 + 1
        y = int(bar_top + lift_y)
        w = max(1, int(x2 - x1))
        h = max(1, int(bar_bottom - bar_top))
        return int(x1), y, w, h

    def _draw_segment_block(
        self,
        painter,
        color_index,
        x,
        y,
        width,
        height,
        alpha,
        outline=False,
    ):
        x = int(x)
        y = int(y)
        width = max(1, int(width))
        height = max(1, int(height))

        fill = QColor(SEGMENT_COLORS[color_index % len(SEGMENT_COLORS)])
        fill.setAlpha(alpha)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(
            x, y, width, height, SEGMENT_RADIUS, SEGMENT_RADIUS
        )

        if outline and width > 2 and height > 2:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
            painter.drawRoundedRect(
                x + 1,
                y + 1,
                width - 2,
                height - 2,
                SEGMENT_RADIUS - 1,
                SEGMENT_RADIUS - 1,
            )

    def _draw_segment_label(
        self, painter, gloss, x1, x2, canvas_w, lift_y=0, label_alpha=150
    ):
        avail = x2 - x1 - 6
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
                painter.setPen(QPen(QColor(255, 255, 255, label_alpha)))
                text_w = fm.horizontalAdvance(display)
                lx = max(
                    self._margin,
                    min(
                        x1 + (x2 - x1 - text_w) // 2,
                        canvas_w - self._margin - text_w,
                    ),
                )
                painter.drawText(lx, 11 + lift_y, display)
                return

    def _drag_offset_x(self, seg_index):
        _gloss, start, end = self._segments[seg_index]
        x1 = self._frame_to_x(start)
        x2 = self._frame_to_x(end)
        half = max(12, (x2 - x1) // 2)
        return int(max(-half, min(half, self._segment_swap_dx * 0.55)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        scrub_y, bar_top, bar_bottom = self._layout_metrics()
        drag_idx = self._segment_swap_index if self._segment_swap_drag else None

        painter.fillRect(0, 0, w, self.height(), QColor("#1e1e1e"))

        for i, (gloss, start, end) in enumerate(self._segments):
            if end <= start:
                continue
            if drag_idx == i:
                continue

            x, y, bw, bh = self._segment_geometry(start, end, bar_top, bar_bottom)
            is_selected = i == self._selected_segment and not self._segment_swap_drag
            alpha = SEGMENT_ALPHA_ACTIVE if is_selected else SEGMENT_ALPHA
            self._draw_segment_block(
                painter,
                self._color_index_for_gloss(gloss),
                x,
                y,
                bw,
                bh,
                alpha,
                outline=is_selected,
            )
            self._draw_segment_label(painter, gloss, x, x + bw, w)

        if drag_idx is not None and drag_idx < len(self._segments):
            gloss, start, end = self._segments[drag_idx]
            if end > start:
                ox, oy, bw, bh = self._segment_geometry(
                    start, end, bar_top, bar_bottom
                )
                offset_x = self._drag_offset_x(drag_idx)

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 50))
                painter.drawRoundedRect(
                    ox, oy + 3, bw, bh, SEGMENT_RADIUS, SEGMENT_RADIUS
                )

                lx, ly, _, _ = self._segment_geometry(
                    start, end, bar_top, bar_bottom, offset_x, -LIFT_OFFSET_Y
                )
                self._draw_segment_block(
                    painter,
                    self._color_index_for_gloss(gloss),
                    lx,
                    ly,
                    bw,
                    bh,
                    SEGMENT_ALPHA_ACTIVE,
                    outline=True,
                )
                self._draw_segment_label(
                    painter,
                    gloss,
                    lx,
                    lx + bw,
                    w,
                    lift_y=-LIFT_OFFSET_Y,
                    label_alpha=200,
                )

        painter.setPen(QPen(QColor(70, 70, 70), 1))
        painter.drawLine(self._margin, scrub_y, w - self._margin, scrub_y)

        if self._max > self._min:
            px = self._frame_to_x(self._value)
            painter.setPen(QPen(QColor(240, 240, 240, 220), 1))
            painter.drawLine(px, bar_top - 3, px, scrub_y + 1)

        painter.end()

    def _seek(self, x):
        frame = self._x_to_frame(int(x))
        if frame != self._value:
            self._value = frame
            self.update()
            self.valueChanged.emit(frame)

    def _finish_segment_swap_drag(self, x):
        idx = self._segment_swap_index
        dx = x - self._segment_swap_start_x
        self._segment_swap_drag = False
        self._segment_swap_dx = 0.0
        if idx is None:
            return
        if dx > SWAP_DRAG_THRESHOLD_PX and idx < len(self._segments) - 1:
            self.glossesSwapped.emit(idx, idx + 1)
        elif dx < -SWAP_DRAG_THRESHOLD_PX and idx > 0:
            self.glossesSwapped.emit(idx, idx - 1)
        self._selected_segment = None
        self.update()

    def mouseDoubleClickEvent(self, event):
        if not self.isEnabled() or event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        seg, zone = self._segment_hit_zone(x)
        if seg is None or zone != "center":
            return
        if self._selected_segment == seg:
            self._selected_segment = None
        else:
            self._selected_segment = seg
        w = self.window()
        if w:
            w.setFocus()
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        if not self.isEnabled():
            return
        x = event.position().x()

        if event.button() == Qt.MouseButton.RightButton:
            frame = self._x_to_frame(x)
            seg = self._segment_index_at(x)
            if seg is None:
                seg = -1
            global_pos = self.mapToGlobal(QPoint(int(x), int(event.position().y())))
            self.segmentContextMenuRequested.emit(seg, frame, global_pos)
            event.accept()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        seg, zone = self._segment_hit_zone(x)
        if self._is_selected(seg) and zone in ("left", "right"):
            stamp_idx = self._stamp_index_for_zone(seg, zone)
            if stamp_idx is not None:
                self._dragging_stamp_index = stamp_idx
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                frame = self._clamp_stamp_frame(stamp_idx, self._x_to_frame(x))
                if frame != self._boundaries[stamp_idx]:
                    self._boundaries[stamp_idx] = frame
                    self.boundaryChanged.emit(stamp_idx, frame)
                    self.update()
        elif self._is_selected(seg) and zone == "center" and len(self._segments) >= 2:
            self._segment_swap_drag = True
            self._segment_swap_index = self._selected_segment
            self._segment_swap_start_x = x
            self._segment_swap_dx = 0.0
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self._dragging_scrub = True
            self._seek(x)
        event.accept()

    def mouseMoveEvent(self, event):
        x = event.position().x()
        if self._dragging_stamp_index is not None:
            idx = self._dragging_stamp_index
            frame = self._clamp_stamp_frame(idx, self._x_to_frame(x))
            if frame != self._boundaries[idx]:
                self._boundaries[idx] = frame
                self.boundaryChanged.emit(idx, frame)
                self.update()
            event.accept()
            return
        if self._segment_swap_drag:
            self._segment_swap_dx = x - self._segment_swap_start_x
            self.update()
            event.accept()
            return
        if self._dragging_scrub:
            self._seek(x)
            event.accept()
            return
        self._update_hover_cursor(x)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._segment_swap_drag:
                self._finish_segment_swap_drag(event.position().x())
            self._dragging_scrub = False
            self._dragging_stamp_index = None
            self._update_hover_cursor(event.position().x())
            event.accept()

    def leaveEvent(self, event):
        if self._dragging_stamp_index is None and not self._segment_swap_drag:
            self.unsetCursor()
        self.update()
        super().leaveEvent(event)
