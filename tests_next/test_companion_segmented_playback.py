import asyncio
import unittest

from extensions.companion.segmented_playback import SegmentedPlayback, split_speech


class SegmentedPlaybackTests(unittest.IsolatedAsyncioTestCase):
    def test_split_respects_sentence_and_boundaries(self):
        parts = split_speech('第一句。第二句！ A long word that must be split', max_chars=20)
        self.assertEqual(parts[:2], ['第一句。', '第二句！'])
        self.assertTrue(all(len(part) <= 20 for part in parts))

    async def test_segments_play_in_order(self):
        played, events = [], []
        async def play(text): played.append(text)
        async def stop(): events.append('stop')
        player = SegmentedPlayback(play, stop, max_chars=20, on_event=lambda e, d: events.append(e))
        await player('第一句。第二句。')
        self.assertEqual(played, ['第一句。', '第二句。'])
        self.assertEqual(events.count('segment_started'), 2)

    async def test_cancel_stops_current_segment_and_discards_queue(self):
        started, released, played, stopped = asyncio.Event(), asyncio.Event(), [], []
        async def play(text):
            played.append(text); started.set()
            await released.wait()
        async def stop(): stopped.append(True)
        player = SegmentedPlayback(play, stop)
        task = asyncio.create_task(player('第一句。第二句。'))
        await started.wait()
        await player.cancel()
        released.set()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(played, ['第一句。'])
        self.assertTrue(stopped)

    async def test_cancel_in_start_callback_prevents_provider_dispatch(self):
        played = []
        async def play(text): played.append(text)
        async def stop(): pass
        async def event(name, detail):
            if name == 'segment_started': await player.cancel()
        player = SegmentedPlayback(play, stop, on_event=event)
        with self.assertRaises(asyncio.CancelledError):
            await player('old answer')
        self.assertEqual(played, [])

    async def test_direct_task_cancel_stops_player_without_explicit_cancel(self):
        entered = asyncio.Event()
        stopped = []
        async def play(text):
            entered.set()
            await asyncio.Event().wait()
        async def stop(): stopped.append(True)
        player = SegmentedPlayback(play, stop)
        task = asyncio.create_task(player('answer'))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(stopped, [True])

    async def test_failed_segment_stops_player_and_discards_next_segment(self):
        played, stopped = [], []
        async def play(text):
            played.append(text)
            raise OSError('device failure')
        async def stop(): stopped.append(True)
        player = SegmentedPlayback(play, stop)
        with self.assertRaises(OSError): await player('first. second.')
        self.assertEqual(played, ['first.'])
        self.assertEqual(stopped, [True])
