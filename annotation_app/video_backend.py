import cv2


class VideoBackend:
    def __init__(self):
        self.cap = None
        self.total_frames = 0
        self.fps = 25.0
        self.current_frame_idx = -1
        self.last_frame_rgb = None

    def load(self, path):
        if self.cap:
            self.cap.release()

        self.cap = cv2.VideoCapture(path)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if fps and fps > 0 else 25.0
        self.current_frame_idx = -1
        self.last_frame_rgb = None

    def get_frame(self, frame_idx):
        if not self.cap:
            return None

        frame_idx = max(0, min(frame_idx, self.total_frames - 1))

        if frame_idx == self.current_frame_idx and self.last_frame_rgb is not None:
            return self.last_frame_rgb

        if frame_idx != self.current_frame_idx + 1:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)

        ret, frame = self.cap.read()

        if ret:
            self.current_frame_idx = frame_idx
            self.last_frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return self.last_frame_rgb

        return None
