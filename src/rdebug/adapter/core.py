from ..errors import CaptureOpenError, QueryError, ReplayUnsupportedError
from .locator import import_renderdoc

_STAGE_NAMES = ("Vertex", "Hull", "Domain", "Geometry", "Pixel", "Compute")

_FAILURE_FLAGS = (
    "backfaceCulled",
    "depthClipped",
    "depthBoundsFailed",
    "viewClipped",
    "scissorClipped",
    "sampleMasked",
    "shaderDiscarded",
    "depthTestFailed",
    "stencilTestFailed",
)


def _rid_str(rid):
    return str(rid)


def _value_dict(mod_value):
    col = mod_value.col
    entry = {}
    fv = getattr(col, "floatValue", None)
    if fv is not None:
        entry["float"] = [float(v) for v in fv]
    uv = getattr(col, "uintValue", None)
    if uv is not None:
        entry["uint"] = [int(v) for v in uv]
    sv = getattr(col, "sintValue", None)
    if sv is not None:
        entry["sint"] = [int(v) for v in sv]
    entry["depth"] = float(mod_value.depth)
    entry["stencil"] = int(mod_value.stencil)
    if hasattr(col, "IsValid"):
        entry["valid"] = bool(col.IsValid())
    return entry


def _modification_to_dict(h):
    row = {
        "eventId": int(h.eventId),
        "primitiveID": int(h.primitiveID),
        "fragIndex": int(getattr(h, "fragIndex", 0)),
        "passed": bool(h.Passed()),
        "unboundPS": bool(getattr(h, "unboundPS", False)),
        "directShaderWrite": bool(getattr(h, "directShaderWrite", False)),
        "preMod": _value_dict(h.preMod),
        "shaderOut": _value_dict(h.shaderOut),
        "postMod": _value_dict(h.postMod),
    }
    for name in _FAILURE_FLAGS:
        row[name] = bool(getattr(h, name, False))
    return row


class CaptureSession:
    def __init__(self, path, rd_path=None, replay_options=None):
        self.path = str(path)
        self.driver = None
        self._current_eid = 0
        self._rd = import_renderdoc(rd_path)
        self._initialised = True
        self._cap = None
        self._ctrl = None
        try:
            self._rd.InitialiseReplay(self._rd.GlobalEnvironment(), [])
            cap = self._rd.OpenCaptureFile()
            self._cap = cap
            result = cap.OpenFile(self.path, "", None)
            if result != self._rd.ResultCode.Succeeded:
                raise CaptureOpenError(
                    f"cannot open '{self.path}': {result}"
                )
            self.driver = str(cap.DriverName())
            if not cap.LocalReplaySupport():
                raise ReplayUnsupportedError(
                    f"{self.driver} capture cannot be replayed on this machine: {self.path}"
                )
            opts = (
                replay_options
                if replay_options is not None
                else self._rd.ReplayOptions()
            )
            open_result, controller = cap.OpenCapture(opts, None)
            if open_result != self._rd.ResultCode.Succeeded:
                raise CaptureOpenError(
                    f"cannot replay '{self.path}': {open_result}"
                )
            self._ctrl = controller
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        ctrl = getattr(self, "_ctrl", None)
        cap = getattr(self, "_cap", None)
        self._ctrl = None
        self._cap = None
        if ctrl is not None:
            try:
                ctrl.Shutdown()
            except Exception:
                pass
        if cap is not None:
            try:
                cap.Shutdown()
            except Exception:
                pass
        if getattr(self, "_initialised", False):
            self._initialised = False
            try:
                self._rd.ShutdownReplay()
            except Exception:
                pass

    @property
    def rd(self):
        return self._rd

    @property
    def current_event_id(self):
        return self._current_eid

    def set_event(self, event_id):
        eid = int(event_id)
        self._ctrl.SetFrameEvent(eid, True)
        self._current_eid = eid

    def root_actions(self):
        return self._ctrl.GetRootActions()

    def action_rows(self, min_eid=None, max_eid=None, name=None, limit=None):
        from ..query.events import filter_rows, flatten_actions

        rows = flatten_actions(
            self.root_actions(), draw_flag=self._rd.ActionFlags.Drawcall
        )
        return filter_rows(
            rows,
            min_eid=min_eid,
            max_eid=max_eid,
            name=name,
            limit=limit,
        )

    def draw_rows(self, min_eid=None, max_eid=None, name=None, limit=None):
        from ..query.events import filter_rows, flatten_actions

        rows = flatten_actions(
            self.root_actions(), draw_flag=self._rd.ActionFlags.Drawcall
        )
        return filter_rows(
            rows,
            min_eid=min_eid,
            max_eid=max_eid,
            name=name,
            only_draws=True,
            limit=limit,
        )

    def last_event_id(self):
        rows = self.action_rows()
        if not rows:
            return 0
        return max(r["eventId"] for r in rows)

    def api_info(self):
        info = {"driver": self.driver}
        try:
            props = self._ctrl.GetAPIProperties()
            info["pipelineType"] = str(props.pipelineType)
            info["shaderDebugging"] = bool(props.shaderDebugging)
        except Exception:
            pass
        return info

    def resources(self, name=None, limit=None):
        out = []
        for r in self._ctrl.GetResources():
            entry = {"id": _rid_str(r.resourceId), "name": str(r.name)}
            if name and name.lower() not in entry["name"].lower():
                continue
            out.append(entry)
            if limit is not None and len(out) >= int(limit):
                break
        return out

    def textures(self, limit=None):
        out = []
        for t in self._ctrl.GetTextures():
            fmt = t.format
            out.append(
                {
                    "id": _rid_str(t.resourceId),
                    "type": str(t.type),
                    "width": int(t.width),
                    "height": int(t.height),
                    "depth": int(t.depth),
                    "mips": int(t.mips),
                    "arraysize": int(t.arraysize),
                    "msSamp": int(t.msSamp),
                    "byteSize": int(t.byteSize),
                    "format": {
                        "type": str(fmt.type),
                        "compType": str(fmt.compType),
                        "compByteWidth": int(fmt.compByteWidth),
                    },
                }
            )
            if limit is not None and len(out) >= int(limit):
                break
        return out

    def buffers(self, limit=None):
        out = []
        for b in self._ctrl.GetBuffers():
            entry = {"id": _rid_str(b.resourceId), "length": int(b.length)}
            cf = getattr(b, "creationFlags", None)
            if cf is not None:
                entry["creationFlags"] = int(cf)
            out.append(entry)
            if limit is not None and len(out) >= int(limit):
                break
        return out

    def texture(self, rid):
        want = _rid_str(self._to_resource_id(rid))
        for t in self.textures():
            if t["id"] == want:
                return t
        return None

    def usage(self, rid):
        real = self._to_resource_id(rid)
        return [
            {"eventId": int(u.eventId), "usage": str(u.usage)}
            for u in self._ctrl.GetUsage(real)
        ]

    def _to_resource_id(self, rid):
        if isinstance(rid, self._rd.ResourceId):
            return rid
        digits = "".join(ch for ch in str(rid) if ch.isdigit())
        if not digits:
            raise QueryError(f"invalid resource id: {rid!r}")
        return self._rd.ResourceId(int(digits))

    def _texture_comp_type(self, real):
        want = _rid_str(real)
        for t in self._ctrl.GetTextures():
            if _rid_str(t.resourceId) == want:
                return t.format.compType
        return self._rd.CompType.Typeless

    def pixel_history(
        self,
        rid,
        x,
        y,
        mip=0,
        slice_=0,
        sample=0,
        comp_type=None,
        context_eid=None,
    ):
        real = self._to_resource_id(rid)
        if context_eid is None:
            context_eid = self.last_event_id()
        self.set_event(context_eid)
        sub = self._rd.Subresource()
        sub.mip = int(mip)
        sub.slice = int(slice_)
        sub.sample = int(sample)
        comp = comp_type if comp_type is not None else self._texture_comp_type(real)
        history = self._ctrl.PixelHistory(real, int(x), int(y), sub, comp)
        return {
            "resource": _rid_str(real),
            "contextEventId": int(context_eid),
            "x": int(x),
            "y": int(y),
            "mip": int(mip),
            "slice": int(slice_),
            "sample": int(sample),
            "modifications": [_modification_to_dict(h) for h in history],
        }

    def pipeline(self, event_id=None):
        if event_id is not None:
            self.set_event(event_id)
        pipe = self._ctrl.GetPipelineState()
        rd = self._rd
        null = rd.ResourceId.Null()
        out = {
            "eventId": int(self._current_eid),
            "graphicsPipelineObject": _rid_str(pipe.GetGraphicsPipelineObject()),
            "outputTargets": [],
            "depthTarget": None,
            "shaders": {},
            "descriptors": [],
            "indexBuffer": None,
        }
        for i, o in enumerate(pipe.GetOutputTargets()):
            rid = getattr(o, "resource", None)
            if rid == null:
                continue
            out["outputTargets"].append(
                {
                    "slot": i,
                    "resource": _rid_str(rid),
                    "firstMip": int(getattr(o, "firstMip", 0)),
                    "firstSlice": int(getattr(o, "firstSlice", 0)),
                }
            )
        depth = pipe.GetDepthTarget()
        drid = getattr(depth, "resource", None)
        if drid != null:
            out["depthTarget"] = {
                "resource": _rid_str(drid),
                "firstMip": int(getattr(depth, "firstMip", 0)),
                "firstSlice": int(getattr(depth, "firstSlice", 0)),
            }
        for stage_name in _STAGE_NAMES:
            stage = getattr(rd.ShaderStage, stage_name, None)
            if stage is None:
                continue
            sid = pipe.GetShader(stage)
            if sid == null:
                continue
            shader_entry = {"resource": _rid_str(sid)}
            try:
                refl = pipe.GetShaderReflection(stage)
                shader_entry["entryPoint"] = str(refl.entryPoint)
                di = getattr(refl, "debugInfo", None)
                if di is not None:
                    shader_entry["debuggable"] = bool(di.debuggable)
                    shader_entry["debugStatus"] = str(di.debugStatus)
            except Exception:
                pass
            out["shaders"][stage_name] = shader_entry
        try:
            used = pipe.GetAllUsedDescriptors(True)
        except Exception:
            used = []
        for d in used:
            res = getattr(d.descriptor, "resource", None)
            samp = getattr(d.sampler, "object", None)
            out["descriptors"].append(
                {
                    "stage": str(d.access.stage),
                    "type": str(d.access.type),
                    "index": int(d.access.index),
                    "resource": _rid_str(res) if res != null else None,
                    "sampler": _rid_str(samp)
                    if (samp is not None and samp != null)
                    else None,
                }
            )
        ib = pipe.GetIBuffer()
        ibres = getattr(ib, "resourceId", None)
        if ibres is not None and ibres != null:
            out["indexBuffer"] = {"resource": _rid_str(ibres)}
        return out
