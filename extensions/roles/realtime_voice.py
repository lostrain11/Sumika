"""Harness-neutral realtime voice session coordinator.

Audio providers remain replaceable; this module owns lifecycle and cancellation
only. It never opens a microphone or silently retries a failed turn.
"""
from dataclasses import dataclass, field
from enum import Enum
import time
import uuid

class VoiceState(str,Enum):
    IDLE='idle'; LISTENING='listening'; TRANSCRIBING='transcribing'; RESPONDING='responding'; PLAYING='playing'; CANCELLED='cancelled'; ERROR='error'

@dataclass
class VoiceSession:
    session_id:str=field(default_factory=lambda:uuid.uuid4().hex)
    state:VoiceState=VoiceState.IDLE
    turn_id:int=0
    transcript_text:str=''
    response_text:str=''
    updated:float=field(default_factory=time.time)

    def _move(self, state):
        self.state=state;self.updated=time.time();return self.snapshot()
    def start_listening(self):
        if self.state not in (VoiceState.IDLE,VoiceState.PLAYING):raise RuntimeError('voice session is busy')
        self.turn_id+=1;self.transcript_text=self.response_text='';return self._move(VoiceState.LISTENING)
    def audio_ready(self):
        if self.state!=VoiceState.LISTENING:raise RuntimeError('audio is not being captured')
        return self._move(VoiceState.TRANSCRIBING)
    def transcribed(self,text):
        if self.state!=VoiceState.TRANSCRIBING:raise RuntimeError('audio is not transcribing')
        if not isinstance(text,str) or not text.strip():raise ValueError('valid transcript required')
        self.transcript_text=text;return self._move(VoiceState.RESPONDING)
    def responded(self,text):
        if self.state!=VoiceState.RESPONDING or not isinstance(text,str) or not text.strip():raise ValueError('valid response required')
        self.response_text=text;return self._move(VoiceState.PLAYING)
    def playback_done(self):
        if self.state!=VoiceState.PLAYING:raise RuntimeError('playback is not active')
        return self._move(VoiceState.IDLE)
    def cancel(self):
        if self.state in (VoiceState.CANCELLED,VoiceState.IDLE):return self.snapshot()
        return self._move(VoiceState.CANCELLED)
    def fail(self,reason):
        if not isinstance(reason,str) or not reason.strip():raise ValueError('failure reason required')
        self.response_text=reason;return self._move(VoiceState.ERROR)
    def snapshot(self):return dict(session_id=self.session_id,state=self.state.value,turn_id=self.turn_id,transcript=self.transcript_text,response=self.response_text,updated=self.updated)
