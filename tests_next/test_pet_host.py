import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ui.pet_host import PetHost


class PetHostTests(unittest.TestCase):
    def test_single_instance_fixed_url_and_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'SumikaPet.exe').touch()
            host=PetHost(root)
            process=Mock()
            process.poll.return_value=None
            job=Mock()
            with patch('ui.pet_host.os.name','nt'), \
                 patch('ui.pet_host.subprocess.Popen',return_value=process) as spawn, \
                 patch('ui.pet_host.ChildJob',return_value=job):
                self.assertTrue(host.start(12345)['alive'])
                host.start(12345)
                spawn.assert_called_once()
                self.assertEqual(spawn.call_args.args[0], [str(root.resolve()/'SumikaPet.exe'),'http://127.0.0.1:12345/?pet=1'])
                job.assign.assert_called_once_with(process)
                self.assertFalse(host.stop()['alive'])
                job.close.assert_called_once()
                process.wait.assert_called_once_with(timeout=5)

    def test_missing_host_never_spawns_and_invalid_port_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            host=PetHost(folder)
            with patch('ui.pet_host.subprocess.Popen') as spawn:
                with self.assertRaises(RuntimeError): host.start(12345)
                for port in (True,0,65536,'12345'):
                    with self.assertRaises(ValueError): host.start(port)
                spawn.assert_not_called()

    def test_job_assignment_failure_reclaims_child(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'SumikaPet.exe').touch()
            host=PetHost(folder)
            process=Mock()
            process.poll.return_value=None
            job=Mock()
            job.assign.side_effect=RuntimeError('job assignment failed')
            with patch('ui.pet_host.os.name','nt'), \
                 patch('ui.pet_host.subprocess.Popen',return_value=process), \
                 patch('ui.pet_host.ChildJob',return_value=job):
                with self.assertRaises(RuntimeError): host.start(12345)
                process.kill.assert_called_once()
                self.assertFalse(host.status()['alive'])
