"""Exact nonce/PID/start-tick control of a dedicated candidate MCP process."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil

from scripts.selftest.io import HarnessError
from scripts.selftest.mcp_fault_contracts import ProcessIdentity

REMOTE = r"""
import contextlib,json,os,signal,sys,time
mode,nonce,kind,*expected=sys.argv[1:]
path=('/tmp/flowtest-mcp-fault-'+nonce+'.json' if kind=='stdio'
      else '/tmp/flowtest-mcp-probe-http-8766.json')
def ticks(pid):
    try:
        fields=open('/proc/'+str(pid)+'/stat').read().split()
        return None if fields[2]=='Z' else fields[21]
    except FileNotFoundError:
        return None
def load():
    with open(path) as stream:
        value=json.load(stream)
    if value['nonce']!=nonce:
        raise RuntimeError('ownership mismatch')
    return value
def live(value):
    return ticks(value['pid'])==value['start_ticks']
if mode=='serve':
    value={'nonce':nonce,'pid':os.getpid(),'start_ticks':ticks(os.getpid())}
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream)
    try:
        sys.argv=['flowtest-mcp','--api-base-url','http://127.0.0.1:8000']
        from app.mcp.cli import main
        main()
    finally:
        with contextlib.suppress(FileNotFoundError):
            if load()==value:
                os.unlink(path)
elif mode=='identity':
    value=load()
    if not live(value):
        raise RuntimeError('process is not alive')
    print(json.dumps({key:value[key] for key in ('nonce','pid','start_ticks')}))
elif mode=='gone':
    if len(expected)!=2 or ticks(int(expected[0]))==expected[1] or os.path.exists(path):
        raise RuntimeError('exact process or registration remains')
    print(json.dumps({'nonce':nonce,'pid':int(expected[0]),'start_ticks':expected[1],
                      'removed':True}))
elif mode in ('kill','stop'):
    try:
        value=load()
    except FileNotFoundError:
        if mode=='kill':
            raise
        print(json.dumps({'removed':True,'nonce':nonce}))
    else:
        if mode=='kill' and expected!=[str(value['pid']),value['start_ticks']]:
            raise RuntimeError('exact process identity changed')
        if live(value):
            os.kill(value['pid'],signal.SIGKILL if mode=='kill' else signal.SIGTERM)
        for _ in range(50):
            if not live(value):
                break
            time.sleep(.05)
        if live(value):
            raise RuntimeError('owned process survived')
        with contextlib.suppress(FileNotFoundError):
            if load()==value:
                os.unlink(path)
        identity={key:value[key] for key in ('nonce','pid','start_ticks')}
        print(json.dumps(identity|{'removed':True}))
else:
    raise RuntimeError('unsupported mode')
"""


def process_command(
    container: str,
    nonce: str,
    mode: str,
    *,
    kind: str = "stdio",
    expected: ProcessIdentity | None = None,
) -> list[str]:
    if (
        re.fullmatch(r"[0-9a-f]{64}", container) is None
        or re.fullmatch(r"[0-9a-f]{32}", nonce) is None
        or mode not in {"serve", "identity", "kill", "stop", "gone"}
        or kind not in {"stdio", "http"}
    ):
        raise HarnessError("SELFTEST_FAULT_PROCESS_ARGUMENT_INVALID")
    docker = shutil.which("docker")
    if docker is None:
        raise HarnessError("SELFTEST_DOCKER_UNAVAILABLE")
    args = [docker, "exec", "--interactive"]
    if mode == "serve":
        args += ["--env", "FLOWTEST_MCP_SERVICE_ACCOUNT_TOKEN"]
    identity = [str(expected.pid), expected.start_ticks] if expected is not None else []
    if mode in {"kill", "gone"} and (expected is None or expected.nonce != nonce):
        raise HarnessError("SELFTEST_FAULT_EXACT_KILL_IDENTITY_REQUIRED")
    return [*args, container, "python", "-c", REMOTE, mode, nonce, kind, *identity]


async def control(
    container: str,
    nonce: str,
    mode: str,
    *,
    kind: str = "stdio",
    expected: ProcessIdentity | None = None,
) -> dict[str, object]:
    child = await asyncio.create_subprocess_exec(
        *process_command(container, nonce, mode, kind=kind, expected=expected),
        env={"PATH": os.environ.get("PATH", "")},
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        body, _ = await asyncio.wait_for(child.communicate(), timeout=8)
    except TimeoutError:
        child.kill()
        await child.wait()
        raise HarnessError("SELFTEST_FAULT_PROCESS_CONTROL_TIMEOUT") from None
    if child.returncode or len(body) > 2048:
        raise HarnessError("SELFTEST_FAULT_PROCESS_CONTROL_FAILED")
    value = json.loads(body)
    if not isinstance(value, dict) or value.get("nonce") != nonce:
        raise HarnessError("SELFTEST_FAULT_PROCESS_IDENTITY_MISMATCH")
    return value


async def kill(container: str, identity: ProcessIdentity, *, kind: str) -> ProcessIdentity:
    current = ProcessIdentity.model_validate(
        await control(container, identity.nonce, "identity", kind=kind)
    )
    if current != identity:
        raise HarnessError("SELFTEST_FAULT_PROCESS_IDENTITY_CHANGED")
    value = await control(container, identity.nonce, "kill", kind=kind, expected=identity)
    removed = value.pop("removed", None)
    if removed is not True or ProcessIdentity.model_validate(value) != identity:
        raise HarnessError("SELFTEST_FAULT_PROCESS_KILL_NOT_CONFIRMED")
    return identity
