from pathlib import Path
import tempfile
import unittest

from m832d_ble.backend import run_job
from m832d_ble.config import DeviceConfig
from m832d_ble.model import BackendExit, JobInvocation, SetupRequiredError

from .test_runtime import FakeChannels


class RecordingTransport:
    failure = None

    def __init__(self, config, callback, cancel_event):
        self.config = config
        self.callback = callback
        self.cancel_event = cancel_event
        self.submitted_bytes = 0
        self.acknowledged_bytes = 0
        self.closed = False

    async def connect(self):
        if self.failure == 'connect':
            raise RuntimeError('injected connection failure')
        if self.failure == 'setup':
            raise SetupRequiredError('pairing missing')

    async def write(self, data):
        self.submitted_bytes += len(data)
        if self.failure == 'write':
            raise RuntimeError('injected uncertain write failure')
        self.acknowledged_bytes += len(data)

    async def close(self):
        self.closed = True


class BackendOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.job = Path(self.directory.name) / 'job.bin'
        self.job.write_bytes(b'binary\x00job')
        self.invocation = JobInvocation('42', 'user', 'title', 1, '', str(self.job))
        self.config = DeviceConfig('D6:4D:F2:16:B6:BF')

    async def asyncTearDown(self):
        self.directory.cleanup()

    async def test_success_reports_transport_delivery(self):
        RecordingTransport.failure = None
        result = await run_job(
            self.invocation, self.config, FakeChannels(), RecordingTransport,
        )
        self.assertEqual(result, BackendExit.OK)

    async def test_failure_before_data_is_retryable(self):
        RecordingTransport.failure = 'connect'
        result = await run_job(
            self.invocation, self.config, FakeChannels(), RecordingTransport,
        )
        self.assertEqual(result, BackendExit.RETRY)

    async def test_setup_failure_holds_job(self):
        RecordingTransport.failure = 'setup'
        result = await run_job(
            self.invocation, self.config, FakeChannels(), RecordingTransport,
        )
        self.assertEqual(result, BackendExit.HOLD)

    async def test_failure_after_submission_stops_queue(self):
        RecordingTransport.failure = 'write'
        result = await run_job(
            self.invocation, self.config, FakeChannels(), RecordingTransport,
        )
        self.assertEqual(result, BackendExit.STOP)


if __name__ == '__main__':
    unittest.main()
