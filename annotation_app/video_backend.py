import cv2


class VideoBackend:
    def __init__(self):
        self.cap = None
        self.total_frames = 0
        self.current_frame_idx = 0

    def load(self, path):
        if self.cap:
            self.cap.release()

        self.cap = cv2.VideoCapture(path)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.current_frame_idx = 0

    def get_frame(self, frame_idx):
        if not self.cap:
            return None

        frame_idx = max(0, min(frame_idx, self.total_frames - 1))

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()

        if ret:
            self.current_frame_idx = frame_idx
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return None
