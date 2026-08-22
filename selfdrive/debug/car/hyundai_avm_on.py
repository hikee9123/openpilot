#!/usr/bin/env python3
import secrets
import time

import cereal.messaging as messaging


if __name__ == "__main__":
  pm = messaging.PubMaster(["carControlCustom"])
  cmd_idx = secrets.randbits(32) or 1

  print("Requesting AVM ON. Keep the vehicle stopped in D with the brake pressed.")
  time.sleep(1.0)
  for _ in range(5):
    msg = messaging.new_message("carControlCustom")
    msg.carControlCustom.cmdIdx = cmd_idx
    msg.carControlCustom.avmOnRequest = True
    pm.send("carControlCustom", msg)
    time.sleep(0.1)

  print(f"AVM ON request sent (cmdIdx={cmd_idx}).")
