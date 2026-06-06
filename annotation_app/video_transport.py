from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from data_model import MIN_SEGMENT_FRAMES, clamp_stamp_frame

GLOSS_COLOR_COUNT = 16

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
    "#FF8A65",
    "#9575CD",
    "#4DB6AC",
    "#DCE775",
    "#90A4AE",
    "#F48FB1",
]

SEGMENT_ALPHA = 100
SEGMENT_ALPHA_ACTIVE = 140
SEGMENT_ALPHA_PLANNED = 42
SEGMENT_ALPHA_PLANNED_ACTIVE = 72


def _parse_segment(seg):
    planned = len(seg) > 4 and bool(seg[4])
    return seg[0], seg[1], seg[2], seg[3], planned
SEGMENT_RADIUS = 4
LIFT_OFFSET_Y = 7
BOUNDARY_HIT_PX = 8
EDGE_HIT_PX = 7
SWAP_DRAG_THRESHOLD_PX = 28
SCRUB_DRAG_THRESHOLD_PX = 4
GLOSS_BAR_HEIGHT = 19
GLOSS_TOP_PAD = 12
GLOSS_BAR_TOP = 15 + GLOSS_TOP_PAD
GLOSS_LABEL_ABOVE = 4
SCRUB_RAIL_PX = 13
TIMELINE_HEIGHT_PX = GLOSS_BAR_TOP + GLOSS_BAR_HEIGHT + SCRUB_RAIL_PX


class VideoTransport(QWidget):
    """Gloss track + scrub line; drag boundaries; RMB select block, drag to swap gloss order."""

    valueChanged = pyqtSignal(int)
    boundaryChanged = pyqtSignal(int, int)
    glossOrderMoved = pyqtSignal(int, int)
    segmentContextMenuRequested = pyqtSignal(int, bool, int, QPoint)
    stampSelectionChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(TIMELINE_HEIGHT_PX)
        self.setMaximumHeight(TIMELINE_HEIGHT_PX)
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
        self._selected_planned_index = None
        self._recorded_stamp_count = 0
        self._planned_move_hi = -1
        self._drop_target_order = None
        self._segment_swap_drag = False
        self._segment_swap_index = None
        self._segment_swap_start_x = 0.0
        self._segment_swap_dx = 0.0
        self._dragging_stamp_index = None
        self._dragging_playhead_end = False
        self._eor_stamp_index = -1
        self._deferred_scrub_press = False
        self._deferred_press_x = 0.0

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

    def set_gloss_colors(self, gloss_to_index):
        self._gloss_colors = dict(gloss_to_index)
        self.update()

    def _color_index_for_gloss(self, gloss):
        return self._gloss_colors.get(gloss, 0) % GLOSS_COLOR_COUNT

    def set_boundaries(self, frames):
        self._boundaries = list(frames)
        self.update()

    def set_eor_stamp_index(self, index):
        self._eor_stamp_index = index

    def _is_eor_stamp(self, stamp_idx):
        return stamp_idx >= 0 and stamp_idx == self._eor_stamp_index

    def _last_movable_stamp_index(self):
        if self._eor_stamp_index >= 0:
            return self._eor_stamp_index - 1
        return len(self._boundaries) - 1

    def _emit_stamp_selection(self):
        idx = -1 if self._selected_segment is None else self._selected_segment
        self.stampSelectionChanged.emit(idx)

    def set_planned_move_range(self, recorded_count, last_movable_original_index):
        self._recorded_stamp_count = recorded_count
        self._planned_move_hi = last_movable_original_index

    def clear_segment_selection(self):
        self._selected_segment = None
        self._selected_planned_index = None
        self.update()
        self._emit_stamp_selection()

    def set_selected_segment(self, index):
        self._selected_segment = index
        self._selected_planned_index = None
        self.update()
        self._emit_stamp_selection()

    def selected_planned_index(self):
        return self._selected_planned_index

    def selected_segment(self):
        """Index into recorded_glosses / timestamps (not display segment index)."""
        return self._selected_segment

    def _segment_index_at_display(self, display_seg):
        return _parse_segment(self._segments[display_seg])[3]

    def _segment_is_planned(self, display_seg):
        return _parse_segment(self._segments[display_seg])[4]

    def _display_index_for_stamp(self, stamp_idx):
        for i, seg in enumerate(self._segments):
            _, _, _, idx, planned = _parse_segment(seg)
            if not planned and idx == stamp_idx:
                return i
        return None

    def _display_index_for_planned(self, original_idx):
        for i, seg in enumerate(self._segments):
            _, _, _, idx, planned = _parse_segment(seg)
            if planned and idx == original_idx:
                return i
        return None

    def _order_move_target(self, display_idx, dx):
        from_i = self._segment_index_at_display(display_idx)
        hi = self._planned_move_hi
        if from_i < 0 or from_i > hi:
            return None
        if not self._segment_is_planned(display_idx) and self._is_eor_stamp(from_i):
            return None
        if abs(dx) < SWAP_DRAG_THRESHOLD_PX:
            return from_i
        stride = self._order_stride_px()
        steps = max(1, int(abs(dx) / stride))
        if dx > 0:
            return min(from_i + steps, hi)
        return max(from_i - steps, 0)

    def _order_stride_px(self):
        if len(self._boundaries) >= 2:
            return self._stamp_stride_px()
        slots = max(1, self._planned_move_hi + 1)
        return max(SWAP_DRAG_THRESHOLD_PX, self._inner_width() // slots)

    def _display_index_for_order(self, order_idx):
        display_i = self._display_index_for_stamp(order_idx)
        if display_i is not None:
            return display_i
        return self._display_index_for_planned(order_idx)

    def _update_drop_target_from_drag(self):
        if not self._segment_swap_drag or self._segment_swap_index is None:
            self._drop_target_order = None
            return
        from_i = self._segment_index_at_display(self._segment_swap_index)
        to_i = self._order_move_target(
            self._segment_swap_index, self._segment_swap_dx
        )
        self._drop_target_order = to_i
        self.update()

    def _has_stamp_after_display(self, display_seg):
        if self._segment_is_planned(display_seg):
            return False
        stamp_i = self._segment_index_at_display(display_seg)
        return stamp_i + 1 < len(self._boundaries)

    def _is_playhead_end_segment(self, display_seg):
        if self._segment_is_planned(display_seg):
            return False
        return (
            display_seg is not None
            and display_seg == len(self._segments) - 1
            and not self._has_stamp_after_display(display_seg)
        )

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
        bar_top = GLOSS_BAR_TOP
        bar_bottom = bar_top + GLOSS_BAR_HEIGHT
        return scrub_y, bar_top, bar_bottom

    def _in_gloss_hit_band(self, y):
        _, bar_top, bar_bottom = self._layout_metrics()
        return (bar_top - LIFT_OFFSET_Y) <= y <= bar_bottom + 1

    def _segment_index_at(self, x):
        if not self._segments:
            return None
        frame = self._x_to_frame(x)
        for i in range(len(self._segments) - 1, -1, -1):
            gloss, start, end, _, planned = _parse_segment(self._segments[i])
            if end <= start:
                continue
            if i == len(self._segments) - 1:
                if start <= frame <= end:
                    return i
            elif start <= frame < end:
                return i
        return None

    def _segment_hit_zone(self, x, y=None):
        if y is not None and not self._in_gloss_hit_band(y):
            return None, None
        seg = self._segment_index_at(x)
        if seg is None:
            return None, None
        gloss, start, end, _, planned = _parse_segment(self._segments[seg])
        if planned:
            return seg, "center"
        x1 = self._frame_to_x(start)
        x2 = self._frame_to_x(end)
        mx = int(x)
        if abs(mx - x1) <= EDGE_HIT_PX:
            return seg, "left"
        if abs(mx - x2) <= EDGE_HIT_PX and (
            seg + 1 < len(self._segments)
            or self._has_stamp_after_display(seg)
            or self._is_playhead_end_segment(seg)
        ):
            return seg, "right"
        return seg, "center"

    def _stamp_index_for_zone(self, seg, zone):
        if self._segment_is_planned(seg):
            return None
        if zone == "left":
            stamp_idx = self._segment_index_at_display(seg)
            return None if self._is_eor_stamp(stamp_idx) else stamp_idx
        if zone == "right":
            if seg + 1 < len(self._segments):
                stamp_idx = self._segment_index_at_display(seg + 1)
            else:
                stamp_idx = self._segment_index_at_display(seg) + 1
            if stamp_idx < len(self._boundaries):
                return stamp_idx
        return None

    def _clamp_playhead_end(self, stamp_i, frame):
        lo = self._boundaries[stamp_i] + MIN_SEGMENT_FRAMES
        return max(lo, min(self._max, frame))

    def _is_selected(self, display_seg):
        if display_seg is None:
            return False
        idx = self._segment_index_at_display(display_seg)
        if self._segment_is_planned(display_seg):
            return self._selected_planned_index == idx
        return self._selected_segment == idx

    def _can_swap_from_display(self, display_seg):
        if display_seg is None or display_seg < 0 or display_seg >= len(self._segments):
            return False
        if not self._is_selected(display_seg):
            return False
        idx = self._segment_index_at_display(display_seg)
        hi = self._planned_move_hi
        if hi < 0:
            return False
        if self._segment_is_planned(display_seg):
            return 0 <= idx <= hi
        if self._is_eor_stamp(idx):
            return False
        return 0 <= idx <= hi

    def _clamp_stamp_frame(self, index, frame):
        return clamp_stamp_frame(self._boundaries, index, frame, self._max)

    def _update_hover_cursor(self, x, y=None):
        if (
            self._dragging_stamp_index is not None
            or self._segment_swap_drag
            or self._dragging_playhead_end
        ):
            return

        seg, zone = self._segment_hit_zone(x, y)
        if self._is_selected(seg) and zone in ("left", "right"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif self._is_selected(seg) and zone == "center" and self._can_swap_from_display(
            seg
        ):
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

        fill = QColor(SEGMENT_COLORS[color_index % GLOSS_COLOR_COUNT])
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
        self,
        painter,
        gloss,
        x1,
        x2,
        canvas_w,
        bar_top,
        lift_y=0,
        label_alpha=150,
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
                painter.drawText(
                    lx, bar_top - GLOSS_LABEL_ABOVE + lift_y, display
                )
                return

    def _stamp_stride_px(self):
        if len(self._boundaries) < 2:
            return max(SWAP_DRAG_THRESHOLD_PX, self._inner_width() // 4)
        total = 0
        for i in range(len(self._boundaries) - 1):
            total += abs(
                self._frame_to_x(self._boundaries[i + 1])
                - self._frame_to_x(self._boundaries[i])
            )
        return max(SWAP_DRAG_THRESHOLD_PX, total // (len(self._boundaries) - 1))

    def _drag_offset_x(self, display_seg):
        dx = int(self._segment_swap_dx * 0.85)
        start = self._segments[display_seg][1]
        x1 = self._frame_to_x(start)
        lo = self._margin - x1
        hi = self.width() - self._margin - x1
        return max(lo, min(hi, dx))

    def _draw_drop_target_indicator(self, painter, bar_top, bar_bottom):
        display_i = None
        if self._drop_target_order is not None:
            display_i = self._display_index_for_order(self._drop_target_order)
        if display_i is None:
            return
        _, start, end, _, _ = _parse_segment(self._segments[display_i])
        if end <= start:
            return
        x, y, bw, bh = self._segment_geometry(start, end, bar_top, bar_bottom)
        painter.setBrush(QColor(255, 255, 255, 35))
        painter.setPen(QPen(QColor(255, 255, 255, 210), 2, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(x, y, bw, bh, SEGMENT_RADIUS, SEGMENT_RADIUS)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        scrub_y, bar_top, bar_bottom = self._layout_metrics()
        drag_idx = self._segment_swap_index if self._segment_swap_drag else None

        painter.fillRect(0, 0, w, self.height(), QColor("#1e1e1e"))

        for i, seg in enumerate(self._segments):
            gloss, start, end, _, planned = _parse_segment(seg)
            if planned:
                continue
            if end <= start:
                continue
            if drag_idx == i:
                continue

            x, y, bw, bh = self._segment_geometry(start, end, bar_top, bar_bottom)
            is_selected = self._is_selected(i) and not self._segment_swap_drag
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
            self._draw_segment_label(painter, gloss, x, x + bw, w, bar_top)

        for i, seg in enumerate(self._segments):
            gloss, start, end, _, planned = _parse_segment(seg)
            if not planned:
                continue
            if end <= start:
                continue
            if drag_idx == i:
                continue

            x, y, bw, bh = self._segment_geometry(start, end, bar_top, bar_bottom)
            is_selected = self._is_selected(i) and not self._segment_swap_drag
            alpha = (
                SEGMENT_ALPHA_PLANNED_ACTIVE
                if is_selected
                else SEGMENT_ALPHA_PLANNED
            )
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
            self._draw_segment_label(
                painter,
                gloss,
                x,
                x + bw,
                w,
                bar_top,
                label_alpha=90 if is_selected else 70,
            )

        if self._segment_swap_drag:
            self._draw_drop_target_indicator(painter, bar_top, bar_bottom)

        if drag_idx is not None and drag_idx < len(self._segments):
            gloss, start, end, _, planned = _parse_segment(self._segments[drag_idx])
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
                drag_alpha = (
                    SEGMENT_ALPHA_PLANNED_ACTIVE
                    if planned
                    else SEGMENT_ALPHA_ACTIVE
                )
                self._draw_segment_block(
                    painter,
                    self._color_index_for_gloss(gloss),
                    lx,
                    ly,
                    bw,
                    bh,
                    drag_alpha,
                    outline=True,
                )
                self._draw_segment_label(
                    painter,
                    gloss,
                    lx,
                    lx + bw,
                    w,
                    bar_top,
                    lift_y=-LIFT_OFFSET_Y,
                    label_alpha=200,
                )

        painter.setPen(QPen(QColor(70, 70, 70), 1))
        painter.drawLine(self._margin, scrub_y, w - self._margin, scrub_y)

        if self._max > self._min:
            px = self._frame_to_x(self._value)
            painter.setPen(QPen(QColor(240, 240, 240, 230), 2))
            painter.drawLine(px, 0, px, scrub_y + 1)

        painter.end()

    def _seek(self, x):
        frame = self._x_to_frame(int(x))
        if frame != self._value:
            self._value = frame
            self.update()
            self.valueChanged.emit(frame)

    def _finish_segment_swap_drag(self, x):
        display_idx = self._segment_swap_index
        dx = x - self._segment_swap_start_x
        self._segment_swap_drag = False
        self._segment_swap_dx = 0.0
        self._drop_target_order = None
        if display_idx is None:
            return

        idx_from = self._segment_index_at_display(display_idx)
        idx_to = self._order_move_target(display_idx, dx)
        if idx_to is not None and idx_to != idx_from:
            self.glossOrderMoved.emit(idx_from, idx_to)

        self._selected_segment = None
        self._selected_planned_index = None
        self.update()
        self._emit_stamp_selection()

    def mouseDoubleClickEvent(self, event):
        if not self.isEnabled() or event.button() != Qt.MouseButton.LeftButton:
            return
        self._deferred_scrub_press = False
        self._dragging_scrub = False
        x = event.position().x()
        y = event.position().y()
        seg, zone = self._segment_hit_zone(x, y)
        if seg is None or zone != "center":
            return
        idx = self._segment_index_at_display(seg)
        if self._segment_is_planned(seg):
            if self._selected_planned_index == idx:
                self._selected_planned_index = None
            else:
                self._selected_planned_index = idx
                self._selected_segment = None
        elif self._selected_segment == idx:
            self._selected_segment = None
        else:
            self._selected_segment = idx
            self._selected_planned_index = None
        w = self.window()
        if w:
            w.setFocus()
        self.update()
        self._emit_stamp_selection()
        event.accept()

    def mousePressEvent(self, event):
        if not self.isEnabled():
            return
        x = event.position().x()
        y = event.position().y()

        if event.button() == Qt.MouseButton.RightButton:
            frame = self._x_to_frame(x)
            display_seg = (
                self._segment_index_at(x)
                if self._in_gloss_hit_band(y)
                else None
            )
            if display_seg is None:
                seg_idx = -1
                is_planned = False
            else:
                seg_idx = self._segment_index_at_display(display_seg)
                is_planned = self._segment_is_planned(display_seg)
            global_pos = self.mapToGlobal(QPoint(int(x), int(event.position().y())))
            self.segmentContextMenuRequested.emit(
                seg_idx, is_planned, frame, global_pos
            )
            event.accept()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        seg, zone = self._segment_hit_zone(x, y)

        if seg is None:
            if (
                self._selected_segment is not None
                or self._selected_planned_index is not None
            ):
                self.clear_segment_selection()
            self._deferred_scrub_press = False
            self._dragging_scrub = True
            self._seek(x)
            event.accept()
            return

        if zone == "center" and not self._is_selected(seg):
            self._deferred_scrub_press = True
            self._deferred_press_x = x
            event.accept()
            return

        if self._is_selected(seg) and zone in ("left", "right"):
            if zone == "right" and self._is_playhead_end_segment(seg):
                self._dragging_playhead_end = True
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                stamp_i = self._segment_index_at_display(seg)
                frame = self._clamp_playhead_end(
                    stamp_i, self._x_to_frame(x)
                )
                if frame != self._value:
                    self._value = frame
                    self.update()
                    self.valueChanged.emit(frame)
            else:
                stamp_idx = self._stamp_index_for_zone(seg, zone)
                if stamp_idx is not None:
                    self._dragging_stamp_index = stamp_idx
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                    frame = self._clamp_stamp_frame(stamp_idx, self._x_to_frame(x))
                    if frame != self._boundaries[stamp_idx]:
                        self._boundaries[stamp_idx] = frame
                        self.boundaryChanged.emit(stamp_idx, frame)
                        self.update()
        elif (
            self._is_selected(seg)
            and zone == "center"
            and self._can_swap_from_display(seg)
        ):
            self._segment_swap_drag = True
            self._segment_swap_index = seg
            self._segment_swap_start_x = x
            self._segment_swap_dx = 0.0
            self._update_drop_target_from_drag()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self._dragging_scrub = True
            self._seek(x)
        event.accept()

    def mouseMoveEvent(self, event):
        x = event.position().x()
        y = event.position().y()
        if self._deferred_scrub_press:
            if abs(x - self._deferred_press_x) >= SCRUB_DRAG_THRESHOLD_PX:
                self._deferred_scrub_press = False
                self._dragging_scrub = True
                self._seek(x)
            else:
                self._update_hover_cursor(x, y)
                event.accept()
                return
        if self._dragging_stamp_index is not None:
            idx = self._dragging_stamp_index
            frame = self._clamp_stamp_frame(idx, self._x_to_frame(x))
            if frame != self._boundaries[idx]:
                self._boundaries[idx] = frame
                self.boundaryChanged.emit(idx, frame)
                self.update()
            event.accept()
            return
        if self._dragging_playhead_end:
            stamp_i = self._segment_index_at_display(len(self._segments) - 1)
            frame = self._clamp_playhead_end(stamp_i, self._x_to_frame(x))
            if frame != self._value:
                self._value = frame
                self.update()
                self.valueChanged.emit(frame)
            event.accept()
            return
        if self._segment_swap_drag:
            self._segment_swap_dx = x - self._segment_swap_start_x
            self._update_drop_target_from_drag()
            self.update()
            event.accept()
            return
        if self._dragging_scrub:
            self._seek(x)
            event.accept()
            return
        self._update_hover_cursor(x, y)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._segment_swap_drag:
                self._finish_segment_swap_drag(event.position().x())
            self._deferred_scrub_press = False
            self._dragging_scrub = False
            self._dragging_stamp_index = None
            self._dragging_playhead_end = False
            self._update_hover_cursor(
                event.position().x(), event.position().y()
            )
            event.accept()

    def leaveEvent(self, event):
        if (
            self._dragging_stamp_index is None
            and not self._segment_swap_drag
            and not self._dragging_playhead_end
        ):
            self.unsetCursor()
        self.update()
        super().leaveEvent(event)
