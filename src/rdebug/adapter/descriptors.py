"""Layer 1: descriptor-level access detail from the replay controller.

This lives beside adapter/core.py rather than inside it: the replay controller
already exists on the session, and adding a sibling module keeps the Gate 4
monitored surface (`adapter/core.py`) untouched. Access to ``session._ctrl``
is deliberately confined to this adapter module; analysis layers never see a
native RenderDoc object.
"""


def read_descriptor_access(session, event_id=None, resource_id=None):
    """Return structured descriptor accesses at an event.

    ``GetUsage`` only exposes an event id and a usage name. Descriptor access
    additionally exposes mip/layer ranges and byte ranges for bound views, so
    this is the evidence source for subresource and region resolution.
    """
    if event_id is not None:
        session.set_event(event_id)
    rd = session.rd
    rows = []
    for access in session._ctrl.GetDescriptorAccess():
        descriptor = None
        reason = None
        try:
            ranges = rd.DescriptorRange(access)
            descriptors = session._ctrl.GetDescriptors(
                access.descriptorStore, [ranges])
            if descriptors:
                descriptor = descriptors[0]
        except Exception as exc:  # noqa: BLE001 - reason is the evidence here
            reason = f"descriptor_lookup_failed: {type(exc).__name__}"
        resource = str(descriptor.resource) if descriptor is not None else None
        if resource in (None, "", "ResourceId::0"):
            resource = None
        if resource_id is not None and resource != str(resource_id):
            continue
        rows.append({
            "resource": resource,
            "view": str(descriptor.view) if descriptor is not None else None,
            "descriptorStore": str(access.descriptorStore),
            "descriptorIndex": int(access.index),
            "arrayElement": int(access.arrayElement),
            "byteOffset": int(descriptor.byteOffset) if descriptor is not None else None,
            "byteSize": int(descriptor.byteSize) if descriptor is not None else None,
            "firstMip": int(descriptor.firstMip) if descriptor is not None else None,
            "numMips": int(descriptor.numMips) if descriptor is not None else None,
            "firstSlice": int(descriptor.firstSlice) if descriptor is not None else None,
            "numSlices": int(descriptor.numSlices) if descriptor is not None else None,
            "stage": int(access.stage),
            "descriptorType": int(access.type),
            "status": "observed" if descriptor is not None else "unknown",
            "reason": reason if descriptor is None else None,
        })
    return rows
