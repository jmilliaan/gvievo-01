"""The gating inputs the amr_base tests build (lean plan D66): supervisor params, the lease, the
panel image and the drives, at t = 10 s on instance INST, generation 3. Pass `allowed` explicitly
where a test is about what the lease allows."""

from amr_base.gating import LEASE_AUTONOMOUS, LEASE_MANUAL, Drives, Lease, Panel, Params

SUP = Params(require_supervisor=True, teleop_enabled=False)
SUP_TELEOP = Params(require_supervisor=True, teleop_enabled=True)
INST = "11111111-aaaa"
DRIVES_OK = Drives(t_recv=10.0, operational=True)


def lease(t=10.0, gen=3, allowed=LEASE_MANUAL | LEASE_AUTONOMOUS, seq=10, inst=INST):
    return Lease(t_recv=t, instance=inst, generation=gen, seq=seq, allowed=allowed)


def panel(t=10.0, auto=False, valid=True, **held):
    return Panel(t_recv=t, valid=valid, auto=auto, **held)
