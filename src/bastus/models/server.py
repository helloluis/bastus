"""Attacker-pod (RunPod server) lifecycle state — shared by the web layer and the
RunPod providers, kept here to avoid a circular import between them.
"""

from __future__ import annotations

from enum import Enum


class ServerState(str, Enum):
    NOT_PROVISIONED = "not_provisioned"
    PROVISIONING = "provisioning"
    PULLING_IMAGE = "pulling_image"
    DOWNLOADING_WEIGHTS = "downloading_weights"
    LOADING_MODEL = "loading_model"
    READY = "ready"
    ERROR = "error"
    DESTROYING = "destroying"
