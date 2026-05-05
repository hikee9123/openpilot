#!/usr/bin/env python3
import os
import time

import numpy as np

from cereal import messaging
from msgq.visionipc import VisionIpcServer, VisionStreamType

from openpilot.common.realtime import Ratekeeper


W = int(os.getenv("CAM_SIM_WIDTH", "1928"))
H = int(os.getenv("CAM_SIM_HEIGHT", "1208"))
FPS = int(os.getenv("CAM_SIM_FPS", "20"))


class RoadFrameGenerator:
  def __init__(self, width: int, height: int):
    self.width = width
    self.height = height

    yy, xx = np.indices((height, width), dtype=np.int32)
    horizon = int(height * 0.42)
    self.sky_mask = yy < horizon
    self.road_mask = ~self.sky_mask

    center = width // 2
    lower = np.maximum(1, yy - horizon)
    road_scale = np.maximum(1, height - horizon)
    half_width = (lower * width) // (road_scale * 2) + width // 12

    self.left_edge = center - half_width
    self.right_edge = center + half_width
    self.road_region = self.road_mask & (xx >= self.left_edge) & (xx <= self.right_edge)

    lane_width = np.maximum(3, lower // 42)
    lane_offset = np.maximum(8, lower // 5)
    self.left_lane = self.road_region & (np.abs(xx - (center - lane_offset)) <= lane_width)
    self.right_lane = self.road_region & (np.abs(xx - (center + lane_offset)) <= lane_width)
    self.grid_y = self.road_region & (((yy - horizon) % 92) < np.maximum(2, lower // 120))

    uv_h = height // 2
    self.uv = np.empty((uv_h, width), dtype=np.uint8)
    self.uv[:, 0::2] = 112
    self.uv[:, 1::2] = 142

  def frame(self, frame_id: int) -> bytes:
    y = np.empty((self.height, self.width), dtype=np.uint8)
    y[self.sky_mask] = 108
    y[self.road_mask] = 56
    y[self.road_region] = 82

    y[self.left_lane] = 226
    y[self.right_lane] = 226
    if frame_id % 2 == 0:
      y[self.grid_y] = 114

    band = (frame_id * 7) % max(1, self.width)
    y[:, band:band + 4] = np.maximum(y[:, band:band + 4], 140)

    return np.concatenate((y.ravel(), self.uv.ravel())).tobytes()


class RoadCamerad:
  def __init__(self):
    self.frame_id = 0
    self.generator = RoadFrameGenerator(W, H)
    self.pm = messaging.PubMaster(["roadCameraState"])
    self.vipc_server = VisionIpcServer("camerad")
    self.vipc_server.create_buffers(VisionStreamType.VISION_STREAM_ROAD, 20, W, H)
    self.vipc_server.start_listener()

  def send_frame(self):
    timestamp = int(time.monotonic() * 1e9)
    yuv = self.generator.frame(self.frame_id)
    self.vipc_server.send(VisionStreamType.VISION_STREAM_ROAD, yuv, self.frame_id, timestamp, timestamp)

    dat = messaging.new_message("roadCameraState", valid=True)
    dat.roadCameraState = {
      "frameId": self.frame_id,
      "timestampSof": timestamp,
      "timestampEof": timestamp,
      "sensor": "unknown",
      "transform": [1.0, 0.0, 0.0,
                    0.0, 1.0, 0.0,
                    0.0, 0.0, 1.0],
    }
    self.pm.send("roadCameraState", dat)
    self.frame_id += 1

  def run(self):
    rk = Ratekeeper(FPS, None)
    while True:
      self.send_frame()
      rk.keep_time()


def main():
  RoadCamerad().run()


if __name__ == "__main__":
  main()
