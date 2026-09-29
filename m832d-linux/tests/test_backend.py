from pathlib import Path
from io import BytesIO, StringIO
import tempfile
import unittest
from unittest.mock import patch

from m832d_ble import backend
from m832d_ble.backend import run_job
from m832d_ble.config import DeviceConfig
from m832d_ble.model import BackendExit, JobInvocation, SetupRequiredError

from .test_runtime import FakeChannels


class RecordingTransport:
    failure = None
    last_instance = None

    def __init__(self, config, callback, cancel_event, pairing_callback=None):
        self.config = config
        self.callback = callback
        self.cancel_event = cancel_event
        self.pairing_callback = pairing_callback or (lambda active: None)
        self.submitted_bytes = 0
        self.acknowledged_bytes = 0
        self.closed = False
        self.data = bytearray()
        RecordingTransport.last_instance = self

    async def connect(self):
        if self.failure == 'pairing':
            self.pairing_callback(True)
            self.pairing_callback(False)
        if self.failure == 'connect':
            raise RuntimeError('injected connection failure')
        if self.failure == 'setup':
            raise SetupRequiredError('pairing missing')

    async def write(self, data):
        self.submitted_bytes += len(data)
        if self.failure == 'write':
            raise RuntimeError('injected uncertain write failure')
        self.data.extend(data)
        self.acknowledged_bytes += len(data)

    async def close(self):
        self.closed = True
        if self.failure == 'cleanup':
            raise RuntimeError('injected cleanup failure')


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
        self.assertEqual(bytes(RecordingTransport.last_instance.data), b'binary\x00job')

    async def test_stdin_job_is_streamed(self):
        RecordingTransport.failure = None
        invocation = JobInvocation('43', 'user', 'stdin', 1, '', None)
        fake_stdin = type('FakeStdin', (), {'buffer': BytesIO(b'stdin\x00job')})()
        with patch.object(backend.sys, 'stdin', fake_stdin):
            result = await run_job(
                invocation, self.config, FakeChannels(), RecordingTransport,
            )
        self.assertEqual(result, BackendExit.OK)
        self.assertEqual(bytes(RecordingTransport.last_instance.data), b'stdin\x00job')

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
        self.assertEqual(RecordingTransport.last_instance.submitted_bytes, 0)
        self.assertEqual(bytes(RecordingTransport.last_instance.data), b'')

    async def test_pairing_completes_before_data_is_read(self):
        RecordingTransport.failure = 'pairing'
        result = await run_job(
            self.invocation, self.config, FakeChannels(), RecordingTransport,
        )
        self.assertEqual(result, BackendExit.OK)
        self.assertEqual(bytes(RecordingTransport.last_instance.data), b'binary\x00job')

    async def test_failure_after_submission_stops_queue(self):
        RecordingTransport.failure = 'write'
        result = await run_job(
            self.invocation, self.config, FakeChannels(), RecordingTransport,
        )
        self.assertEqual(result, BackendExit.STOP)

    async def test_cleanup_failure_after_submission_stops_queue(self):
        RecordingTransport.failure = 'cleanup'
        result = await run_job(
            self.invocation, self.config, FakeChannels(), RecordingTransport,
        )
        self.assertEqual(result, BackendExit.STOP)

    async def test_cleanup_failure_before_submission_is_retryable(self):
        RecordingTransport.failure = 'connect'
        result = await run_job(
            self.invocation, self.config, FakeChannels(), RecordingTransport,
        )
        self.assertEqual(result, BackendExit.RETRY)


class BackendMainTests(unittest.TestCase):
    def test_discovery_record_uses_explicit_address(self):
        async def fake_discover():
            return [('D6:4D:F2:16:B6:BF', 'M832D')]

        with patch.object(backend, 'discover', fake_discover), \
                patch('sys.stdout', new_callable=StringIO) as output:
            result = backend.main(['m832dble'])
        self.assertEqual(result, BackendExit.OK)
        self.assertIn('m832dble://D6-4D-F2-16-B6-BF/', output.getvalue())

    def test_malformed_invocation_stops_queue(self):
        self.assertEqual(backend.main(['m832dble', 'bad']), BackendExit.STOP)


if __name__ == '__main__':
    unittest.main()
