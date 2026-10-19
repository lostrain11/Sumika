"""Windows UIA adapter using pywinauto; never chooses a target by guessed title."""
import hashlib
import json
class WindowsController:
    def __init__(self, *, enabled=True): self.enabled=enabled

    def _window(self, handle, process_id):
        if not self.enabled: raise PermissionError('desktop control disabled')
        if type(handle) is not int or type(process_id) is not int: raise ValueError('numeric handle and process id required')
        from pywinauto import Desktop
        window=Desktop(backend='uia').window(handle=handle).wrapper_object()
        if window.process_id()!=process_id: raise ValueError('window process changed')
        return window

    def inspect(self,handle,process_id,*,limit=200):
        if type(limit) is not int or not 1<=limit<=1000:raise ValueError('invalid limit')
        w=self._window(handle,process_id)
        items=[]
        for c in [w,*w.descendants()][:limit]:
            i=c.element_info
            rect=c.rectangle()
            items.append(dict(name=i.name,automation_id=i.automation_id,control_type=i.control_type,enabled=c.is_enabled(),visible=c.is_visible(),rectangle=[rect.left,rect.top,rect.right,rect.bottom]))
        return items

    def act(self,handle,process_id,action,*,approved=False,expected_snapshot_hash=None,automation_id=None,control_type=None,text=None,keys=None):
        # This guard is not an authorization service. Harness must approve exact arguments.
        if approved is not True:raise PermissionError('native approval required for desktop mutation')
        if action not in ('set_text','invoke','focus','minimize','maximize','restore','hotkey'):
            raise ValueError('unsupported desktop action')
        if action=='set_text' and not isinstance(text,str):raise ValueError('text required')
        if action=='hotkey' and (not isinstance(keys,list) or not keys or any(not isinstance(k,str) or not k for k in keys)):
            raise ValueError('key list required')
        w=self._window(handle,process_id)
        before=self.inspect(handle,process_id)
        digest=hashlib.sha256(json.dumps(before,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if expected_snapshot_hash is not None and expected_snapshot_hash != digest:
            raise PermissionError('desktop target state changed; renew approval')
        target=w
        if automation_id is not None:
            candidates=[c for c in w.descendants() if c.element_info.automation_id==automation_id and (control_type is None or c.element_info.control_type==control_type)]
            if len(candidates)!=1:raise ValueError('control target is missing or ambiguous')
            target=candidates[0]
        if action=='hotkey':
            import pyautogui
            import ctypes
        # Once a native mutation is attempted, an exception cannot prove that
        # nothing happened. Return uncertainty instead of inviting a retry.
        phase='mutation'
        try:
            if action=='set_text':target.set_edit_text(text)
            elif action=='invoke':target.invoke()
            elif action in ('focus','minimize','maximize','restore'):
                getattr(w,'set_focus' if action=='focus' else action)()
            elif action=='hotkey':
                w.set_focus()
                if ctypes.windll.user32.GetForegroundWindow()!=handle:
                    raise RuntimeError('foreground window changed')
                pyautogui.hotkey(*keys)
            phase='post_action_inspection'
            after=self.inspect(handle,process_id)
        except Exception as error:
            return dict(status='unknown',action_attempted=True,retry_allowed=False,
                        failure_phase=phase,error_type=type(error).__name__,
                        boundary='Native mutation attempted; effects may have occurred; inspect before any new approval')
        return dict(status='performed',verification=after,verification_hash=hashlib.sha256(json.dumps(after,ensure_ascii=False,separators=(',',':')).encode()).hexdigest())
