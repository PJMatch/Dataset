import json
import os

MIN_SEGMENT_FRAMES = 1


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


def get_sentence_id_str(dataset_info):
    """Extract or format the sentence ID string from dataset info (e.g. '01', '98')."""
    if not dataset_info:
        return "01"
    name = dataset_info.get("name", "")
    parts = name.split("_")
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    if "sentence_id" in dataset_info and dataset_info["sentence_id"] is not None:
        sid = dataset_info["sentence_id"]
        try:
            return f"{int(sid):02d}"
        except (ValueError, TypeError):
            return str(sid)
    return "01"


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
        if not selected_gloss:
            return

        eor_i = self.eor_index()

        # 1. User is explicitly recording "EoR"
        if selected_gloss == "EoR":
            if max_frame is not None:
                frame_idx = min(frame_idx, max_frame)
            if self.timestamps:
                prev_t = (
                    self.timestamps[-2]
                    if eor_i == len(self.timestamps) - 1 and len(self.timestamps) > 1
                    else (
                        self.timestamps[-1]
                        if eor_i is None or eor_i != len(self.timestamps) - 1
                        else 0
                    )
                )
                frame_idx = max(frame_idx, prev_t + MIN_SEGMENT_FRAMES)

            if eor_i is not None:
                self.timestamps[eor_i] = frame_idx
                self.ensure_eor_last(max_frame=max_frame, create_if_missing=False)
            else:
                self.recorded_glosses.append("EoR")
                self.timestamps.append(frame_idx)
            return

        # 2. User is recording a content gloss, but EoR is already in recorded_glosses
        if eor_i is not None:
            if eor_i > 0:
                frame_idx = max(
                    frame_idx, self.timestamps[eor_i - 1] + MIN_SEGMENT_FRAMES
                )
            if max_frame is not None:
                frame_idx = min(frame_idx, max_frame)
            self.recorded_glosses.insert(eor_i, selected_gloss)
            self.timestamps.insert(eor_i, frame_idx)
            self.ensure_eor_last(max_frame=max_frame, create_if_missing=False)
            return

        # 3. Normal content gloss stamping (EoR is not recorded yet - DO NOT add EoR)
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

    def ensure_eor_last(self, default_frame=None, max_frame=None, create_if_missing=False):
        """Ensure that 'EoR' is the very last recorded gloss with a valid timestamp."""
        eor_i = self.eor_index()
        if eor_i is None:
            if create_if_missing:
                last_t = self.timestamps[-1] if self.timestamps else 0
                frame = (
                    default_frame
                    if default_frame is not None
                    else (last_t + MIN_SEGMENT_FRAMES)
                )
                if self.timestamps:
                    frame = max(frame, last_t + MIN_SEGMENT_FRAMES)
                if max_frame is not None:
                    frame = min(frame, max_frame)
                self.recorded_glosses.append("EoR")
                self.timestamps.append(frame)
                if "EoR" not in self.original_glosses:
                    self.original_glosses.append("EoR")
            return

        if eor_i != len(self.recorded_glosses) - 1:
            gloss = self.recorded_glosses.pop(eor_i)
            stamp = self.timestamps.pop(eor_i)
            self.recorded_glosses.append(gloss)
            last_t = self.timestamps[-1] if self.timestamps else 0
            new_stamp = max(stamp, last_t + MIN_SEGMENT_FRAMES)
            if max_frame is not None:
                new_stamp = min(new_stamp, max_frame)
            self.timestamps.append(new_stamp)
        else:
            if len(self.timestamps) > 1:
                prev_t = self.timestamps[-2]
                if self.timestamps[-1] < prev_t + MIN_SEGMENT_FRAMES:
                    self.timestamps[-1] = prev_t + MIN_SEGMENT_FRAMES
            if max_frame is not None:
                self.timestamps[-1] = min(self.timestamps[-1], max_frame)

    def delete_timestamp(self, index):
        if 0 <= index < len(self.timestamps):
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
        if from_index == to_index:
            return
        if from_index < 0 or to_index < 0:
            return

        # 1. Reorder in original_glosses if both indices are in range and not EoR
        eor_orig = self._eor_original_index()
        max_orig_idx = (
            eor_orig - 1 if eor_orig > 0 else len(self.original_glosses) - 1
        )
        if from_index <= max_orig_idx and to_index <= max_orig_idx:
            gloss = self.original_glosses.pop(from_index)
            self.original_glosses.insert(to_index, gloss)

        # 2. Reorder in recorded_glosses if both indices are recorded and neither is EoR
        rec_len = len(self.recorded_glosses)
        if from_index < rec_len and to_index < rec_len:
            if (
                self.recorded_glosses[from_index] != "EoR"
                and self.recorded_glosses[to_index] != "EoR"
            ):
                g = self.recorded_glosses.pop(from_index)
                self.recorded_glosses.insert(to_index, g)

    def move_unrecorded_gloss(self, from_index, to_index):
        self.move_gloss_in_order(from_index, to_index)

    def move_gloss(self, from_index, to_index):
        self.move_gloss_in_order(from_index, to_index)

    def repair_timestamps(self, max_frame):
        if self.eor_index() is not None:
            self.ensure_eor_last(max_frame=max_frame, create_if_missing=False)
        ensure_monotonic_timestamps(self.timestamps, max_frame)

    def is_complete(self):
        # Annotation is complete only when EoR has been explicitly recorded by the user
        has_content = any(g != "EoR" for g in self.recorded_glosses)
        eor_recorded = self.eor_index() is not None
        return has_content and eor_recorded

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
