"""Cancel-aware async bridge to the existing streaming companion question service."""
import asyncio
import concurrent.futures

from extensions.models.cancellation import CancellationToken


class VoiceQuestionProvider:
    def __init__(self, service, *, session_id='companion-voice', on_delta=None):
        self.service = service
        self.session_id = session_id
        self.on_delta = on_delta
        self._binding = None
        self._record_history = True
        self._turn = None

    def begin_turn(self):
        self._binding = self.service.bind_question()

    async def answer(self, text):
        return await self._answer(text, on_delta=self.on_delta)

    async def _answer(self, text, *, on_delta, token=None):
        if self._binding is None:
            raise RuntimeError('voice question must bind observation before recognition')
        binding = self._binding
        token = token or CancellationToken()
        task = asyncio.create_task(asyncio.to_thread(
            self.service.ask, text, session_id=self.session_id,
            binding=binding, cancellation_token=token, on_delta=on_delta,
            record_history=self._record_history))
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            token.cancel()
            try:
                await asyncio.shield(task)
            except Exception:
                pass
            raise
        if result.get('status') in ('cancelled', 'stale_response', 'insufficient_context'):
            raise RuntimeError('voice context was invalidated or request cancelled')
        response = result.get('text')
        if not isinstance(response, str) or not response.strip():
            raise RuntimeError('voice model returned no answer')
        return response

    async def answer_and_play(self, text, player, *, on_start=None):
        """Watch generation failures even while the consumer is playing a sentence."""
        loop = asyncio.get_running_loop()
        failure = loop.create_future()
        def failed(error):
            if not failure.done():
                failure.set_result(error)
        invalidation = CancellationToken()
        def invalidated():
            loop.call_soon_threadsafe(failed, RuntimeError('voice context was invalidated during playback'))
        unregister = invalidation.register(invalidated)
        unwatch = self.service.watch_binding(self._binding, invalidation)
        speech = asyncio.create_task(player.stream(
            self.stream(text, on_failure=failed), on_start=on_start))
        try:
            done, _ = await asyncio.wait((speech, failure), return_when=asyncio.FIRST_COMPLETED)
            if failure in done:
                raise failure.result()
            await speech
        finally:
            unwatch()
            unregister()
            if not speech.done():
                speech.cancel()
            await asyncio.gather(speech, return_exceptions=True)
            failure.cancel()

    async def stream(self, text, *, on_failure=None):
        """Marshal bounded deltas to the host loop and cancel blocked producers."""
        loop = asyncio.get_running_loop()
        pending = asyncio.Queue(maxsize=16)
        token = CancellationToken()
        turn = self._turn
        binding = self._binding

        def delta(packet):
            value = packet.get('text')
            if not isinstance(value, str) or len(value) > 4096:
                raise ValueError('invalid or oversized voice delta')
            token.check()
            put = asyncio.run_coroutine_threadsafe(pending.put(packet), loop)
            try:
                while True:
                    try:
                        put.result(timeout=0.05)
                        break
                    except concurrent.futures.TimeoutError:
                        token.check()
            finally:
                if not put.done():
                    put.cancel()

        producing = asyncio.create_task(self._answer(text, on_delta=delta, token=token))
        def completed(task):
            if not task.cancelled() and on_failure is not None:
                error = task.exception()
                if error is not None:
                    on_failure(error)
        producing.add_done_callback(completed)
        received = ''
        waiting = None
        try:
            while not producing.done() or not pending.empty():
                waiting = asyncio.create_task(pending.get())
                ready, _ = await asyncio.wait((waiting, producing),
                                             return_when=asyncio.FIRST_COMPLETED)
                if producing in ready and producing.exception() is not None:
                    await producing
                if waiting not in ready:
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
                    waiting = None
                    continue
                packet = waiting.result()
                waiting = None
                if self.on_delta is not None:
                    self.on_delta({**packet, 'turn': turn})
                received += packet['text']
                if len(received) > 64000:
                    raise ValueError('voice answer exceeded buffer limit')
                yield packet['text']
            final = await producing
            if len(final) > 64000:
                raise ValueError('voice answer exceeded buffer limit')
            if not final.startswith(received):
                raise RuntimeError('voice stream does not match completed answer')
            for offset in range(len(received), len(final), 4096):
                remainder = final[offset:offset + 4096]
                if self.on_delta is not None:
                    self.on_delta({'text': remainder, 'turn': turn,
                        'observation_at': binding.observation.observed_at.isoformat(),
                        'observation_source': binding.observation.source,
                        'observation_target': binding.observation.target})
                yield remainder
        finally:
            token.cancel()
            if waiting is not None:
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
            if not producing.done():
                producing.cancel()
            await asyncio.gather(producing, return_exceptions=True)

    def voice_event(self, event, detail):
        if event in ('user_started', 'proactive_started'):
            self._turn = detail.get('turn')
            self._record_history = event == 'user_started'
            self.begin_turn()
