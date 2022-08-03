import os

from datetime import datetime, timezone
from enum import IntEnum, auto
from multiprocessing.context import BaseContext
from typing import Any, Dict, Set

from sanic.log import Colors, logger


def get_now():
    now = datetime.now(tz=timezone.utc)
    return now


class ProcessState(IntEnum):
    IDLE = auto()
    STARTED = auto()
    JOINED = auto()
    TERMINATED = auto()


class WorkerProcess:
    def __init__(self, factory, name, target, kwargs, worker_state):
        self.state = ProcessState.IDLE
        self.factory = factory
        self.name = name
        self.target = target
        self.kwargs = kwargs
        self.worker_state = worker_state
        self.spawn()

    def set_state(self, state: ProcessState, force=False):
        if not force and state < self.state:
            raise Exception("...")
        self.state = state

    def start(self):
        os.environ["SANIC_WORKER_NAME"] = self.name
        logger.debug(
            f"{Colors.BLUE}Starting a process: {Colors.SANIC}%s{Colors.END}",
            self.name,
        )
        self.set_state(ProcessState.STARTED)
        self._process.start()
        if self.name not in self.worker_state:
            self.worker_state[self.name] = {
                "pid": self.pid,
                "start_at": get_now(),
                "starts": 1,
            }
        del os.environ["SANIC_WORKER_NAME"]

    def join(self):
        self.set_state(ProcessState.JOINED)
        self._process.join()

    def terminate(self):
        logger.debug(
            f"{Colors.BLUE}Terminating a process: {Colors.SANIC}%s "
            f"{Colors.BLUE}[%s]{Colors.END}",
            self.name,
            self.pid,
        )
        self.set_state(ProcessState.TERMINATED, force=True)
        self._process.terminate()
        del self.worker_state[self.name]

    def restart(self, **kwargs):
        logger.debug(
            f"{Colors.BLUE}Restarting a process: {Colors.SANIC}%s "
            f"{Colors.BLUE}[%s]{Colors.END}",
            self.name,
            self.pid,
        )
        self._process.terminate()
        self.set_state(ProcessState.IDLE, force=True)
        self.kwargs.update(
            {"config": {k.upper(): v for k, v in kwargs.items()}}
        )
        try:
            self.spawn()
            self.start()
        except AttributeError:
            raise RuntimeError("Restart failed")

        self.worker_state[self.name] = {
            **self.worker_state[self.name],
            "pid": self.pid,
            "starts": self.worker_state[self.name]["starts"] + 1,
            "restart_at": get_now(),
        }

    def is_alive(self):
        return self._process.is_alive()

    def spawn(self):
        if self.state is not ProcessState.IDLE:
            raise Exception("Cannot spawn a worker process until it is idle.")
        self._process = self.factory(
            name=self.name,
            target=self.target,
            kwargs=self.kwargs,
            # daemon = True
        )

    @property
    def pid(self):
        return self._process.pid


class Worker:
    def __init__(
        self,
        ident: str,
        serve,
        server_settings,
        context: BaseContext,
        worker_state: Dict[str, Any],
    ):
        self.ident = ident
        self.context = context
        self.serve = serve
        self.server_settings = server_settings
        self.worker_state = worker_state
        self.processes: Set[WorkerProcess] = set()
        self.create_process()

    def create_process(self) -> WorkerProcess:
        process = WorkerProcess(
            factory=self.context.Process,
            name=f"Sanic-{self.ident}-{len(self.processes)}",
            target=self.serve,
            kwargs={
                **self.server_settings,
            },
            worker_state=self.worker_state,
        )
        self.processes.add(process)
        return process
