"""Cooperative cancellation and progress shared by import, CAM and export."""
from models import CamError


class Cancelled(CamError):
    pass


def checkpoint(cancel=None, progress=None, message="Working", current=0, total=0):
    if cancel and cancel():
        raise Cancelled("Cancelled. No new program was exported.")
    if progress:
        progress(message, current, total)
