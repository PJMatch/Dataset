import json
import os

MIN_SEGMENT_FRAMES = 12


def clamp_stamp_frame(timestamps, index, frame, max_frame, min_span=MIN_SEGMENT_FRAMES):
    if not timestamps or index < 0 or index >= len(timestamps):
        return frame
    current = timestamps[index]
    lo = 0
    hi = max_frame
    if index > 0:
        lo = timestamps[index - 1] + min_span
    if index + 1 < len(timestamps):
        hi = min(hi, timestamps[index + 1] - min_span)
    if lo > hi:
        return current
    return max(lo, min(hi, frame))


def ensure_monotonic_timestamps(timestamps, max_frame, min_span=MIN_SEGMENT_FRAMES):
    """Keep stamps ordered with minimum gap so no gloss segment collapses."""
    if not timestamps:
        return
    max_frame = max(0, max_frame)
    timestamps[0] = max(0, min(timestamps[0], max_frame))
    for i in range(1, len(timestamps)):
        timestamps[i] = max(timestamps[i], timestamps[i - 1] + min_span)
        timestamps[i] = min(timestamps[i], max_frame)
    for i in range(len(timestamps) - 2, -1, -1):
        min_allowed = timestamps[i + 1] - min_span
        if timestamps[i] > min_allowed:
            timestamps[i] = max(0, min_allowed)


def clamp_insert_frame(timestamps, insert_at, frame, max_frame, min_span=MIN_SEGMENT_FRAMES):
    lo = 0
    hi = max_frame
    if insert_at > 0:
        lo = timestamps[insert_at - 1] + min_span
    if insert_at < len(timestamps):
        hi = min(hi, timestamps[insert_at] - min_span)
    if lo > hi:
        return None
    return max(lo, min(hi, frame))


class AnnotationData:
    def __init__(self, ssh_manager, json_remote_path):
        self.ssh_manager = ssh_manager
        self.json_remote_path = json_remote_path

        self.data = self.ssh_manager.read_json_memory(json_remote_path)

        raw_glosses = self.data.get("glosses", [])
        self.original_glosses = []

        for item in raw_glosses:
            if isinstance(item, list):
                self.original_glosses.append(str(item[0]))
            else:
                self.original_glosses.append(str(item))

        if not self.original_glosses or self.original_glosses[-1] != "EoR":
            self.original_glosses.append("EoR")

        self._factory_glosses = list(self.original_glosses)
        self.recorded_glosses = []
        self.timestamps = []

    def reset_to_factory(self):
        """Clear stamps and restore the gloss list from when this video was loaded."""
        self.recorded_glosses = []
        self.timestamps = []
        self.original_glosses = list(self._factory_glosses)

    def add_timestamp(self, selected_gloss, frame_idx, max_frame=None):
        if not self.is_complete():
            if self.timestamps and max_frame is not None:
                frame_idx = max(frame_idx, self.timestamps[-1] + MIN_SEGMENT_FRAMES)
                frame_idx = min(frame_idx, max_frame)
            self.recorded_glosses.append(selected_gloss)
            self.timestamps.append(frame_idx)

    def eor_index(self):
        for i, gloss in enumerate(self.recorded_glosses):
            if gloss == "EoR":
                return i
        return None

    def ensure_eor_last(self):
        idx = self.eor_index()
        if idx is None or idx == len(self.recorded_glosses) - 1:
            return
        gloss = self.recorded_glosses.pop(idx)
        stamp = self.timestamps.pop(idx)
        self.recorded_glosses.append(gloss)
        self.timestamps.append(stamp)

    def delete_timestamp(self, index):
        if 0 <= index < len(self.timestamps):
            if self.recorded_glosses[index] == "EoR":
                return
            self.recorded_glosses.pop(index)
            self.timestamps.pop(index)

    def insert_timestamp(self, index, gloss, frame_idx):
        if gloss == "EoR":
            return
        index = max(0, min(index, len(self.timestamps)))
        eor_i = self.eor_index()
        if eor_i is not None:
            index = min(index, eor_i)
        self.recorded_glosses.insert(index, gloss)
        self.timestamps.insert(index, frame_idx)

    def _eor_original_index(self):
        if not self.original_glosses or self.original_glosses[-1] != "EoR":
            return len(self.original_glosses)
        return len(self.original_glosses) - 1

    def insert_original_gloss(self, index, gloss):
        if gloss == "EoR":
            return
        recorded = len(self.recorded_glosses)
        eor_i = self._eor_original_index()
        index = max(recorded, min(index, eor_i))
        self.original_glosses.insert(index, gloss)

    def delete_original_gloss(self, index):
        recorded = len(self.recorded_glosses)
        if index < recorded or index >= len(self.original_glosses):
            return
        if self.original_glosses[index] == "EoR":
            return
        self.original_glosses.pop(index)

    def replace_original_gloss(self, index, gloss):
        recorded = len(self.recorded_glosses)
        if gloss == "EoR" or index < recorded or index >= len(self.original_glosses):
            return
        self.original_glosses[index] = gloss

    def move_gloss_in_order(self, from_index, to_index):
        """Reorder gloss names in the master list only.

        Timestamps are never moved or edited: stamped frames stay put, and the
        recorded gloss names are always re-derived from the master list so the
        two never drift apart (which previously caused duplicated names).
        """
        recorded = len(self.recorded_glosses)
        hi = self._eor_original_index() - 1
        if from_index == to_index:
            return
        if from_index < 0 or to_index < 0 or from_index > hi or to_index > hi:
            return
        if self.original_glosses[from_index] == "EoR":
            return

        gloss = self.original_glosses.pop(from_index)
        insert_at = to_index - 1 if from_index < to_index else to_index
        self.original_glosses.insert(insert_at, gloss)

        for i in range(recorded):
            if i < len(self.original_glosses) and self.recorded_glosses[i] != "EoR":
                self.recorded_glosses[i] = self.original_glosses[i]

    def move_unrecorded_gloss(self, from_index, to_index):
        self.move_gloss_in_order(from_index, to_index)

    def move_gloss(self, from_index, to_index):
        self.move_gloss_in_order(from_index, to_index)

    def repair_timestamps(self, max_frame):
        self.ensure_eor_last()
        ensure_monotonic_timestamps(self.timestamps, max_frame)

    def is_complete(self):
        return len(self.timestamps) >= len(self.original_glosses)

    def finalize_and_save(self, reordered_glosses):
        sorted_timestamps = sorted(self.timestamps)
        self.data["glosses"] = [
            [g, t] for g, t in zip(reordered_glosses, sorted_timestamps)
        ]
        self.ssh_manager.save_json_memory(self.json_remote_path, self.data)

    def set_recorded_correctly_false(self):
        self.data["recorded_correctly"] = False
        self.ssh_manager.save_json_memory(self.json_remote_path, self.data)

    def update_structure(self, new_glosses):
        """Wipes progress and saves a brand new unannotated structure to the server."""
        self.recorded_glosses = []
        self.timestamps = []

        if not new_glosses or new_glosses[-1] != "EoR":
            new_glosses.append("EoR")

        self.original_glosses = new_glosses
        self._factory_glosses = list(self.original_glosses)

        self.data["glosses"] = new_glosses
        self.data["recorded_correctly"] = True

        self.ssh_manager.save_json_memory(self.json_remote_path, self.data)
