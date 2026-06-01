import json
import os


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

        self.recorded_glosses = []
        self.timestamps = []

    def add_timestamp(self, selected_gloss, frame_idx):
        if not self.is_complete():
            self.recorded_glosses.append(selected_gloss)
            self.timestamps.append(frame_idx)

    def delete_timestamp(self, index):
        if 0 <= index < len(self.timestamps):
            self.recorded_glosses.pop(index)
            self.timestamps.pop(index)

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

        self.data["glosses"] = new_glosses
        self.data["recorded_correctly"] = True

        self.ssh_manager.save_json_memory(self.json_remote_path, self.data)
