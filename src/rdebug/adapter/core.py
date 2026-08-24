from ..errors import CaptureOpenError, QueryError, ReplayUnsupportedError
from ..evidence import make as _make_evidence
from .locator import import_renderdoc

_STAGE_NAMES = ("Vertex", "Hull", "Domain", "Geometry", "Pixel", "Compute")

_VAR_VIEWS = {
    "Float": "f32v",
    "Double": "f64v",
    "Half": "f16v",
    "SInt": "s32v",
    "UInt": "u32v",
    "SByte": "s8v",
    "UByte": "u8v",
    "SShort": "s16v",
    "UShort": "u16v",
}

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

_REPLAY_LIFECYCLE = {"initialised": False, "sessions": 0, "rd": None}
_ENUMS = {}


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


def _no_preference(rd):
    pref = getattr(rd.ReplayController, "NoPreference", None)
    if pref is not None:
        try:
            return int(pref)
        except (TypeError, ValueError):
            pass
    return 0xFFFFFFFF


def _enum_name(enum_type, value):
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        return str(value)
    for name in dir(enum_type):
        if name.startswith("_"):
            continue
        try:
            if int(getattr(enum_type, name)) == wanted:
                return name
        except (TypeError, ValueError):
            continue
    return str(value)


def _var_values(v):
    n = int(v.rows) * int(v.columns)
    if n <= 0:
        n = 1
    val = getattr(v, "value", None)
    if val is None:
        return None
    attr = _VAR_VIEWS.get(str(getattr(v, "type", "")), "f32v")
    arr = getattr(val, attr, None)
    if arr is None:
        arr = getattr(val, "f32v", None)
        if arr is None:
            return None
    out = []
    for i in range(min(n, 16)):
        x = arr[i]
        try:
            out.append(float(x) if attr.startswith("f") else int(x))
        except (TypeError, ValueError):
            out.append(str(x))
    return out


def _variable_to_dict(v, depth=0):
    out = {
        "name": str(getattr(v, "name", "")),
        "type": _enum_name(_ENUMS.get("VarType"), getattr(v, "type", None)),
        "rows": int(getattr(v, "rows", 1)),
        "columns": int(getattr(v, "columns", 1)),
    }
    members = getattr(v, "members", None)
    if depth < 6 and members is not None and len(members):
        out["members"] = [_variable_to_dict(m, depth + 1) for m in members]
    else:
        values = _var_values(v)
        if values is not None:
            out["value"] = values
    return out


def _state_to_dict(s):
    return {
        "stepIndex": int(s.stepIndex),
        "nextInstruction": int(s.nextInstruction),
        "events": int(getattr(s, "flags", 0)),
        "callstack": [str(c) for c in s.callstack],
        "changes": [
            {"before": _variable_to_dict(ch.before), "after": _variable_to_dict(ch.after)}
            for ch in s.changes
        ],
    }


def _instinfo_to_dict(i):
    li = i.lineInfo
    return {
        "instruction": int(i.instruction),
        "disassemblyLine": int(li.disassemblyLine),
        "fileIndex": int(li.fileIndex),
        "lineStart": int(li.lineStart),
        "lineEnd": int(li.lineEnd),
        "colStart": int(li.colStart),
        "colEnd": int(li.colEnd),
    }


class CaptureSession:
    def __init__(self, path, rd_path=None, replay_options=None):
        self.path = str(path)
        self.driver = None
        self._current_eid = 0
        self._rid_cache = None
        self._rd = import_renderdoc(rd_path)
        if not _REPLAY_LIFECYCLE["initialised"]:
            self._rd.InitialiseReplay(self._rd.GlobalEnvironment(), [])
            _REPLAY_LIFECYCLE["initialised"] = True
            _REPLAY_LIFECYCLE["rd"] = self._rd
            _ENUMS["VarType"] = getattr(self._rd, "VarType", None)
            _ENUMS["ShaderStage"] = getattr(self._rd, "ShaderStage", None)
        _REPLAY_LIFECYCLE["sessions"] += 1
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
        _REPLAY_LIFECYCLE["sessions"] = max(0, _REPLAY_LIFECYCLE["sessions"] - 1)

    @classmethod
    def shutdown_replay(cls):
        """Explicitly shut down the process-wide replay API. After this no new
        CaptureSession can be opened in this process (RenderDoc does not allow
        re-initialisation), so only call it when completely finished."""
        if _REPLAY_LIFECYCLE["initialised"] and _REPLAY_LIFECYCLE["sessions"] == 0:
            try:
                _REPLAY_LIFECYCLE["rd"].ShutdownReplay()
            except Exception:
                pass
            _REPLAY_LIFECYCLE["initialised"] = False

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

    def last_draw_event_id(self):
        rows = self.draw_rows()
        if not rows:
            return self.last_event_id()
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
        key = str(rid)
        cache = self._resource_id_cache()
        if key in cache:
            return cache[key]
        digits = "".join(ch for ch in key if ch.isdigit())
        matches = (
            [
                v
                for k, v in cache.items()
                if k.endswith(f"({digits})") or k.endswith(f"::{digits}")
            ]
            if digits
            else []
        )
        if len(matches) == 1:
            return matches[0]
        raise QueryError(
            f"unknown resource id {key!r}; use an id from 'rdebug resources'"
        )

    def _resource_id_cache(self):
        if getattr(self, "_rid_cache", None) is None:
            self._rid_cache = {}
            for r in self._ctrl.GetResources():
                self._rid_cache[str(r.resourceId)] = r.resourceId
        return self._rid_cache

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
            "evidence": [
                _make_evidence(
                    capture=self.path,
                    event_id=int(context_eid),
                    resource_id=_rid_str(real),
                    subresource={"mip": int(mip), "slice": int(slice_), "sample": int(sample)},
                    location={"x": int(x), "y": int(y)},
                    operation="pixel_history",
                    source="ReplayController.PixelHistory",
                )
            ],
            "modifications": [_modification_to_dict(h) for h in history],
        }

    def debug_pixel(
        self,
        x,
        y,
        primitive=None,
        sample=None,
        view=None,
        eid=None,
        max_steps=4096,
    ):
        rd = self._rd
        if eid is not None:
            self.set_event(eid)
        pipe = self._ctrl.GetPipelineState()
        stage = rd.ShaderStage.Pixel
        null = rd.ResourceId.Null()
        sid = pipe.GetShader(stage)
        if sid == null:
            raise QueryError(f"no pixel shader bound at event {self._current_eid}")
        refl = pipe.GetShaderReflection(stage)
        di = getattr(refl, "debugInfo", None)
        if di is None or not di.debuggable:
            status = str(di.debugStatus) if di is not None else "no debug info available"
            raise QueryError(
                f"pixel shader at event {self._current_eid} is not debuggable: {status}"
            )
        nopref = _no_preference(rd)
        inputs = rd.DebugPixelInputs()
        inputs.primitive = nopref if primitive is None else int(primitive)
        inputs.sample = nopref if sample is None else int(sample)
        inputs.view = nopref if view is None else int(view)
        trace = self._ctrl.DebugPixel(int(x), int(y), inputs)
        if trace is None or getattr(trace, "debugger", None) is None:
            if trace is not None:
                try:
                    self._ctrl.FreeTrace(trace)
                except Exception:
                    pass
            raise QueryError(
                f"shader debugging failed at event {self._current_eid} "
                f"for pixel ({int(x)},{int(y)}) primitive={primitive}"
            )
        try:
            states = []
            truncated = False
            while True:
                more = self._ctrl.ContinueDebug(trace.debugger)
                if not len(more):
                    break
                states.extend(more)
                if len(states) >= max_steps:
                    truncated = True
                    break
            pipeline_obj = pipe.GetGraphicsPipelineObject()
            disasm = ""
            try:
                disasm = str(self._ctrl.DisassembleShader(pipeline_obj, refl, ""))
            except Exception:
                pass
            files = []
            df = getattr(di, "files", None)
            if df is not None:
                files = [{"index": i, "filename": str(f.filename)} for i, f in enumerate(df)]
            return {
                "stage": _enum_name(_ENUMS.get("ShaderStage"), trace.stage),
                "entryPoint": str(refl.entryPoint),
                "shaderResource": _rid_str(sid),
                "pipelineObject": _rid_str(pipeline_obj),
                "files": files,
                "disassembly": disasm,
                "steps": [_state_to_dict(s) for s in states],
                "instInfo": [_instinfo_to_dict(i) for i in trace.instInfo],
                "inputs": [_variable_to_dict(v) for v in trace.inputs],
                "constantBlocks": [_variable_to_dict(v) for v in trace.constantBlocks],
                "truncated": truncated,
            }
        finally:
            try:
                self._ctrl.FreeTrace(trace)
            except Exception:
                pass

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
