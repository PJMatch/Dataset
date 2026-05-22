import json
import os
import tempfile

import paramiko


class SSHManager:
    def __init__(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.sftp = None

    def connect(self, host, username, password):
        self.ssh.connect(host, port=22, username=username, password=password)
        self.sftp = self.ssh.open_sftp()

    def list_datasets(self, remote_dir="/pjm/baza_wideo", min_id=None, max_id=None):
        datasets = []
        try:
            files = self.sftp.listdir(remote_dir)
        except IOError:
            raise Exception(f"Could not read directory {remote_dir}. Does it exist?")

        mp4_files = [f for f in files if f.endswith(".mp4")]

        for mp4 in mp4_files:
            if min_id is not None or max_id is not None:
                try:
                    parts = mp4.split("_")
                    if len(parts) >= 2:
                        sentence_id = int(parts[1])
                        if min_id is not None and sentence_id < min_id:
                            continue
                        if max_id is not None and sentence_id > max_id:
                            continue
                    else:
                        continue
                except ValueError:
                    continue  # skip if the ID part is not a number

            base_name = mp4[:-4]
            json_name = base_name + ".json"

            if json_name in files:
                is_annotated = False
                json_path = f"{remote_dir}/{json_name}"

                try:
                    with self.sftp.open(json_path, "r") as f:
                        data = json.load(f)
                        if data.get("glosses") and isinstance(data["glosses"][0], list):
                            is_annotated = True
                except Exception:
                    pass

                datasets.append(
                    {
                        "name": base_name,
                        "annotated": is_annotated,
                        "mp4_path": f"{remote_dir}/{mp4}",
                        "json_path": json_path,
                    }
                )

        datasets.sort(key=lambda x: (x["annotated"], x["name"]))
        return datasets

    def read_json_memory(self, remote_path):
        with self.sftp.open(remote_path, "r") as f:
            return json.load(f)

    def save_json_memory(self, remote_path, data):
        with self.sftp.open(remote_path, "w") as f:
            json_str = json.dumps(data, ensure_ascii=False, indent=4)
            f.write(json_str.encode("utf-8"))

    def download_video_temp(self, remote_path):
        fd, temp_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        self.sftp.get(remote_path, temp_path)
        return temp_path

    def disconnect(self):
        if self.sftp:
            self.sftp.close()
        self.ssh.close()
