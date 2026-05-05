from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


LEAD_EGO_LANE_YREL = 1.2
LEAD_LANE_LINE_PROB_MIN = 0.25
LEAD_LANE_BOUNDARY_MARGIN = 0.25
LEAD_MAX_DISTANCE = 120.0
LEAD_MIN_DISTANCE = 0.75
LEAD_LANES = ("EGO", "LEFT", "RIGHT")


@dataclass
class TrackedLead:
  dRel: float
  yRel: float
  vRel: float
  aRel: float = 0.0
  measured: bool = False
  modelProb: float = 0.0
  radar: bool = True
  radarTrackId: int = -1
  status: bool = True


def interp_y(xs, ys, x: float) -> float | None:
  count = min(len(xs), len(ys))
  if count == 0:
    return None

  if x <= xs[0]:
    return float(ys[0])

  for i in range(1, count):
    x0, x1 = float(xs[i - 1]), float(xs[i])
    if x <= x1:
      y0, y1 = float(ys[i - 1]), float(ys[i])
      if x1 == x0:
        return y1
      return y0 + (y1 - y0) * ((x - x0) / (x1 - x0))

  return float(ys[count - 1])


def lane_offset_from_model(model: Any, d_rel: float, y_rel: float) -> float:
  center_y = interp_y(model.position.x, model.position.y, d_rel)
  center_y = center_y if center_y is not None else 0.0

  if len(model.laneLines) > 2 and len(model.laneLineProbs) > 2:
    if min(float(model.laneLineProbs[1]), float(model.laneLineProbs[2])) >= LEAD_LANE_LINE_PROB_MIN:
      left_y = interp_y(model.laneLines[1].x, model.laneLines[1].y, d_rel)
      right_y = interp_y(model.laneLines[2].x, model.laneLines[2].y, d_rel)
      if left_y is not None and right_y is not None:
        lane_min = min(left_y, right_y) - LEAD_LANE_BOUNDARY_MARGIN
        lane_max = max(left_y, right_y) + LEAD_LANE_BOUNDARY_MARGIN
        if lane_min <= y_rel <= lane_max:
          return 0.0

  return y_rel - center_y


def lane_label_from_model(model: Any, d_rel: float, y_rel: float) -> str:
  lane_offset = lane_offset_from_model(model, d_rel, y_rel)
  if abs(lane_offset) <= LEAD_EGO_LANE_YREL:
    return "EGO"
  return "LEFT" if lane_offset > 0 else "RIGHT"


def select_lane_leads(live_tracks: Any | None, model: Any, radar_state: Any | None) -> list[TrackedLead | None]:
  selected: dict[str, TrackedLead | None] = {lane: None for lane in LEAD_LANES}

  if live_tracks is not None:
    for point in live_tracks.points:
      lead = _lead_from_track_point(point)
      if lead is None:
        continue
      _select_lead(selected, lane_label_from_model(model, lead.dRel, lead.yRel), lead)

  if not any(selected.values()) and radar_state is not None:
    for lead_data in (radar_state.leadOne, radar_state.leadTwo):
      lead = _lead_from_radar_state_lead(lead_data)
      if lead is None:
        continue
      _select_lead(selected, lane_label_from_model(model, lead.dRel, lead.yRel), lead)

  return [selected[lane] for lane in LEAD_LANES]


def _lead_from_track_point(point: Any) -> TrackedLead | None:
  d_rel = float(point.dRel)
  y_rel = float(point.yRel)
  v_rel = float(point.vRel)
  if not (math.isfinite(d_rel) and math.isfinite(y_rel) and math.isfinite(v_rel)):
    return None
  if d_rel < LEAD_MIN_DISTANCE or d_rel > LEAD_MAX_DISTANCE:
    return None

  a_rel = float(point.aRel) if math.isfinite(float(point.aRel)) else 0.0
  return TrackedLead(
    dRel=d_rel,
    yRel=y_rel,
    vRel=v_rel,
    aRel=a_rel,
    measured=bool(point.measured),
    radar=True,
    radarTrackId=int(point.trackId),
  )


def _lead_from_radar_state_lead(lead_data: Any) -> TrackedLead | None:
  if lead_data is None or not lead_data.status:
    return None

  return TrackedLead(
    dRel=float(lead_data.dRel),
    yRel=float(lead_data.yRel),
    vRel=float(lead_data.vRel),
    aRel=float(lead_data.aRel),
    modelProb=float(getattr(lead_data, "modelProb", 0.0)),
    radar=bool(getattr(lead_data, "radar", False)),
    radarTrackId=int(getattr(lead_data, "radarTrackId", -1)),
  )


def _select_lead(selected: dict[str, TrackedLead | None], lane: str, lead: TrackedLead) -> None:
  if lane not in selected:
    return
  current = selected[lane]
  if current is None or lead.dRel < current.dRel:
    selected[lane] = lead
