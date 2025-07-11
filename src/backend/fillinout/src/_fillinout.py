import contextlib
import typing

import pymel.core as pc

from ... import imaya


def removeOverrides(attr):
    count = 0
    for renderLayer in pc.nt.RenderLayer.listAllRenderLayers():
        with contextlib.suppress(RuntimeError):
            count += typing.cast(
                "pc.nt.RenderLayer", renderLayer
            ).removeAdjustments(attr)

    return count


def fill():
    sel = pc.ls(selection=True)
    if not sel:
        pc.warning("Select a mesh or camera")
        return
    if len(sel) > 1:
        pc.warning("Select only one camera or mesh")
        return
    try:
        obj = sel[0].getShape(ni=True)
    except Exception:
        pc.warning("Selection should be camera or mesh")
        return

    if isinstance(obj, pc.nt.Mesh):
        try:
            cache = obj.history(type="cacheFile")[0]
        except IndexError:
            pc.warning("No cache found on the selected object")
            return

        start = cache.sourceStart.get()
        end = cache.sourceEnd.get()
    elif isinstance(obj, pc.nt.Camera):
        animCurves = pc.listConnections(
            obj.firstParent(), scn=True, d=False, s=True
        )
        if not animCurves:
            pc.warning("No animation found on the selected camera...")
            return
        frames = pc.keyframe(animCurves[0], q=True)
        if not frames:
            pc.warning("No keys found on the selected camera...")
            return
        start = frames[0]
        end = frames[-1]
        imaya.setRenderableCamera(obj)
    else:
        pc.warning("Selection should be camera or mesh")
        return
    pc.playbackOptions(minTime=start)
    pc.setAttr("defaultRenderGlobals.startFrame", start)
    pc.playbackOptions(maxTime=end)
    pc.setAttr("defaultRenderGlobals.endFrame", end)
    pc.currentTime(start)
    return (start, end)
