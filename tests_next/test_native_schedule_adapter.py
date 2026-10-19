import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from ui.schedule import native_request
from ui.workbench import WorkbenchController


class NativeScheduleAdapterTests(unittest.TestCase):
    def definition(self, **updates):
        return dict(id='test', kind='daily', expression='09:00', action='Synthetic task',
                    mode='execute', enabled=True, timezone_name='Asia/Shanghai', **updates)

    def test_calendar_conversion_and_rejection(self):
        definition=self.definition()
        self.assertEqual(native_request(definition)['daily'], {'time':'09:00:00','time_zone':'Asia/Shanghai'})
        definition.update(kind='weekly',expression='6 23:50')
        self.assertEqual(native_request(definition)['weekly']['weekdays'],[7])
        definition.update(kind='once',expression='2030-01-02T09:30:00+08:00')
        self.assertEqual(native_request(definition)['at'],'2030-01-02T01:30:00.000Z')
        with self.assertRaises(ValueError):native_request(definition,datetime(2031,1,1,tzinfo=timezone.utc))
        definition.update(kind='daily',expression='9:00')
        with self.assertRaises(ValueError):native_request(definition)
        definition.update(expression='09:00',mode='reminder')
        with self.assertRaises(ValueError):native_request(definition)

    def test_unknown_transport_is_never_retried(self):
        controller=WorkbenchController(Path('.'))
        controller.handoff_context=MagicMock(return_value={})
        controller.adapter=MagicMock()
        controller.adapter._rpc.side_effect=TimeoutError()
        payload={'request_id':'request-1234567890','confirmed':True,'workspace_id':'w','session_id':'s','definition':self.definition()}
        result=controller.create_native_schedule(payload)
        self.assertEqual(result['state'],'unknown')
        controller.adapter._rpc.assert_called_once()
        payload['confirmed']=False
        with self.assertRaises(ValueError):controller.create_native_schedule(payload)
        controller.adapter._rpc.assert_called_once()
