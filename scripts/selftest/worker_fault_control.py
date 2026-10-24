"""Bounded fault injection in exact nonce-owned containers; no database values are edited."""

import json
from pathlib import Path
from uuid import UUID

from scripts.selftest.io import HarnessError, object_value
from scripts.selftest.local_stack import StackBinding, _docker, _verify_labels
from scripts.selftest.runtime_faults import OwnedWorkers
from scripts.selftest.worker_fault_contracts import WorkerFaultReceipt, WorkerProcess

# Both real task entrypoints stop immediately before the repository's original
# atomic claim.  Pipes synchronize two OS processes; no task result is simulated.
CLAIM_CHILD = r"""
import os,sys
from uuid import UUID
from app.repositories.tasking import TaskingRepository
from app.tasking.tasks import _run_async,_run_test_plan
original=TaskingRepository.claim_run
async def claim(self,*args,**kwargs):
    os.write(int(sys.argv[3]),b'r')
    if os.read(int(sys.argv[2]),1)!=b'g':
        raise RuntimeError('WORKER_CLAIM_GATE_CLOSED')
    return await original(self,*args,**kwargs)
TaskingRepository.claim_run=claim
_run_async(lambda:_run_test_plan(UUID(sys.argv[1])))
"""

CLAIM_PARENT = r"""
import json,os,select,subprocess,sys,time
child=sys.argv[2]
gate_r,gate_w=os.pipe()
ready_r,ready_w=os.pipe()
children=[]
try:
    for _ in range(2):
        children.append(subprocess.Popen([sys.executable,'-c',child,sys.argv[1],str(gate_r),str(ready_w)],pass_fds=(gate_r,ready_w),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
    ticks=[int(open('/proc/'+str(p.pid)+'/stat').read().rsplit(')',1)[1].split()[19])
           for p in children]
    ready=b''
    deadline=time.monotonic()+30
    while len(ready)<2:
        if not select.select([ready_r],[],[],max(0,deadline-time.monotonic()))[0]:
            raise RuntimeError('WORKER_CLAIM_GATE_DEADLINE')
        ready+=os.read(ready_r,2-len(ready))
    os.write(gate_w,b'gg')
    results=[dict(pid=p.pid,start_ticks=tick,exit_code=p.wait(timeout=40))
             for p,tick in zip(children,ticks)]
    print('FLOWTEST_WORKER_RECEIPT:'+json.dumps(results),flush=True)
finally:
    for p in children:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)
    for fd in [gate_r,gate_w,ready_r,ready_w]:
        os.close(fd)
"""

DUPLICATE_DELIVERY = r"""
import json,sys,time
from app.tasking.celery_app import celery_app
tasks=[celery_app.send_task('flowtest.run_test_plan',args=[sys.argv[1]],queue='general')
       for _ in range(2)]
deadline=time.monotonic()+30
while not all(task.ready() for task in tasks):
    if time.monotonic()>=deadline:
        raise RuntimeError('WORKER_DUPLICATE_DELIVERY_DEADLINE')
    time.sleep(.05)
if not all(task.successful() for task in tasks):
    raise RuntimeError('WORKER_DUPLICATE_DELIVERY_FAILED')
print('FLOWTEST_WORKER_RECEIPT:'+json.dumps([task.id for task in tasks]),flush=True)
"""


class WorkerFaultControl:
    def __init__(self, binding: StackBinding, directory: Path) -> None:
        self.workers = OwnedWorkers(binding, directory)
        self.binding = binding

    def _runner(self) -> str:
        identity = self.binding.runner_container_id
        inspection = object_value(json.loads(_docker(["inspect", identity]))[0])
        _verify_labels(self.binding, object_value(object_value(inspection["Config"])["Labels"]))
        if (
            inspection["Id"] != identity
            or inspection["Image"] != self.binding.candidate_image_digest
        ):
            raise HarnessError("WORKER_FAULT_RUNNER_IDENTITY_CHANGED")
        return identity

    def _invoke(self, program: str, run_id: UUID, *args: str) -> object:
        output = _docker(
            ["exec", self._runner(), "python", "-c", program, str(run_id), *args], timeout=90
        )
        receipts = [
            line for line in output.splitlines() if line.startswith("FLOWTEST_WORKER_RECEIPT:")
        ]
        if len(receipts) != 1:
            raise HarnessError("WORKER_FAULT_PROCESS_RECEIPT_MISSING")
        return json.loads(receipts[0].split(":", 1)[1])

    def parallel_claims(self, run_id: UUID) -> WorkerFaultReceipt:
        raw = self._invoke(CLAIM_PARENT, run_id, CLAIM_CHILD)
        if not isinstance(raw, list) or len(raw) != 2:
            raise HarnessError("WORKER_FAULT_ACTOR_COUNT_CHANGED")
        return WorkerFaultReceipt(
            container_id=self.binding.runner_container_id,
            actor_processes=tuple(WorkerProcess.model_validate(item) for item in raw),
            queued_before_claim=True,
        )

    def duplicate_delivery(self, run_id: UUID) -> WorkerFaultReceipt:
        raw = self._invoke(DUPLICATE_DELIVERY, run_id)
        if not isinstance(raw, list) or len(raw) != 2:
            raise HarnessError("WORKER_FAULT_DUPLICATE_TASK_RECEIPT_MISSING")
        return WorkerFaultReceipt(
            container_id=self.binding.runner_container_id,
            duplicate_tasks=tuple(UUID(str(identity)) for identity in raw),
            duplicate_tasks_completed=True,
        )

    def kill_and_restart(self) -> WorkerFaultReceipt:
        self.workers._check()
        primary = next(item for item in self.workers.identities if item.role == "runner-worker")
        _docker(["kill", "--signal", "KILL", primary.container_id])
        try:
            inspection = object_value(json.loads(_docker(["inspect", primary.container_id]))[0])
            state = object_value(inspection["State"])
            if state["Running"] is not False or state["ExitCode"] != 137:
                raise HarnessError("WORKER_FAULT_KILL_NOT_CONFIRMED")
        finally:
            _docker(["start", primary.container_id])
        self.workers._check()
        return WorkerFaultReceipt(
            container_id=primary.container_id, killed_signal=9, exact_container_restarted=True
        )
